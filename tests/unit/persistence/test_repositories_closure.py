"""M20: closure columns, `list_to_check`, the lifecycle marks and the visibility filters."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match.domain.models import (
    Article,
    Company,
    ContractType,
    Eligibility,
    FundingEvent,
    Job,
    Lead,
    WorkplaceType,
)
from job_match.normalization.company import normalize_company
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    ArticleRepository,
    CompanyRepository,
    FundingEventRepository,
    JobDuplicateRepository,
    JobRepository,
    LeadRepository,
)

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
NOW = datetime(2026, 10, 19, 7, 0, 0, tzinfo=UTC)
DAY = timedelta(days=1)
RECHECK = timedelta(hours=24)


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


@pytest.fixture
def repo(db):
    return JobRepository(db.conn)


def _job(sid, *, eligibility=Eligibility.ELIGIBLE, score=75, source="france_travail",
         collected_at=NOW, published_at=None, company="Acme") -> Job:
    return Job(
        source=source, source_job_id=sid, title=f"DevOps {sid}", company=company,
        location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI, description="Kubernetes.",
        url=f"https://ft.test/{sid}", collected_at=collected_at, published_at=published_at,
        eligibility=eligibility, score=score,
    )


def _col(db, job_id, name):
    return db.conn.execute(f"SELECT {name} FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def _ids(rows):
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_migration_0006_adds_the_two_nullable_columns(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(jobs)")}
    assert {"closed_at", "last_checked_at"} <= cols


def test_save_upsert_keeps_the_lifecycle_columns(repo, db):
    j = repo.save(_job("A"))
    repo.mark_closed([j.id], NOW)
    repo.save(_job("A", collected_at=NOW + DAY))  # re-collected: the upsert path
    assert _col(db, j.id, "closed_at") == NOW.isoformat()
    assert _col(db, j.id, "last_checked_at") == NOW.isoformat()


# ---------------------------------------------------------------------------
# list_to_check
# ---------------------------------------------------------------------------

def test_list_to_check_returns_visible_never_checked_jobs_with_their_source(repo):
    j = repo.save(_job("A", eligibility=Eligibility.STRETCH))
    repo.save(_job("B", source="jooble"))
    rows = repo.list_to_check(NOW, 45, recheck_after=RECHECK)
    assert rows[0] == (j.id, "france_travail", "A")
    assert [r[1] for r in rows] == ["france_travail", "jooble"]


def test_list_to_check_skips_rejected_duplicates_and_closed(repo, db):
    canonical = repo.save(_job("A"))
    dup = repo.save(_job("A2"))
    JobDuplicateRepository(db.conn).save_link(canonical.id, dup.id, "exact")
    repo.save(_job("R", eligibility=Eligibility.REJECTED, score=None))
    closed = repo.save(_job("C"))
    repo.mark_closed([closed.id], NOW - DAY)
    assert _ids(repo.list_to_check(NOW, 45, recheck_after=RECHECK)) == [canonical.id]


def test_list_to_check_skips_jobs_checked_within_the_interval(repo):
    fresh = repo.save(_job("F"))
    due = repo.save(_job("D"))
    never = repo.save(_job("N"))
    repo.mark_checked([fresh.id], NOW - timedelta(hours=1))
    repo.mark_checked([due.id], NOW - timedelta(hours=25))
    # never-checked first, then the oldest check
    assert _ids(repo.list_to_check(NOW, 45, recheck_after=RECHECK)) == [never.id, due.id]


def test_list_to_check_spends_no_call_on_jobs_already_hidden_by_age(repo):
    old = repo.save(_job("O", published_at=NOW - 46 * DAY))
    old_no_date = repo.save(_job("OC", collected_at=NOW - 46 * DAY))
    young = repo.save(_job("Y", published_at=NOW - 44 * DAY, collected_at=NOW - 50 * DAY))
    rows = _ids(repo.list_to_check(NOW, 45, recheck_after=RECHECK))
    assert young.id in rows
    assert old.id not in rows and old_no_date.id not in rows


# ---------------------------------------------------------------------------
# marks
# ---------------------------------------------------------------------------

def test_mark_closed_sets_both_and_mark_checked_only_the_check(repo, db):
    a = repo.save(_job("A"))
    b = repo.save(_job("B"))
    repo.mark_closed([a.id], NOW)
    repo.mark_checked([b.id], NOW)
    assert _col(db, a.id, "closed_at") == NOW.isoformat()
    assert _col(db, a.id, "last_checked_at") == NOW.isoformat()
    assert _col(db, b.id, "closed_at") is None
    assert _col(db, b.id, "last_checked_at") == NOW.isoformat()


def test_mark_open_reopens_a_closed_job(repo, db):
    a = repo.save(_job("A"))
    repo.mark_closed([a.id], NOW - DAY)
    repo.mark_open([a.id], NOW)
    assert _col(db, a.id, "closed_at") is None
    assert _col(db, a.id, "last_checked_at") == NOW.isoformat()


def test_marks_with_no_ids_are_noops(repo):
    repo.mark_closed([], NOW)
    repo.mark_checked([], NOW)
    repo.mark_open([], NOW)


# ---------------------------------------------------------------------------
# visibility: list_unnotified / list_canonical_scored
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["list_unnotified", "list_canonical_scored"])
def test_closed_jobs_are_hidden_even_without_an_age_cutoff(repo, method):
    kept = repo.save(_job("K"))
    gone = repo.save(_job("G"))
    repo.mark_closed([gone.id], NOW)
    assert [j.id for j in getattr(repo, method)()] == [kept.id]


@pytest.mark.parametrize("method", ["list_unnotified", "list_canonical_scored"])
def test_age_cutoff_uses_the_posting_date_or_the_collection_date(repo, method):
    young = repo.save(_job("Y", published_at=NOW - 45 * DAY))
    old = repo.save(_job("O", published_at=NOW - 46 * DAY))
    old_no_date = repo.save(_job("OC", collected_at=NOW - 46 * DAY))
    young_no_date = repo.save(_job("YC", collected_at=NOW - 10 * DAY))
    # a posting date always wins over the collection date
    old_posting_young_collection = repo.save(
        _job("OP", published_at=NOW - 60 * DAY, collected_at=NOW)
    )
    listed = {j.id for j in getattr(repo, method)(now=NOW, max_age_days=45)}
    assert listed == {young.id, young_no_date.id}
    assert old.id not in listed and old_no_date.id not in listed
    assert old_posting_young_collection.id not in listed
    # without the cut-off every open job is listed
    assert len(getattr(repo, method)()) == 5


# ---------------------------------------------------------------------------
# leads: a closed job is not an open job
# ---------------------------------------------------------------------------

def test_lead_open_jobs_ignores_closed_jobs(db, repo):
    conn = db.conn
    acme = CompanyRepository(conn).upsert(
        Company(name="Acme", normalized_name=normalize_company("Acme"))
    )
    open_job = repo.save(_job("A", company="Acme"))
    closed_job = repo.save(_job("B", company="Acme"))
    for j in (open_job, closed_job):
        conn.execute("UPDATE jobs SET company_id = ? WHERE id = ?", (acme.id, j.id))
    conn.commit()
    article = ArticleRepository(conn).save(Article(
        source="maddyness", url="https://m.test/acme", title="Acme lève",
        collected_at=NOW, published_at=NOW,
    ))
    event = FundingEventRepository(conn).upsert(FundingEvent(
        company_id=acme.id, source="maddyness", article_url=article.url,
        article_id=article.id, collected_at=NOW, amount=1e6, currency="EUR",
    ))
    LeadRepository(conn).upsert(Lead(
        company_id=acme.id, funding_event_id=event.id, reason="funding", created_at=NOW,
    ))
    leads = LeadRepository(conn)
    assert leads.list_details(NOW - 30 * DAY)[0].open_jobs == 2
    repo.mark_closed([closed_job.id], NOW)
    assert leads.list_details(NOW - 30 * DAY)[0].open_jobs == 1
