"""Two linked regressions, and the reprocess command.

A dry run reported 112 eligible / 29 strong while the digest sent one job. Cause: running
the pipeline twice in a day. `save` upserts on (source, source_job_id), so the second run
re-read each posting, matched its own fingerprint, saved over its own row and then linked
that row as a duplicate of itself. `list_unnotified` excludes duplicates, so every job
disappeared from the digest and its score was blanked by the dedup branch.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    RelevanceConfig,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobDuplicateRepository, JobRepository
from job_match.pipelines.jobs import reprocess_jobs, run_jobs

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)


def _profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=3.0),
        skills=Skills(preferred=[SkillWeight(name="kubernetes", weight=25)], negative=[]),
        filters=Filters(contract_types=[ContractType.CDI], locations=[]),
        ft_search=FTSearch(keywords=["devops"], departments=[]),
        scoring=ScoringConfig(),
    )


def _settings() -> Settings:
    return Settings(strong_threshold=70, base_score=50, title_bonus=0)


def _veto_settings() -> Settings:
    """Settings with the title veto configured, as config/settings.yaml now has it."""
    s = Settings(strong_threshold=70, base_score=50, title_bonus=0)
    s.relevance = RelevanceConfig(
        target_title_keywords=["devops", "cloud"],
        role_titles=["devops", "cloud engineer"],
        dev_titles=["développeur", "java", "angular"],
    )
    return s


def _job(source_job_id: str, **overrides) -> Job:
    defaults = dict(
        source="france_travail",
        source_job_id=source_job_id,
        title="DevOps Engineer",
        company="Acme Corp",
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="We need a DevOps engineer with Kubernetes skills.",
        url=f"https://example.com/jobs/{source_job_id}",
        collected_at=_NOW,
    )
    return Job(**{**defaults, **overrides})


def _dev_job(job_id: str = "FT-DEV") -> Job:
    return _job(
        job_id,
        title="Développeur(se) - Java Angular & Cloud",
        description="Vous developpez en Java Angular sur notre cloud avec Kubernetes.",
    )


class FakeSource:
    name = "france_travail"

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs

    def fetch(self, since):
        return iter(self._jobs)

    def to_job(self, raw: Job) -> Job:
        return raw


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


# ---------------------------------------------------------------------------
# Running the same day twice
# ---------------------------------------------------------------------------

def test_running_twice_does_not_make_a_job_its_own_duplicate(db):
    job = _job("FT-001")

    run_jobs(FakeSource([job]), _profile(), _settings(), db, {})
    second = run_jobs(FakeSource([job]), _profile(), _settings(), db, {})

    assert second.duplicates == 0
    assert second.eligible == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 0
    assert db.conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"] == 1


def test_a_second_run_keeps_the_job_visible_to_the_digest(db):
    job = _job("FT-001")
    run_jobs(FakeSource([job]), _profile(), _settings(), db, {})
    run_jobs(FakeSource([job]), _profile(), _settings(), db, {})

    unnotified = JobRepository(db.conn).list_unnotified()
    assert len(unnotified) == 1
    assert unnotified[0].score is not None  # re-scored, not blanked by the dedup branch


def test_ten_consecutive_runs_still_leave_one_visible_job(db):
    job = _job("FT-001")
    for _ in range(10):
        run_jobs(FakeSource([job]), _profile(), _settings(), db, {})

    assert len(JobRepository(db.conn).list_unnotified()) == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 0


def test_a_second_run_still_detects_a_genuine_duplicate(db):
    """Only the job's own row is excluded; a different posting still dedups."""
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    second = run_jobs(
        FakeSource([_job("FT-002", url="https://example.com/jobs/other")]),
        _profile(), _settings(), db, {},
    )

    assert second.duplicates == 1
    link = db.conn.execute(
        "SELECT canonical_job_id c, duplicate_job_id d FROM job_duplicates"
    ).fetchone()
    assert link["c"] != link["d"]


def test_the_same_posting_on_another_source_is_still_a_duplicate(db):
    """The exclusion is keyed on (source, source_job_id), not on the id alone."""
    ft = _job("SAME-ID")
    jooble = _job("SAME-ID", source="jooble", url="https://jooble.org/jdp/1")

    summary = run_jobs(
        [FakeSource([ft]), type("S", (FakeSource,), {"name": "jooble"})([jooble])],
        _profile(), _settings(), db, {},
    )
    assert summary.duplicates == 1


# ---------------------------------------------------------------------------
# delete_self_links
# ---------------------------------------------------------------------------

