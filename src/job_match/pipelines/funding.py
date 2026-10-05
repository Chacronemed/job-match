import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from job_match.adapters.funding.base import FeedError, FundingSource
from job_match.config.schema import Settings
from job_match.domain.models import Article, Company, FundingEvent, RunSummary
from job_match.funding.article import ArticleFetcher, make_extract
from job_match.funding.extractor import extract_funding
from job_match.funding.leads import build_lead
from job_match.normalization.company import normalize_company
from job_match.normalization.url import normalize_article_url
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    ArticleRepository,
    CompanyRepository,
    FundingEventRepository,
    LeadRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Context:
    settings: Settings
    articles: ArticleRepository
    companies: CompanyRepository
    events: FundingEventRepository
    leads: LeadRepository


@dataclass(frozen=True, slots=True)
class _Outcome:
    is_funding: bool
    events: int = 0
    leads: int = 0
    leads_deduped: int = 0
    no_company: bool = False


def _context(settings: Settings, db: Database) -> _Context:
    return _Context(
        settings=settings,
        articles=ArticleRepository(db.conn),
        companies=CompanyRepository(db.conn),
        events=FundingEventRepository(db.conn),
        leads=LeadRepository(db.conn),
    )


def _process_article(
    article: Article, text: str, ctx: _Context, *, now: datetime, dry_run: bool
) -> _Outcome:
    """Extract funding facts from the in-memory text; store event + lead; mark processed.

    The text itself is never persisted. One event per article (M11); a funding article
    whose company cannot be identified is flagged but yields no event and no lead.
    """
    ex = extract_funding(article.title, text)
    if not ex.is_funding:
        if not dry_run and article.id is not None:
            ctx.articles.mark_processed(article.id, False, now)
        return _Outcome(is_funding=False)

    if not ex.company:
        if not dry_run and article.id is not None:
            ctx.events.delete_for_article_except(article.id, [])
            ctx.articles.mark_processed(article.id, True, now)
        return _Outcome(is_funding=True, no_company=True)

    if dry_run or article.id is None:
        return _Outcome(is_funding=True, events=1, leads=1)

    company = ctx.companies.upsert(
        Company(name=ex.company, normalized_name=normalize_company(ex.company))
    )
    event = ctx.events.upsert(
        FundingEvent(
            company_id=company.id,  # type: ignore[arg-type]
            source=article.source,
            article_url=article.url,
            article_id=article.id,
            collected_at=now,
            amount=ex.amount,
            currency=ex.currency,
            round=ex.round,
            date=article.published_at.date().isoformat() if article.published_at else None,
            investors=ex.investors,
            location=ex.location,
            recruiting_signal=ex.hiring,
            evidence=ex.evidence,
        )
    )
    ctx.events.delete_for_article_except(article.id, [event.id])  # type: ignore[list-item]

    window_start = now - timedelta(days=ctx.settings.funding.lead_dedup_days)
    leads = deduped = 0
    if ctx.leads.has_recent(company.id, window_start, exclude_event_id=event.id):  # type: ignore[arg-type]
        deduped = 1
    else:
        ctx.leads.upsert(build_lead(event, ex, now))
        leads = 1

    ctx.articles.mark_processed(article.id, True, now)
    return _Outcome(is_funding=True, events=1, leads=leads, leads_deduped=deduped)


def _bump(by_source: dict[str, dict[str, int]], source: str, key: str, n: int = 1) -> None:
    bucket = by_source.setdefault(
        source, {"articles": 0, "funding": 0, "events": 0, "leads": 0}
    )
    bucket[key] = bucket.get(key, 0) + n


def _tally(
    by_source: dict[str, dict[str, int]], source: str, outcome: _Outcome
) -> None:
    _bump(by_source, source, "articles")
    if outcome.is_funding:
        _bump(by_source, source, "funding")
    if outcome.events:
        _bump(by_source, source, "events", outcome.events)
    if outcome.leads:
        _bump(by_source, source, "leads", outcome.leads)


@dataclass
class _Counters:
    funding_articles: int = 0
    funding_events: int = 0
    funding_no_company: int = 0
    leads: int = 0
    leads_deduped: int = 0

    def add(self, outcome: _Outcome) -> None:
        self.funding_articles += int(outcome.is_funding)
        self.funding_events += outcome.events
        self.funding_no_company += int(outcome.no_company)
        self.leads += outcome.leads
        self.leads_deduped += outcome.leads_deduped


