from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.domain.models import (
    Company,
    ContractType,
    Eligibility,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RawPayload,
    RunSummary,
    ScoreResult,
    ScoringBreakdown,
    WorkplaceType,
)
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    CompanyRepository,
    JobRepository,
    JobScoreRepository,
    RawPayloadRepository,
    RunRepository,
)

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"

_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


# ---------------------------------------------------------------------------
# Fixtures: domain objects
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> Job:
    defaults = dict(
        source="france_travail",
        source_job_id="FT-001",
        title="DevOps Engineer",
        company="Acme Corp",
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="Looking for a DevOps engineer with Kubernetes experience.",
        url="https://example.com/jobs/ft-001",
        collected_at=_NOW,
    )
    defaults.update(overrides)
    return Job(**defaults)


def _make_scoring_breakdown() -> ScoringBreakdown:
    sr = ScoreResult(
        engine="native",
        available=True,
        score=72,
        positive_matches=("kubernetes", "docker"),
        negative_matches=(),
        missing_preferences=("terraform",),
        explanations=("Matched kubernetes (+15), docker (+10)",),
    )
    return ScoringBreakdown(
        eligible=True,
        experience=ExperienceStatus.ELIGIBLE,
        score=72,
        positive_matches=("kubernetes", "docker"),
        negative_matches=(),
        missing_preferences=("terraform",),
        explanations=("Matched kubernetes (+15), docker (+10)",),
        engines={"native": sr},
        divergence=None,
        needs_review=False,
    )


# ---------------------------------------------------------------------------
# CompanyRepository
# ---------------------------------------------------------------------------

def test_company_upsert_creates_and_returns_id(db):
    repo = CompanyRepository(db.conn)
    co = Company(name="Acme Corp", normalized_name="acme corp")
    saved = repo.upsert(co)
    assert saved.id is not None
    assert saved.normalized_name == "acme corp"


def test_company_upsert_same_normalized_name_returns_same_id(db):
    repo = CompanyRepository(db.conn)
    co = Company(name="Acme Corp", normalized_name="acme corp")
    first = repo.upsert(co)
    second = repo.upsert(co)
    assert first.id == second.id


def test_company_get_by_normalized(db):
    repo = CompanyRepository(db.conn)
    repo.upsert(Company(name="Acme Corp", normalized_name="acme corp", website="https://acme.example"))
    result = repo.get_by_normalized("acme corp")
    assert result is not None
    assert result.website == "https://acme.example"


def test_company_get_by_normalized_missing(db):
    repo = CompanyRepository(db.conn)
    assert repo.get_by_normalized("nobody") is None


# ---------------------------------------------------------------------------
# RawPayloadRepository
# ---------------------------------------------------------------------------

def test_rawpayload_save(db):
    repo = RawPayloadRepository(db.conn)
    p = RawPayload(
        source="france_travail",
        source_id="FT-001",
        fetched_at=_NOW,
        payload_json='{"id": "FT-001"}',
    )
    repo.save(p)
    row = db.conn.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0]
    assert row == 1


def test_rawpayload_save_duplicate_ignored(db):
    repo = RawPayloadRepository(db.conn)
    p = RawPayload(source="france_travail", source_id="FT-001", fetched_at=_NOW, payload_json="{}")
    repo.save(p)
    repo.save(p)  # same (source, source_item_id, fetched_at) → ignored
    count = db.conn.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# JobRepository
# ---------------------------------------------------------------------------

def test_job_save_returns_id(db):
    job = _make_job()
    repo = JobRepository(db.conn)
    saved = repo.save(job)
    assert saved.id is not None


def test_job_roundtrip_basic_fields(db):
    job = _make_job(
        eligibility=Eligibility.ELIGIBLE,
        score=72,
        experience=ExperienceRequirement(
            status=ExperienceStatus.ELIGIBLE, min_years=3.0, evidence="3 ans d'expérience"
        ),
    )
    repo = JobRepository(db.conn)
    saved = repo.save(job)
    loaded = repo.get(saved.id)

    assert loaded is not None
    assert loaded.source == "france_travail"
    assert loaded.source_job_id == "FT-001"
    assert loaded.title == "DevOps Engineer"
    assert loaded.eligibility == Eligibility.ELIGIBLE
    assert loaded.score == 72
    assert loaded.experience is not None
    assert loaded.experience.status == ExperienceStatus.ELIGIBLE
    assert loaded.experience.min_years == 3.0
    assert loaded.experience.evidence == "3 ans d'expérience"


