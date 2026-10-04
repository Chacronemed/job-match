import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from job_match.adapters.funding.base import FeedError, FundingSource
from job_match.config.schema import Settings
from job_match.domain.models import Article, RunSummary
from job_match.funding.article import ArticleFetcher, make_extract
from job_match.normalization.url import normalize_article_url
from job_match.persistence.db import Database
from job_match.persistence.repositories import ArticleRepository

logger = logging.getLogger(__name__)


def run_funding(
    sources: Sequence[FundingSource],
    settings: Settings,
    db: Database,
    fetcher: ArticleFetcher,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Feeds → ArticleRef → URL dedup → fetch + extract → store short extract.

    No funding extraction here (M11). The full article text is a local variable and
    is discarded after the extract is taken.
    """
    repo = ArticleRepository(db.conn)
    now = datetime.now(UTC)
    max_chars = settings.funding.extract_max_chars

    feeds = 0
    found = 0
    new = 0
    skipped = 0
    errors = 0
    processed = 0
    seen_this_run: set[str] = set()
    api_calls = 0

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
            if url in seen_this_run or repo.exists(url):
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
                repo.save(article)
            new += 1

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
    )
