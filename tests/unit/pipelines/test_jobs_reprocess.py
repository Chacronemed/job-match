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


def test_reprocess_counts_jobs_per_department_from_their_location(db):
    """The "?" bucket is where the gate cannot read a location; reprocess shows it too."""
    run_jobs(
        FakeSource([
            _job("FT-001", location="35 - Rennes"),
            _job("FT-002", location="Vierzon"),           # the communes list, not a prefix
            _job("FT-003", location="Siège social"),      # unreadable, kept (France Travail)
        ]),
        _profile(), _settings(), db, {},
    )

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.by_department == {"35": 1, "18": 1, "?": 1}


def test_reprocess_rejects_a_stored_jooble_job_outside_france(db):
    """What the digest bug looked like in the DB: a Jooble row in Bethpage, NY, eligible."""
    run_jobs(
        FakeSource([
            _job("J-US", source="jooble", location="Bethpage, NY"),
            _job("J-FR", source="jooble", location="Rennes, France"),
            _job("J-??", source="jooble", location=""),
        ]),
        _profile(), _settings(), db, {},
    )

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.eligible == 1
    assert summary.rejected_by_reason == {"LOCATION": 2}
    rows = db.conn.execute(
        "SELECT source_job_id, eligibility FROM jobs ORDER BY source_job_id"
    ).fetchall()
    assert [(r["source_job_id"], r["eligibility"]) for r in rows] == [
        ("J-??", "REJECTED"), ("J-FR", "ELIGIBLE"), ("J-US", "REJECTED"),
    ]


def test_reprocess_moves_a_stored_rejection_into_the_stretch_tier(db):
    """The rule changed: a job rejected for one year too many becomes STRETCH on replay."""
    from job_match.config.schema import ExperienceConfig

    job = _job("FT-1", description="Kubernetes. 4 ans d'expérience minimum.")
    run_jobs(FakeSource([job]), _profile(), _settings(), db, {})
    assert db.conn.execute("SELECT eligibility FROM jobs").fetchone()[0] == "REJECTED"

    settings = _settings()
    settings.experience = ExperienceConfig(stretch_years=1)
    summary = reprocess_jobs(_profile(), settings, db, {})

    assert summary.stretch == 1
    assert summary.eligible == 0
    assert summary.strong == 0
    row = db.conn.execute("SELECT eligibility, score, rejection_reason FROM jobs").fetchone()
    assert row[0] == "STRETCH"
    assert row[1] is not None
    assert row[2] is None


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

    assert summary.self_links_dropped == 1
    assert summary.duplicates == 0  # `duplicates` now counts links found, not links removed
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


# ---------------------------------------------------------------------------
# The dedup replay
# ---------------------------------------------------------------------------

_HIDDEN_DESC = (
    "Vous administrez nos clusters Kubernetes, nos pipelines CI/CD et notre IaC Terraform."
)


def _hidden(sid: str, *, collected_at: datetime, **overrides) -> Job:
    """A posting France Travail published without an employer name."""
    fields = dict(
        company="",
        title="Ingenieur DevOps (H/F)",
        location="35 - Rennes",
        description=_HIDDEN_DESC,
        collected_at=collected_at,
        url=f"https://candidat.francetravail.fr/offres/{sid}",
    )
    return _job(sid, **{**fields, **overrides})


def _store(db, *jobs: Job) -> list[int]:
    """Save rows straight to the DB, as runs before the fix left them."""
    repo = JobRepository(db.conn)
    return [repo.save(j).id for j in jobs]


def test_the_replay_links_a_pair_the_original_run_missed(db):
    older = _hidden("FT-OLD", collected_at=_NOW - timedelta(hours=1))
    newer = _hidden(
        "FT-NEW", collected_at=_NOW, description=_HIDDEN_DESC + " Poste a pourvoir."
    )
    newer_id, older_id = _store(db, newer, older)  # saved newest first, as ids show

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.duplicates == 1
    row = db.conn.execute(
        "SELECT canonical_job_id c, duplicate_job_id d FROM job_duplicates"
    ).fetchone()
    assert (row["c"], row["d"]) == (older_id, newer_id)  # the older posting stays canonical
    assert len(JobRepository(db.conn).list_unnotified()) == 1