def test_job_roundtrip_scoring_breakdown(db):
    bd = _make_scoring_breakdown()
    job = _make_job(eligibility=Eligibility.ELIGIBLE, score=72, scoring_breakdown=bd)
    repo = JobRepository(db.conn)
    saved = repo.save(job)
    loaded = repo.get(saved.id)

    assert loaded.scoring_breakdown is not None
    assert loaded.scoring_breakdown.score == 72
    assert loaded.scoring_breakdown.needs_review is False
    assert "kubernetes" in loaded.scoring_breakdown.positive_matches
    assert loaded.scoring_breakdown.engines["native"].engine == "native"


def test_job_rejected_stored(db):
    job = _make_job(
        eligibility=Eligibility.REJECTED,
        rejection_reason="EXPERIENCE: requires 5y, candidate has 2y",
        experience=ExperienceRequirement(
            status=ExperienceStatus.REJECTED, min_years=5.0
        ),
    )
    repo = JobRepository(db.conn)
    saved = repo.save(job)
    loaded = repo.get(saved.id)

    assert loaded is not None
    assert loaded.eligibility == Eligibility.REJECTED
    assert loaded.rejection_reason == "EXPERIENCE: requires 5y, candidate has 2y"


def test_job_upsert_same_source_updates_not_duplicates(db):
    repo = JobRepository(db.conn)
    job = _make_job(title="DevOps Engineer")
    first = repo.save(job)

    updated_job = _make_job(title="Senior DevOps Engineer")
    second = repo.save(updated_job)

    # Same id, updated title
    assert first.id == second.id
    loaded = repo.get(first.id)
    assert loaded.title == "Senior DevOps Engineer"

    total = db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert total == 1


def test_list_eligible(db):
    repo = JobRepository(db.conn)
    repo.save(_make_job(source_job_id="FT-001", eligibility=Eligibility.ELIGIBLE, score=72))
    repo.save(_make_job(source_job_id="FT-002", eligibility=Eligibility.ELIGIBLE, score=55))
    repo.save(_make_job(source_job_id="FT-003", eligibility=Eligibility.REJECTED))

    all_eligible = repo.list_eligible()
    assert len(all_eligible) == 2

    strong = repo.list_eligible(min_score=70)
    assert len(strong) == 1
    assert strong[0].score == 72


def test_list_rejected(db):
    repo = JobRepository(db.conn)
    repo.save(_make_job(source_job_id="FT-001", eligibility=Eligibility.REJECTED))
    repo.save(_make_job(source_job_id="FT-002", eligibility=Eligibility.ELIGIBLE, score=80))

    rejected = repo.list_rejected()
    assert len(rejected) == 1
    assert rejected[0].eligibility == Eligibility.REJECTED


def test_job_no_experience_no_breakdown(db):
    job = _make_job()
    repo = JobRepository(db.conn)
    saved = repo.save(job)
    loaded = repo.get(saved.id)
    assert loaded.experience is None
    assert loaded.scoring_breakdown is None


def test_job_get_missing_returns_none(db):
    repo = JobRepository(db.conn)
    assert repo.get(99999) is None


# ---------------------------------------------------------------------------
# JobScoreRepository
# ---------------------------------------------------------------------------

def test_job_score_save(db):
    job_repo = JobRepository(db.conn)
    saved = job_repo.save(_make_job())

    score_repo = JobScoreRepository(db.conn)
    sr = ScoreResult(engine="native", available=True, score=72)
    score_repo.save(saved.id, sr, scored_at=_NOW)

    row = db.conn.execute(
        "SELECT engine, available, score FROM job_scores WHERE job_id = ?", (saved.id,)
    ).fetchone()
    assert row["engine"] == "native"
    assert row["available"] == 1
    assert row["score"] == 72


def test_job_score_upsert(db):
    job_repo = JobRepository(db.conn)
    saved = job_repo.save(_make_job())

    score_repo = JobScoreRepository(db.conn)
    score_repo.save(saved.id, ScoreResult(engine="native", available=True, score=60), _NOW)
    score_repo.save(saved.id, ScoreResult(engine="native", available=True, score=75), _NOW)

    row = db.conn.execute(
        "SELECT score FROM job_scores WHERE job_id = ? AND engine = 'native'", (saved.id,)
    ).fetchone()
    assert row["score"] == 75

    count = db.conn.execute("SELECT COUNT(*) FROM job_scores").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# RunRepository
# ---------------------------------------------------------------------------

def test_run_save_returns_id(db):
    repo = RunRepository(db.conn)
    summary = RunSummary(
        pipeline="jobs",
        fetched=10,
        normalized=10,
        rejected_by_reason={"EXPERIENCE": 3},
        eligible=7,
        strong=2,
    )
    run_id = repo.save(summary, started_at=_NOW, finished_at=_NOW)
    assert isinstance(run_id, int)
    assert run_id > 0


