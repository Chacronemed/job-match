"""M11: funding extraction inside run_funding, and reprocess_funding. In-memory SQLite,
fake feed and fake fetcher. No network."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from job_match.adapters.funding.base import ArticleRef
from job_match.config.schema import FundingConfig, Settings
from job_match.domain.models import Article, Company, FundingEvent, Lead
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    ArticleRepository,
    CompanyRepository,
    FundingEventRepository,
    LeadRepository,
)
from job_match.pipelines.funding import reprocess_funding, run_funding

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 2, 7, 0, 0, tzinfo=UTC)

FUNDING_BODY = (
    "La startup parisienne Acme SAS annonce aujourd'hui un tour de table de 10 millions d'euros "
    "en série A, mené par le fonds Exemple Capital. "
    "Avec cette levée, Acme prévoit de doubler ses effectifs d'ici douze mois."
)
NEUTRAL_BODY = (
    "La startup Acme présente sa nouvelle plateforme DevOps lors d'un salon à Paris. " * 5
)
NO_COMPANY_BODY = "La startup lève 3 M€ pour accélérer son développement en Europe."


class FakeFeed:
    def __init__(self, name: str, refs: list[ArticleRef]) -> None:
        self.name = name
        self._refs = refs
        self.api_calls_count = 1

    def fetch_articles(self, since=None):
        return iter(self._refs)


class MappedFetcher:
    """Returns a body per URL (default FUNDING_BODY); None for URLs in `broken`."""

    def __init__(self, bodies: dict[str, str] | None = None, broken: set[str] | None = None):
        self.bodies = bodies or {}
        self.calls: list[str] = []
        self._broken = broken or set()
        self.api_calls_count = 0

    def fetch_text(self, url: str) -> str | None:
        self.calls.append(url)
        self.api_calls_count += 1
        if url in self._broken:
            return None
        return self.bodies.get(url, FUNDING_BODY)


def _url(slug: str) -> str:
    return f"https://www.maddyness.com/2026/10/02/{slug}"


def _ref(slug: str, title: str = "Acme lève 10 M€") -> ArticleRef:
    # Feed links carry a trailing slash; the pipeline normalizes it away.
    return ArticleRef(url=_url(slug) + "/", title=title, published_at=_NOW)


def _settings() -> Settings:
    return Settings(funding=FundingConfig(requests_per_second=0, extract_max_chars=80))


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


# ---------------------------------------------------------------------------
# run_funding + extraction
# ---------------------------------------------------------------------------

def test_funding_article_creates_company_event_and_high_priority_lead(db):
    feed = FakeFeed("maddyness", [_ref("acme-leve", title="Acme lève 10 M€ en série A")])
    summary = run_funding([feed], _settings(), db, MappedFetcher())

    assert (summary.funding_articles, summary.funding_events, summary.leads) == (1, 1, 1)
    assert summary.funding_no_company == 0
    assert summary.by_source["maddyness"] == {"articles": 1, "funding": 1, "events": 1, "leads": 1}

    article = ArticleRepository(db.conn).get_by_url(_url("acme-leve"))
    assert article.is_funding is True and article.processed_at is not None
    assert len(article.extract) <= 81  # body never stored

    company = CompanyRepository(db.conn).get_by_normalized("acme")  # "Acme SAS" -> "acme"
    assert company is not None

    [event] = FundingEventRepository(db.conn).list_for_article(article.id)
    assert event.company_id == company.id
    assert (event.amount, event.currency, event.round) == (1e7, "EUR", "series a")
    assert event.investors == ("Exemple Capital",)
    assert event.recruiting_signal == "doubler ses effectifs"
    assert event.date == _NOW.date().isoformat()
    assert "amount" in event.evidence and "hiring" in event.evidence

    lead = LeadRepository(db.conn).get_for_event(event.id)
    assert lead.priority == "high"
    assert lead.reason.startswith("funding 10 M€ series a; hiring:")


def test_non_funding_article_is_marked_processed_without_event(db):
    feed = FakeFeed("maddyness", [_ref("salon", title="Acme au salon")])
    fetcher = MappedFetcher({_url("salon") + "/": NEUTRAL_BODY})
    summary = run_funding([feed], _settings(), db, fetcher)

    assert summary.funding_articles == 0
    article = ArticleRepository(db.conn).get_by_url(_url("salon"))
    assert article.is_funding is False and article.processed_at is not None
    assert FundingEventRepository(db.conn).count() == 0
    assert LeadRepository(db.conn).count() == 0


def test_funding_without_company_is_flagged_but_yields_nothing(db):
    feed = FakeFeed("maddyness", [_ref("anon", title="Une startup lève 3 M€")])
    fetcher = MappedFetcher({_url("anon") + "/": NO_COMPANY_BODY})
    summary = run_funding([feed], _settings(), db, fetcher)

    assert (summary.funding_articles, summary.funding_no_company) == (1, 1)
    assert (summary.funding_events, summary.leads) == (0, 0)
    assert ArticleRepository(db.conn).get_by_url(_url("anon")).is_funding is True
    assert FundingEventRepository(db.conn).count() == 0


def test_same_company_twice_in_window_gives_two_events_one_lead(db):
    feed = FakeFeed("maddyness", [_ref("acme-a"), _ref("acme-b", title="Acme lève 10 M€ (bis)")])
    summary = run_funding([feed], _settings(), db, MappedFetcher())

    assert summary.funding_events == 2
    assert (summary.leads, summary.leads_deduped) == (1, 1)
    assert LeadRepository(db.conn).count() == 1


def test_lead_older_than_window_allows_a_new_lead(db):
    company = CompanyRepository(db.conn).upsert(Company(name="Acme", normalized_name="acme"))
    old_article = ArticleRepository(db.conn).save(Article(
        source="maddyness", url="https://x.test/old", title="old",
        collected_at=_NOW - timedelta(days=60)))
    old_event = FundingEventRepository(db.conn).upsert(FundingEvent(
        company_id=company.id, source="maddyness", article_url="https://x.test/old",
        collected_at=_NOW - timedelta(days=60), article_id=old_article.id))
    LeadRepository(db.conn).upsert(Lead(company_id=company.id, funding_event_id=old_event.id,
                                        reason="old", created_at=_NOW - timedelta(days=60)))

    summary = run_funding([FakeFeed("maddyness", [_ref("acme-new")])], _settings(), db,
                          MappedFetcher())

    assert (summary.leads, summary.leads_deduped) == (1, 0)
    assert LeadRepository(db.conn).count() == 2


def test_dry_run_counts_funding_but_writes_nothing(db):
    summary = run_funding([FakeFeed("maddyness", [_ref("acme-leve")])], _settings(), db,
                          MappedFetcher(), dry_run=True)

    assert (summary.funding_articles, summary.funding_events, summary.leads) == (1, 1, 1)
    assert ArticleRepository(db.conn).count() == 0
    assert FundingEventRepository(db.conn).count() == 0
    assert LeadRepository(db.conn).count() == 0


def test_extraction_exception_is_isolated(db, monkeypatch):
    import job_match.pipelines.funding as pf

    def boom(title, text):
        raise RuntimeError("regex exploded")

    monkeypatch.setattr(pf, "extract_funding", boom)
    summary = run_funding([FakeFeed("maddyness", [_ref("a"), _ref("b")])], _settings(), db,
                          MappedFetcher())

    assert summary.articles == 2  # articles still stored
    assert summary.errors == 2
    assert summary.funding_articles == 0


# ---------------------------------------------------------------------------
# reprocess_funding
# ---------------------------------------------------------------------------

def _store_m10_article(db, slug: str, title: str = "Acme lève 10 M€", collected_at=None):
    """An article as M10 stored it: no processed_at, no funding flag."""
    return ArticleRepository(db.conn).save(Article(
        source="maddyness", url=_url(slug), title=title,
        collected_at=collected_at or _NOW, published_at=_NOW, extract="short",
    ))


def test_reprocess_default_picks_only_unprocessed_articles(db):
    _store_m10_article(db, "unprocessed")
    done = _store_m10_article(db, "done")
    ArticleRepository(db.conn).mark_processed(done.id, False, _NOW)
    fetcher = MappedFetcher()

    summary = reprocess_funding(_settings(), db, fetcher)

    assert fetcher.calls == [_url("unprocessed")]
    assert (summary.fetched, summary.articles) == (1, 1)
    assert (summary.funding_articles, summary.funding_events, summary.leads) == (1, 1, 1)
    assert ArticleRepository(db.conn).get_by_url(_url("unprocessed")).processed_at is not None
    assert summary.by_source["maddyness"]["events"] == 1


def test_reprocess_since_is_idempotent_and_preserves_lead_status(db):
    article = _store_m10_article(db, "acme")
    first = reprocess_funding(_settings(), db, MappedFetcher(), since=date(2026, 1, 1))
    [event] = FundingEventRepository(db.conn).list_for_article(article.id)
    lead = LeadRepository(db.conn).get_for_event(event.id)
    db.conn.execute("UPDATE leads SET status='contacted' WHERE id=?", (lead.id,))
    db.conn.commit()

    second = reprocess_funding(_settings(), db, MappedFetcher(), since=date(2026, 1, 1))

    assert first.funding_events == second.funding_events == 1
    [event_again] = FundingEventRepository(db.conn).list_for_article(article.id)
    assert event_again.id == event.id
    assert FundingEventRepository(db.conn).count() == 1
    assert LeadRepository(db.conn).count() == 1
    assert LeadRepository(db.conn).get_for_event(event.id).status == "contacted"
    assert second.leads_deduped == 0  # the article's own lead never dedups itself


def test_reprocess_replaces_event_when_company_changes(db):
    article = _store_m10_article(db, "acme", title="Actualité du jour")  # body decides
    reprocess_funding(_settings(), db, MappedFetcher(), since=date(2026, 1, 1))
    assert CompanyRepository(db.conn).get_by_normalized("acme") is not None

    new_body = "Beta lève 5 M€ auprès de Bpifrance."
    reprocess_funding(_settings(), db, MappedFetcher({_url("acme"): new_body}),
                      since=date(2026, 1, 1))

    [event] = FundingEventRepository(db.conn).list_for_article(article.id)
    beta = CompanyRepository(db.conn).get_by_normalized("beta")
    assert event.company_id == beta.id
    assert FundingEventRepository(db.conn).count() == 1
    assert LeadRepository(db.conn).count() == 1


def test_reprocess_since_excludes_older_articles_and_respects_limit(db):
    _store_m10_article(db, "old", collected_at=_NOW - timedelta(days=90))
    _store_m10_article(db, "a")
    _store_m10_article(db, "b")
    fetcher = MappedFetcher()

    summary = reprocess_funding(_settings(), db, fetcher, since=_NOW.date(), limit=1)

    assert fetcher.calls == [_url("a")]
    assert summary.fetched == 1


def test_reprocess_fetch_failure_is_counted_and_article_stays_unprocessed(db):
    _store_m10_article(db, "dead")
    summary = reprocess_funding(_settings(), db, MappedFetcher(broken={_url("dead")}))

    assert summary.errors == 1
    assert summary.articles == 0
    assert ArticleRepository(db.conn).get_by_url(_url("dead")).processed_at is None


def test_reprocess_dry_run_writes_nothing(db):
    _store_m10_article(db, "acme")
    summary = reprocess_funding(_settings(), db, MappedFetcher(), dry_run=True)

    assert summary.funding_articles == 1
    assert ArticleRepository(db.conn).get_by_url(_url("acme")).processed_at is None
    assert FundingEventRepository(db.conn).count() == 0


def test_company_name_casing_variants_share_one_company_and_one_lead(db):
    """Real case: the roundup says "InBolt", the dedicated article says "Inbolt"."""
    body = "L'entreprise vise les data centers."  # no funding sentence: the title decides
    feed = FakeFeed("maddyness", [
        _ref("roundup", title="InBolt lève 11 millions d'euros pour accélérer"),
        _ref("inbolt", title="Après Stellantis, Inbolt lève 11 millions d'euros"),
    ])
    fetcher = MappedFetcher({_url("roundup") + "/": body, _url("inbolt") + "/": body})

    summary = run_funding([feed], _settings(), db, fetcher)

    rows = db.conn.execute("SELECT id, name, normalized_name FROM companies").fetchall()
    assert len(rows) == 1
    assert rows[0]["normalized_name"] == "inbolt"
    assert rows[0]["name"] == "InBolt"  # first seen spelling is kept

    assert summary.funding_events == 2  # one event per article, both on the same company
    assert (summary.leads, summary.leads_deduped) == (1, 1)
    [lead] = LeadRepository(db.conn).list_all()
    assert lead.company_id == rows[0]["id"]