def test_delete_self_links_removes_only_self_links(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    run_jobs(
        FakeSource([_job("FT-002", url="https://example.com/jobs/other")]),
        _profile(), _settings(), db, {},
    )
    (job_id,) = [r["id"] for r in db.conn.execute("SELECT id FROM jobs LIMIT 1")]
    dup_repo = JobDuplicateRepository(db.conn)
    dup_repo.save_link(job_id, job_id, "exact_fingerprint", 1.0)

    removed = dup_repo.delete_self_links()

    assert removed == 1
    rows = db.conn.execute(
        "SELECT canonical_job_id c, duplicate_job_id d FROM job_duplicates"
    ).fetchall()
    assert len(rows) == 1 and rows[0]["c"] != rows[0]["d"]


def test_delete_self_links_on_a_clean_db_removes_nothing(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    assert JobDuplicateRepository(db.conn).delete_self_links() == 0


# ---------------------------------------------------------------------------
# reprocess_jobs
# ---------------------------------------------------------------------------

def test_reprocess_rejects_a_job_the_new_rules_veto(db):
    first = run_jobs(FakeSource([_dev_job()]), _profile(), _settings(), db, {})
    assert first.eligible == 1  # stored before the veto existed

    summary = reprocess_jobs(_profile(), _veto_settings(), db, {})

    assert (summary.fetched, summary.eligible, summary.rejected_jobs) == (1, 0, 1)
    assert "NOT_RELEVANT" in summary.rejected_by_reason

    row = db.conn.execute("SELECT eligibility, score FROM jobs").fetchone()
    assert row["eligibility"] == "REJECTED"
    assert row["score"] is None  # the stale strong score is cleared


def test_reprocess_makes_no_api_calls(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    summary = reprocess_jobs(_profile(), _settings(), db, {})
    assert summary.api_calls == 0
    assert summary.eligible == 1


def test_reprocess_can_re_admit_a_job_the_old_rules_rejected(db):
    run_jobs(FakeSource([_dev_job()]), _profile(), _veto_settings(), db, {})
    assert db.conn.execute("SELECT eligibility FROM jobs").fetchone()["eligibility"] == "REJECTED"

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.eligible == 1
    row = db.conn.execute("SELECT eligibility, score, rejection_reason FROM jobs").fetchone()
    assert row["eligibility"] == "ELIGIBLE"
    assert row["score"] is not None
    assert row["rejection_reason"] is None


def test_reprocess_never_re_notifies(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    repo = JobRepository(db.conn)
    repo.mark_notified([j.id for j in repo.list_unnotified()], _NOW + timedelta(hours=1))

    reprocess_jobs(_profile(), _settings(), db, {})

    assert repo.list_unnotified() == []
    assert db.conn.execute("SELECT notified_at FROM jobs").fetchone()["notified_at"]


def test_reprocess_drops_self_links_and_frees_the_jobs(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    (stored,) = JobRepository(db.conn).list_eligible()
    JobDuplicateRepository(db.conn).save_link(stored.id, stored.id, "exact_fingerprint", 1.0)
    assert JobRepository(db.conn).list_unnotified() == []  # hidden from the digest

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.duplicates == 1  # one self-link removed
    assert len(JobRepository(db.conn).list_unnotified()) == 1


def test_reprocess_keeps_genuine_duplicate_links(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    run_jobs(
        FakeSource([_job("FT-002", url="https://example.com/jobs/other")]),
        _profile(), _settings(), db, {},
    )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 1

    reprocess_jobs(_profile(), _settings(), db, {})

    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 1


def test_reprocess_dry_run_changes_nothing(db):
    run_jobs(FakeSource([_dev_job()]), _profile(), _settings(), db, {})
    before = db.conn.execute("SELECT eligibility, score FROM jobs").fetchone()

    summary = reprocess_jobs(_profile(), _veto_settings(), db, {}, dry_run=True)

    after = db.conn.execute("SELECT eligibility, score FROM jobs").fetchone()
    assert summary.rejected_jobs == 1  # reports what would change
    assert (after["eligibility"], after["score"]) == (before["eligibility"], before["score"])
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE pipeline='jobs_reprocess'"
    ).fetchone()["n"] == 0


def test_reprocess_since_filters_by_collection_date(db):
    old = _job("FT-OLD", collected_at=_NOW - timedelta(days=10))
    new = _job("FT-NEW", collected_at=_NOW, url="https://example.com/jobs/new")
    run_jobs(FakeSource([old, new]), _profile(), _settings(), db, {})

    summary = reprocess_jobs(_profile(), _settings(), db, {}, since=_NOW - timedelta(days=1))
    assert summary.fetched == 1


def test_reprocess_records_its_own_run_row(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})
    reprocess_jobs(_profile(), _settings(), db, {})

    row = db.conn.execute("SELECT pipeline FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert row["pipeline"] == "jobs_reprocess"


def test_reprocess_on_an_empty_db_is_a_no_op(db):
    summary = reprocess_jobs(_profile(), _settings(), db, {})
    assert (summary.fetched, summary.eligible, summary.rejected_jobs) == (0, 0, 0)
