"""FundingEventRepository, LeadRepository and the M11 additions to ArticleRepository."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from job_match.domain.models import Article, Company, FundingEvent, Lead
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    ArticleRepository,
    CompanyRepository,
    FundingEventRepository,
    LeadRepository,
)

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 4, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


@pytest.fixture
def seeded(db):
    """One article, one company; returns (db, article, company)."""
    article = ArticleRepository(db.conn).save(
        Article(source="maddyness", url="https://x.test/acme", title="Acme lève 10 M€",
                collected_at=_NOW, published_at=_NOW)
    )
    company = CompanyRepository(db.conn).upsert(Company(name="Acme", normalized_name="acme"))
    return db, article, company


def _event(article_id: int, company_id: int, **kw) -> FundingEvent:
    return FundingEvent(
        company_id=company_id, source="maddyness", article_url="https://x.test/acme",
        collected_at=_NOW, article_id=article_id, **kw,
    )


# ---------------------------------------------------------------------------
# Migration 0004
# ---------------------------------------------------------------------------

def test_migration_0004_adds_columns_and_indexes(db):
    assert "processed_at" in {r["name"] for r in db.conn.execute("PRAGMA table_info(articles)")}
    assert "evidence_json" in {
        r["name"] for r in db.conn.execute("PRAGMA table_info(funding_events)")
    }
    assert "priority" in {r["name"] for r in db.conn.execute("PRAGMA table_info(leads)")}
    rows = db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {r["name"] for r in rows}
    assert {"funding_events_article_co", "leads_funding_event", "articles_processed_at"} <= indexes
    assert 4 in {r[0] for r in db.conn.execute("SELECT version FROM schema_version")}


# ---------------------------------------------------------------------------
# ArticleRepository additions
# ---------------------------------------------------------------------------

def test_article_round_trip_includes_is_funding_and_processed_at(seeded):
    db, article, _ = seeded
    repo = ArticleRepository(db.conn)
    assert article.is_funding is False and article.processed_at is None

    repo.mark_processed(article.id, True, _NOW)
    got = repo.get(article.id)
    assert got.is_funding is True
    assert got.processed_at == _NOW


def test_list_unprocessed_and_collected_since(db):
    repo = ArticleRepository(db.conn)
    old = repo.save(Article(source="maddyness", url="https://x.test/old", title="old",
                            collected_at=datetime(2026, 9, 1, tzinfo=UTC)))
    new = repo.save(Article(source="maddyness", url="https://x.test/new", title="new",
                            collected_at=datetime(2026, 10, 3, 12, tzinfo=UTC)))
    repo.mark_processed(old.id, False, _NOW)

    assert [a.id for a in repo.list_unprocessed()] == [new.id]
    assert [a.id for a in repo.list_collected_since(date(2026, 10, 3))] == [new.id]  # same day
    assert [a.id for a in repo.list_collected_since(date(2026, 1, 1), limit=1)] == [old.id]


# ---------------------------------------------------------------------------
# FundingEventRepository
# ---------------------------------------------------------------------------

def test_event_upsert_round_trip(seeded):
    db, article, company = seeded
    repo = FundingEventRepository(db.conn)
    saved = repo.upsert(_event(
        article.id, company.id, amount=1e7, currency="EUR", round="series a", date="2026-10-04",
        investors=("Exemple Capital", "business angels"), recruiting_signal="recruter 30 personnes",
        evidence={"amount": "Acme lève 10 M€", "hiring": "recruter 30 personnes"},
    ))

    assert saved.id is not None
    got = repo.get(saved.id)
    assert got == saved
    assert got.investors == ("Exemple Capital", "business angels")
    assert got.evidence["amount"] == "Acme lève 10 M€"
    assert got.source == "maddyness" and got.article_url == "https://x.test/acme"  # via JOIN
    assert got.date == "2026-10-04"


def test_event_upsert_same_article_company_updates_in_place(seeded):
    db, article, company = seeded
    repo = FundingEventRepository(db.conn)
    first = repo.upsert(_event(article.id, company.id, amount=1e7, currency="EUR"))
    second = repo.upsert(_event(article.id, company.id, amount=1.2e7, currency="EUR", round="seed"))

    assert second.id == first.id
    assert second.amount == 1.2e7 and second.round == "seed"
    assert repo.count() == 1


def test_event_null_fields_stay_null(seeded):
    db, article, company = seeded
    got = FundingEventRepository(db.conn).upsert(_event(article.id, company.id))
    assert (got.amount, got.currency, got.round, got.investors, got.recruiting_signal) == (
        None, None, None, None, None)
    assert got.evidence == {}


def test_delete_for_article_except_removes_stale_event_and_its_lead(seeded):
    db, article, company = seeded
    other = CompanyRepository(db.conn).upsert(Company(name="Beta", normalized_name="beta"))
    events = FundingEventRepository(db.conn)
    leads = LeadRepository(db.conn)
    keep = events.upsert(_event(article.id, company.id))
    stale = events.upsert(_event(article.id, other.id))
    leads.upsert(Lead(company_id=other.id, funding_event_id=stale.id, reason="r", created_at=_NOW))

    removed = events.delete_for_article_except(article.id, [keep.id])

    assert removed == 1
    assert [e.id for e in events.list_for_article(article.id)] == [keep.id]
    assert leads.count() == 0


# ---------------------------------------------------------------------------
# LeadRepository
# ---------------------------------------------------------------------------

def test_lead_upsert_preserves_status_and_notified_at(seeded):
    db, article, company = seeded
    event = FundingEventRepository(db.conn).upsert(_event(article.id, company.id))
    repo = LeadRepository(db.conn)
    lead = repo.upsert(Lead(company_id=company.id, funding_event_id=event.id, reason="v1",
                            created_at=_NOW, priority="normal"))
    db.conn.execute("UPDATE leads SET status='contacted', notified_at=? WHERE id=?",
                    (_NOW.isoformat(), lead.id))
    db.conn.commit()

    again = repo.upsert(Lead(company_id=company.id, funding_event_id=event.id, reason="v2",
                             created_at=_NOW + timedelta(days=1), priority="high"))

    assert again.id == lead.id
    assert (again.reason, again.priority) == ("v2", "high")
    assert again.status == "contacted"
    assert again.notified_at == _NOW
    assert again.created_at == _NOW  # original creation kept
    assert repo.count() == 1


def test_has_recent_window_and_exclusion(seeded):
    db, article, company = seeded
    event = FundingEventRepository(db.conn).upsert(_event(article.id, company.id))
    repo = LeadRepository(db.conn)
    repo.upsert(Lead(company_id=company.id, funding_event_id=event.id, reason="r",
                     created_at=_NOW - timedelta(days=10)))

    assert repo.has_recent(company.id, _NOW - timedelta(days=30))
    assert not repo.has_recent(company.id, _NOW - timedelta(days=5))  # outside window
    assert not repo.has_recent(company.id, _NOW - timedelta(days=30), exclude_event_id=event.id)
    assert not repo.has_recent(999, _NOW - timedelta(days=30))