def test_run_save_stores_summary_json(db):
    repo = RunRepository(db.conn)
    summary = RunSummary(pipeline="jobs", fetched=5, eligible=5, strong=1)
    run_id = repo.save(summary, _NOW, _NOW)

    import json
    row = db.conn.execute("SELECT summary_json FROM runs WHERE id = ?", (run_id,)).fetchone()
    data = json.loads(row["summary_json"])
    assert data["fetched"] == 5
    assert data["strong"] == 1


# ---------------------------------------------------------------------------
# list_unnotified / mark_notified
# ---------------------------------------------------------------------------

def test_list_unnotified_empty_db(db):
    repo = JobRepository(db.conn)
    assert repo.list_unnotified() == []


def test_list_unnotified_returns_eligible_only(db):
    repo = JobRepository(db.conn)
    repo.save(_make_job(source_job_id="FT-001", eligibility=Eligibility.ELIGIBLE, score=80))
    repo.save(_make_job(source_job_id="FT-002", eligibility=Eligibility.REJECTED))
    jobs = repo.list_unnotified()
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "FT-001"


def test_list_unnotified_excludes_already_notified(db):
    repo = JobRepository(db.conn)
    repo.save(_make_job(source_job_id="FT-001", eligibility=Eligibility.ELIGIBLE, score=80))
    repo.save(_make_job(source_job_id="FT-002", eligibility=Eligibility.ELIGIBLE, score=70))
    # Mark FT-001 as notified
    j1 = repo.list_unnotified()[0]  # score 80 comes first
    repo.mark_notified([j1.id], _NOW)
    remaining = repo.list_unnotified()
    assert len(remaining) == 1
    assert remaining[0].source_job_id == "FT-002"


def test_mark_notified_empty_list_is_noop(db):
    repo = JobRepository(db.conn)
    repo.mark_notified([], _NOW)  # must not raise


def test_list_unnotified_ordered_by_score_desc(db):
    repo = JobRepository(db.conn)
    for sid, score in [("FT-001", 55), ("FT-002", 90), ("FT-003", 72)]:
        repo.save(_make_job(source_job_id=sid, eligibility=Eligibility.ELIGIBLE, score=score))
    scores = [j.score for j in repo.list_unnotified()]
    assert scores == [90, 72, 55]


# ---------------------------------------------------------------------------
# reset_notified_since
# ---------------------------------------------------------------------------

def test_reset_notified_since_resets_matching_jobs(db):
    from datetime import date
    repo = JobRepository(db.conn)
    # Notified on Oct 2 — within reset window (since Oct 1)
    j = repo.save(_make_job(
        source_job_id="FT-001", eligibility=Eligibility.ELIGIBLE, score=80,
    ))
    notified_oct2 = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)
    repo.mark_notified([j.id], notified_oct2)

    count = repo.reset_notified_since(date(2026, 10, 1))
    assert count == 1
    assert repo.list_unnotified() != []  # job is unnotified again


def test_reset_notified_since_leaves_earlier_jobs_alone(db):
    from datetime import date
    repo = JobRepository(db.conn)
    # Notified on Sep 30 — before the reset window (since Oct 1)
    j = repo.save(_make_job(
        source_job_id="FT-001", eligibility=Eligibility.ELIGIBLE, score=80,
    ))
    notified_sep30 = datetime(2026, 9, 30, 9, 0, 0, tzinfo=UTC)
    repo.mark_notified([j.id], notified_sep30)

    count = repo.reset_notified_since(date(2026, 10, 1))
    assert count == 0
    assert repo.list_unnotified() == []  # still excluded


def test_reset_notified_since_ignores_rejected_jobs(db):
    from datetime import date
    repo = JobRepository(db.conn)
    j = repo.save(_make_job(source_job_id="FT-001", eligibility=Eligibility.REJECTED))
    # Directly stamp notified_at (unlikely in practice but tests the WHERE clause)
    db.conn.execute(
        "UPDATE jobs SET notified_at = ? WHERE id = ?",
        (datetime(2026, 10, 2, tzinfo=UTC).isoformat(), j.id),
    )
    db.conn.commit()
    count = repo.reset_notified_since(date(2026, 10, 1))
    assert count == 0  # rejected job not touched


def test_reset_notified_since_returns_zero_when_nothing_matches(db):
    from datetime import date
    repo = JobRepository(db.conn)
    assert repo.reset_notified_since(date(2026, 10, 1)) == 0