def test_the_replay_is_idempotent(db):
    _store(
        db,
        _hidden("FT-OLD", collected_at=_NOW - timedelta(hours=1)),
        _hidden("FT-NEW", collected_at=_NOW, description=_HIDDEN_DESC + " Urgent."),
    )
    first = reprocess_jobs(_profile(), _settings(), db, {})
    second = reprocess_jobs(_profile(), _settings(), db, {})

    assert (first.duplicates, second.duplicates) == (1, 0)
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 1


def test_the_replay_reports_in_a_dry_run_without_writing(db):
    _store(
        db,
        _hidden("FT-OLD", collected_at=_NOW - timedelta(hours=1)),
        _hidden("FT-NEW", collected_at=_NOW, description=_HIDDEN_DESC + " Urgent."),
    )

    summary = reprocess_jobs(_profile(), _settings(), db, {}, dry_run=True)

    assert summary.duplicates == 1  # what it would link
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 0


def test_the_replay_keeps_two_departments_apart(db):
    _store(
        db,
        _hidden("FT-RNS", collected_at=_NOW - timedelta(hours=1)),
        _hidden("FT-PAR", collected_at=_NOW, location="75 - Paris"),
    )

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.duplicates == 0
    assert len(JobRepository(db.conn).list_unnotified()) == 2


def test_the_replay_leaves_an_unrelated_job_alone(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {})

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert summary.duplicates == 0
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 0


def test_the_replay_removes_a_link_the_rules_no_longer_make(db):
    """The company block is department-aware now, so a cross-department link must go."""
    lille, velizy = _store(
        db,
        _job("FT-59", company="THALES", location="59 - Lambersart",
             collected_at=_NOW - timedelta(hours=1)),
        _job("FT-78", company="THALES", location="78 - Velizy-Villacoublay"),
    )
    JobDuplicateRepository(db.conn).save_link(lille, velizy, "fuzzy", 0.99)

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert (summary.stale_links_dropped, summary.duplicates) == (1, 0)
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 0
    # both reach the digest now; the Velizy row was hidden behind the Lille one
    assert len(JobRepository(db.conn).list_unnotified()) == 2


def test_the_replay_keeps_a_link_the_rules_still_make(db):
    older, newer = _store(
        db,
        _hidden("FT-OLD", collected_at=_NOW - timedelta(hours=1)),
        _hidden("FT-NEW", collected_at=_NOW, description=_HIDDEN_DESC + " Urgent."),
    )
    JobDuplicateRepository(db.conn).save_link(older, newer, "fuzzy", 0.95)

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert (summary.stale_links_dropped, summary.duplicates) == (0, 0)
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 1


def test_a_dry_run_removes_no_link(db):
    lille, velizy = _store(
        db,
        _job("FT-59", company="THALES", location="59 - Lambersart",
             collected_at=_NOW - timedelta(hours=1)),
        _job("FT-78", company="THALES", location="78 - Velizy-Villacoublay"),
    )
    JobDuplicateRepository(db.conn).save_link(lille, velizy, "fuzzy", 0.99)

    summary = reprocess_jobs(_profile(), _settings(), db, {}, dry_run=True)

    assert summary.stale_links_dropped == 1  # what it would remove
    assert db.conn.execute("SELECT COUNT(*) AS n FROM job_duplicates").fetchone()["n"] == 1


def test_the_replay_relinks_to_the_right_canonical(db):
    """A stale link and a valid one at once: remove the first, write the second."""
    wrong, older, newer = _store(
        db,
        _job("FT-WRONG", company="THALES", location="59 - Lambersart",
             collected_at=_NOW - timedelta(hours=2)),
        _hidden("FT-OLD", collected_at=_NOW - timedelta(hours=1)),
        _hidden("FT-NEW", collected_at=_NOW, description=_HIDDEN_DESC + " Urgent."),
    )
    JobDuplicateRepository(db.conn).save_link(wrong, newer, "fuzzy", 0.99)

    summary = reprocess_jobs(_profile(), _settings(), db, {})

    assert (summary.stale_links_dropped, summary.duplicates) == (1, 1)
    row = db.conn.execute(
        "SELECT canonical_job_id c, duplicate_job_id d FROM job_duplicates"
    ).fetchone()
    assert (row["c"], row["d"]) == (older, newer)
