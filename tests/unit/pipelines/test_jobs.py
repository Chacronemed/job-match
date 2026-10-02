"""Integration tests for pipelines/jobs.py using in-memory SQLite and a fake source."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.pipelines.jobs import run_jobs

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "migrations"
_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(experience_years: float = 3.0) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=experience_years),
        skills=Skills(
            preferred=[SkillWeight(name="kubernetes", weight=25)],
            negative=[],
        ),
        filters=Filters(contract_types=[ContractType.CDI], locations=[]),
        ft_search=FTSearch(rome_codes=[], keywords=["devops"], departments=[]),
    )


def _settings() -> Settings:
    return Settings(
        strong_threshold=70,
        base_score=50,
        title_bonus=0,
        dedup_window_days=30,
        fuzzy_title_threshold=0.85,
        fuzzy_desc_threshold=0.80,
    )


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


class FakeSource:
    """A fake JobSource for testing — raw items are pre-built Job objects."""

    name = "france_travail"

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs

    def fetch(self, since):
        return iter(self._jobs)

    def to_job(self, raw: Job) -> Job:
        return raw


class BrokenSource(FakeSource):
    """First item always raises in to_job."""

    def to_job(self, raw: Job) -> Job:
        if raw == self._jobs[0]:
            raise ValueError("malformed item")
        return raw


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_eligible_job_is_stored_and_counted(db):
    job = _job("FT-001")
    summary = run_jobs(FakeSource([job]), _profile(), _settings(), db, aliases={})
    assert summary.fetched == 1
    assert summary.eligible == 1
    assert summary.duplicates == 0
    assert not summary.rejected_by_reason


def test_strong_job_counted(db):
    job = _job("FT-001")  # description contains "kubernetes" → score 75 ≥ 70
    summary = run_jobs(FakeSource([job]), _profile(), _settings(), db, aliases={})
    assert summary.strong == 1


def test_not_strong_job_counted_eligible_not_strong(db):
    job = _job("FT-001", description="Looking for a cloud engineer. No specific stack.")
    summary = run_jobs(FakeSource([job]), _profile(), _settings(), db, aliases={})
    assert summary.eligible == 1
    assert summary.strong == 0


def test_rejected_by_experience(db):
    # "5 ans" in description → min_years=5 > candidate's 3
    job = _job("FT-001", description="Poste DevOps. Minimum 5 ans d'expérience requis.")
    summary = run_jobs(FakeSource([job]), _profile(experience_years=3.0), _settings(), db, {})
    assert summary.eligible == 0
    assert summary.rejected_by_reason.get("EXPERIENCE", 0) == 1


def test_rejected_by_contract(db):
    job = _job("FT-001", contract_type=ContractType.CDD)  # profile filters CDI only
    summary = run_jobs(FakeSource([job]), _profile(), _settings(), db, {})
    assert summary.rejected_by_reason.get("CONTRACT", 0) == 1


def test_duplicate_exact_fingerprint_counted(db):
    j1 = _job("FT-001")
    j2 = _job("FT-002")  # same content, different source_job_id → same fingerprint
    # Both share the same company/title/location/contract/description
    summary = run_jobs(FakeSource([j1, j2]), _profile(), _settings(), db, {})
    assert summary.fetched == 2
    assert summary.eligible == 1
    assert summary.duplicates == 1


def test_duplicate_link_stored(db):
    j1 = _job("FT-001")
    j2 = _job("FT-002")
    run_jobs(FakeSource([j1, j2]), _profile(), _settings(), db, {})
    # Exactly one row in job_duplicates
    count = db.conn.execute("SELECT COUNT(*) FROM job_duplicates").fetchone()[0]
    assert count == 1
    row = db.conn.execute("SELECT reason, similarity FROM job_duplicates").fetchone()
    assert row["reason"] == "exact_fingerprint"
    assert row["similarity"] == 1.0


def test_dry_run_writes_nothing(db):
    job = _job("FT-001")
    summary = run_jobs(FakeSource([job]), _profile(), _settings(), db, {}, dry_run=True)
    assert summary.eligible == 1
    assert job_repo_count(db) == 0


def test_dry_run_still_counts_correctly(db):
    j1 = _job("FT-001")
    j2 = _job("FT-002", description="Minimum 5 ans d'expérience DevOps.")
    summary = run_jobs(
        FakeSource([j1, j2]), _profile(experience_years=3.0), _settings(), db, {},
        dry_run=True,
    )
    assert summary.fetched == 2
    assert summary.eligible == 1
    assert summary.rejected_by_reason.get("EXPERIENCE", 0) == 1


def test_limit_caps_processing(db):
    jobs = [_job(f"FT-{i:03}", url=f"https://example.com/jobs/{i}") for i in range(10)]
    summary = run_jobs(FakeSource(jobs), _profile(), _settings(), db, {}, limit=3)
    assert summary.fetched == 3


def test_to_job_error_counted_as_error(db):
    jobs = [_job("FT-001"), _job("FT-002", url="https://example.com/jobs/FT-002")]
    source = BrokenSource(jobs)
    summary = run_jobs(source, _profile(), _settings(), db, {})
    assert summary.errors == 1
    assert summary.fetched == 1  # only the second item succeeds


def test_run_summary_pipeline_field(db):
    summary = run_jobs(FakeSource([]), _profile(), _settings(), db, {})
    assert summary.pipeline == "jobs"


def test_aliases_expand_in_scoring(db):
    # "k8s" in description should match "kubernetes" via aliases
    job = _job("FT-001", description="We need a DevOps engineer with k8s skills.")
    aliases = {"kubernetes": ["k8s", "kube"]}
    summary = run_jobs(FakeSource([job]), _profile(), _settings(), db, aliases)
    assert summary.strong == 1  # k8s → kubernetes +25 → score 75 ≥ 70


def test_summary_invariant_rejected_unique_count(db):
    """rejected_jobs + eligible + duplicates == fetched (errors are excluded from fetched)."""
    j1 = _job("FT-001")
    j2 = _job("FT-002")   # same content as j1 → duplicate
    j3 = _job("FT-003", description="Minimum 5 ans d'expérience DevOps.")  # EXPERIENCE
    j4 = _job("FT-004", contract_type=ContractType.CDD)                    # CONTRACT
    j5 = _job("FT-005", description="Minimum 5 ans.", contract_type=ContractType.CDD)  # BOTH
    # BrokenSource raises on the first item (FT-000) → error, not counted in fetched
    source = BrokenSource([_job("FT-000"), j1, j2, j3, j4, j5])
    summary = run_jobs(source, _profile(experience_years=3.0), _settings(), db, {})

    # Core invariant
    assert summary.rejected_jobs + summary.eligible + summary.duplicates == summary.fetched

    # Exact counts
    assert summary.errors == 1         # FT-000 → to_job error
    assert summary.fetched == 5        # j1..j5 all converted successfully
    assert summary.rejected_jobs == 3  # j3, j4, j5 — unique jobs rejected
    assert summary.eligible == 1       # j1
    assert summary.duplicates == 1     # j2

    # j5 is rejected for two reasons → sum_by_reason > rejected_jobs
    assert summary.rejected_by_reason["EXPERIENCE"] == 2   # j3, j5
    assert summary.rejected_by_reason["CONTRACT"] == 2     # j4, j5
    total_by_reason = sum(summary.rejected_by_reason.values())
    assert total_by_reason > summary.rejected_jobs  # 4 > 3


def job_repo_count(db: Database) -> int:
    return db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