def run_funding(
    sources: Sequence[FundingSource],
    settings: Settings,
    db: Database,
    fetcher: ArticleFetcher,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Feeds → ArticleRef → URL dedup → fetch → extract funding → store extract + event + lead.

    The full article text is a local variable and is discarded after extraction.
    """
    ctx = _context(settings, db)
    now = datetime.now(UTC)
    max_chars = settings.funding.extract_max_chars

    feeds = found = new = skipped = errors = processed = api_calls = 0
    seen_this_run: set[str] = set()
    counters = _Counters()
    by_source: dict[str, dict[str, int]] = {}

    for source in sources:
        if limit is not None and processed >= limit:
            break
        try:
            refs = list(source.fetch_articles(since=None))
        except FeedError as exc:
            logger.warning("feed failed: %s", exc)
            errors += 1
            continue
        except Exception as exc:  # one broken source never aborts the run
            logger.warning("feed %s raised %s: %s", source.name, type(exc).__name__, exc)
            errors += 1
            continue
        finally:
            api_calls += getattr(source, "api_calls_count", 0)
        feeds += 1

        for ref in refs:
            if limit is not None and processed >= limit:
                break
            processed += 1
            found += 1

            url = normalize_article_url(ref.url)
            if url in seen_this_run or ctx.articles.exists(url):
                skipped += 1
                continue
            seen_this_run.add(url)

            text = fetcher.fetch_text(ref.url)
            if text is None:
                errors += 1  # not stored: retried on the next run while still in the feed
                continue

            article = Article(
                source=source.name,
                url=url,
                title=ref.title,
                collected_at=now,
                published_at=ref.published_at,
                extract=make_extract(text, max_chars),
            )
            if not dry_run:
                article = ctx.articles.save(article)
            new += 1

            try:
                outcome = _process_article(article, text, ctx, now=now, dry_run=dry_run)
            except Exception as exc:  # extraction bug on one article never aborts the run
                logger.warning("extraction failed for %s: %s", url, exc)
                errors += 1
                continue
            counters.add(outcome)
            _tally(by_source, source.name, outcome)

    api_calls += fetcher.api_calls_count
    return RunSummary(
        pipeline="funding",
        feeds=feeds,
        fetched=found,
        normalized=found,
        articles=new,
        duplicates=skipped,
        errors=errors,
        api_calls=api_calls,
        funding_articles=counters.funding_articles,
        funding_events=counters.funding_events,
        funding_no_company=counters.funding_no_company,
        leads=counters.leads,
        leads_deduped=counters.leads_deduped,
        by_source=by_source,
    )


def reprocess_funding(
    settings: Settings,
    db: Database,
    fetcher: ArticleFetcher,
    *,
    since: date | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Refetch stored articles and (re)run funding extraction.

    Default: articles never processed (M10 rows). With `since`: every article collected on or
    after that date, idempotently (events are updated in place, lead status is preserved).
    """
    ctx = _context(settings, db)
    now = datetime.now(UTC)
    articles = (
        ctx.articles.list_unprocessed(limit)
        if since is None
        else ctx.articles.list_collected_since(since, limit)
    )

    processed = errors = 0
    counters = _Counters()
    by_source: dict[str, dict[str, int]] = {}

    for article in articles:
        text = fetcher.fetch_text(article.url)
        if text is None:
            errors += 1  # processed_at stays NULL: picked up again next time
            continue
        try:
            outcome = _process_article(article, text, ctx, now=now, dry_run=dry_run)
        except Exception as exc:
            logger.warning("extraction failed for %s: %s", article.url, exc)
            errors += 1
            continue
        processed += 1
        counters.add(outcome)
        _tally(by_source, article.source, outcome)

    return RunSummary(
        pipeline="funding",
        fetched=len(articles),
        normalized=processed,
        articles=processed,
        errors=errors,
        api_calls=fetcher.api_calls_count,
        funding_articles=counters.funding_articles,
        funding_events=counters.funding_events,
        funding_no_company=counters.funding_no_company,
        leads=counters.leads,
        leads_deduped=counters.leads_deduped,
        by_source=by_source,
    )
