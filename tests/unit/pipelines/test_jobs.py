"""Integration tests for pipelines/jobs.py using in-memory SQLite and a fake source."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.adapters.jobs.base import QueryStat
from job_match.config.schema import (
    Candidate,
    ExperienceConfig,
    Filters,
    FTSearch,
    Profile,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.pipelines.jobs import run_jobs

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
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


def test_no_global_cap_every_fetched_item_is_processed(db):
    """The pipeline never caps: a global cap starved every query after the first.

    Volume is capped by the source, per (keyword, department) query.
    """
    jobs = [_job(f"FT-{i:03}", url=f"https://example.com/jobs/{i}") for i in range(10)]
    summary = run_jobs(FakeSource(jobs), _profile(), _settings(), db, {})
    assert summary.fetched == 10


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


# ---------------------------------------------------------------------------
# observability: runs table + per-query aggregates
# ---------------------------------------------------------------------------

class StatSource(FakeSource):
    """A fake source that exposes per-query stats, like the real adapter."""

    def __init__(self, jobs, stats) -> None:
        super().__init__(jobs)
        self.query_stats = tuple(stats)
        self.api_calls_count = len(self.query_stats)


def test_summary_aggregates_fetched_per_department_and_keyword(db):
    jobs = [_job(f"FT-{i:03}", url=f"https://example.com/jobs/{i}") for i in range(3)]
    stats = [
        QueryStat("devops", "75", 2, 40),
        QueryStat("devops", "92", 1, 1),
        QueryStat("sre", "75", 0, 0),
    ]
    summary = run_jobs(StatSource(jobs, stats), _profile(), _settings(), db, {})

    assert summary.queries == 3
    assert summary.by_area == {"75": 2, "92": 1}
    assert summary.by_keyword == {"devops": 3, "sre": 0}


def test_run_is_recorded_in_the_runs_table(db):
    stats = [QueryStat("devops", "75", 1, 1)]
    run_jobs(StatSource([_job("FT-001")], stats), _profile(), _settings(), db, {})

    rows = db.conn.execute(
        "SELECT pipeline, started_at, finished_at, summary_json FROM runs"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["pipeline"] == "jobs"
    assert rows[0]["started_at"] and rows[0]["finished_at"]

    payload = json.loads(rows[0]["summary_json"])
    assert payload["fetched"] == 1
    assert payload["eligible"] == 1
    assert payload["queries"] == 1
    assert payload["by_area"] == {"75": 1}
    assert payload["by_keyword"] == {"devops": 1}


def test_dry_run_records_no_run(db):
    run_jobs(FakeSource([_job("FT-001")]), _profile(), _settings(), db, {}, dry_run=True)
    assert db.conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == 0


# ---------------------------------------------------------------------------
# Multi-source runs
# ---------------------------------------------------------------------------

class NamedSource(FakeSource):
    """A fake source with its own name and call count."""

    def __init__(self, name: str, jobs: list[Job], calls: int = 0) -> None:
        super().__init__(jobs)
        self.name = name
        self.api_calls_count = calls


def _ft_and_jooble_same_job() -> tuple[Job, Job]:
    """The same offer as the two sources report it.

    Different ids, different location format, and Jooble has no contract type — which is
    exactly why the dedup block keys on the company alone.
    """
    description = (
        "Nous recherchons un ingenieur DevOps pour industrialiser nos deploiements "
        "Kubernetes et Terraform au sein d'une equipe de huit personnes."
    )
    ft = _job(
        "FT-77",
        title="Ingénieur DevOps",
        company="Acme Corp",
        location="92 - Nanterre",
        contract_type=ContractType.CDI,
        description=description,
        url="https://candidat.francetravail.fr/offres/FT-77",
    )
    jooble = _job(
        "JB-9001",
        source="jooble",
        title="Ingenieur DevOps",
        company="Acme Corp",
        location="Nanterre",
        contract_type=ContractType.UNKNOWN,
        description=description,
        url="https://jooble.org/jdp/9001",
    )
    return ft, jooble


def test_the_same_job_on_two_sources_becomes_canonical_plus_duplicate(db):
    ft, jooble = _ft_and_jooble_same_job()

    summary = run_jobs(
        [NamedSource("france_travail", [ft]), NamedSource("jooble", [jooble])],
        _profile(), _settings(), db, {},
    )

    assert summary.fetched == 2
    assert summary.eligible == 1    # scored once
    assert summary.duplicates == 1  # the second copy is linked, not scored

    links = db.conn.execute(
        "SELECT canonical_job_id, duplicate_job_id, reason FROM job_duplicates"
    ).fetchall()
    assert len(links) == 1

    canonical = db.conn.execute(
        "SELECT source_id, source_job_id FROM jobs WHERE id = ?", (links[0]["canonical_job_id"],)
    ).fetchone()
    duplicate = db.conn.execute(
        "SELECT source_id, source_job_id FROM jobs WHERE id = ?", (links[0]["duplicate_job_id"],)
    ).fetchone()

    # Read first wins the canonical slot; neither row is deleted.
    assert canonical["source_id"] == "france_travail"
    assert duplicate["source_id"] == "jooble"
    assert db.conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"] == 2


def test_cross_source_duplicate_is_only_linked_in_one_direction(db):
    """Reversing the source order reverses which row is canonical — nothing is lost."""
    ft, jooble = _ft_and_jooble_same_job()

    run_jobs(
        [NamedSource("jooble", [jooble]), NamedSource("france_travail", [ft])],
        _profile(), _settings(), db, {},
    )

    row = db.conn.execute(
        "SELECT j.source_id AS canonical, d.source_id AS duplicate"
        " FROM job_duplicates l"
        " JOIN jobs j ON j.id = l.canonical_job_id"
        " JOIN jobs d ON d.id = l.duplicate_job_id"
    ).fetchone()
    assert row["canonical"] == "jooble"
    assert row["duplicate"] == "france_travail"


def test_distinct_jobs_from_two_sources_are_both_kept(db):
    a = _job("FT-1", company="Acme Corp", title="Ingénieur DevOps")
    b = _job(
        "JB-1",
        source="jooble",
        company="Globex",
        title="Administrateur Systèmes Linux",
        description="Administration Linux, supervision et scripts Python.",
        url="https://jooble.org/jdp/1",
    )
    summary = run_jobs(
        [NamedSource("france_travail", [a]), NamedSource("jooble", [b])],
        _profile(), _settings(), db, {},
    )
    assert summary.eligible == 2
    assert summary.duplicates == 0


def test_by_source_reports_fetched_eligible_duplicates_and_calls(db):
    ft, jooble = _ft_and_jooble_same_job()
    other = _job("FT-2", company="Globex", url="https://example.com/jobs/2")

    summary = run_jobs(
        [
            NamedSource("france_travail", [ft, other], calls=98),
            NamedSource("jooble", [jooble], calls=7),
        ],
        _profile(), _settings(), db, {},
    )

    assert summary.by_source == {
        "france_travail": {"fetched": 2, "eligible": 2, "duplicates": 0, "calls": 98},
        "jooble": {"fetched": 1, "eligible": 0, "duplicates": 1, "calls": 7},
    }
    assert summary.api_calls == 105  # summed across sources


def test_a_failing_source_does_not_stop_the_others(db):
    class DeadSource(NamedSource):
        def fetch(self, since):
            raise RuntimeError("API down")

    summary = run_jobs(
        [DeadSource("jooble", []), NamedSource("france_travail", [_job("FT-1")])],
        _profile(), _settings(), db, {},
    )

    assert summary.errors == 1
    assert summary.eligible == 1
    assert summary.by_source["france_travail"]["fetched"] == 1
    assert summary.by_source["jooble"]["fetched"] == 0


def test_query_stats_are_merged_across_sources(db):
    ft = StatSource([_job("FT-1")], [QueryStat("devops", "75", 1, 10, "france_travail")])
    ft.name = "france_travail"
    jb = StatSource(
        [_job("JB-1", source="jooble", company="Globex", url="https://jooble.org/1")],
        [QueryStat("devops", "Île-de-France", 1, 50, "jooble")],
    )
    jb.name = "jooble"

    summary = run_jobs([ft, jb], _profile(), _settings(), db, {})

    assert summary.queries == 2
    assert summary.by_area == {"75": 1, "Île-de-France": 1}
    assert summary.by_keyword == {"devops": 2}


def test_a_single_source_still_works_unwrapped(db):
    """The common case stays a bare source, not a one-item list."""
    summary = run_jobs(FakeSource([_job("FT-1")]), _profile(), _settings(), db, {})
    assert summary.eligible == 1


# ---------------------------------------------------------------------------
# by_department: where the offers are, not where we searched
# ---------------------------------------------------------------------------

def test_by_department_counts_offers_by_their_own_location(db):
    jobs = [
        _job("FT-1", location="92 - Nanterre"),
        _job("FT-2", location="92 - Courbevoie", url="https://example.com/jobs/2"),
        _job("FT-3", location="31 - Toulouse", url="https://example.com/jobs/3"),
        _job("FT-4", location="Lyon", url="https://example.com/jobs/4"),
    ]
    summary = run_jobs(FakeSource(jobs), _profile(), _settings(), db, {}, dry_run=True)

    assert summary.by_department == {"92": 2, "31": 1, "69": 1}


def test_by_department_marks_unresolvable_locations(db):
    """A region, a country or a town nobody listed has no single department."""
    jobs = [
        _job("FT-1", location="Bretagne"),
        _job("FT-2", location="France", url="https://example.com/jobs/2"),
        _job("FT-3", location="", url="https://example.com/jobs/3"),
        _job("FT-4", location="75 - Paris", url="https://example.com/jobs/4"),
    ]
    summary = run_jobs(FakeSource(jobs), _profile(), _settings(), db, {}, dry_run=True)

    assert summary.by_department == {"?": 3, "75": 1}


def test_by_department_counts_rejected_offers_too(db):
    """It answers "where are the offers", not "where are the matches"."""
    jobs = [
        _job("FT-1", location="92 - Nanterre", contract_type=ContractType.ALTERNANCE),
        _job("FT-2", location="99 - BELGIQUE", url="https://example.com/jobs/2"),
    ]
    summary = run_jobs(FakeSource(jobs), _profile(), _settings(), db, {}, dry_run=True)

    assert summary.eligible == 0
    assert summary.by_department == {"92": 1, "99": 1}


# ---------------------------------------------------------------------------
# Experience stretch tier
# ---------------------------------------------------------------------------

def _stretch_settings(years: float = 1) -> Settings:
    s = _settings()
    s.experience = ExperienceConfig(stretch_years=years)
    return s


class _Src:
    name = "france_travail"

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs

    def fetch(self, since):
        return iter(self._jobs)

    def to_job(self, raw: Job) -> Job:
        return raw


def test_a_stretch_job_is_stored_as_stretch_and_counted_apart():
    """Candidate has 3 years; the job asks 4 (in the band) and scores like any eligible job."""
    jobs = [
        _job("FT-STRETCH", company="Acme", title="DevOps Engineer",
             description="Kubernetes. 4 ans d'expérience minimum."),
        _job("FT-OK", company="Beta", title="SRE",
             description="Kubernetes. 2 ans d'expérience."),
        _job("FT-NO", company="Gamma", title="Platform Engineer",
             description="Kubernetes. 5 ans d'expérience minimum."),
    ]
    with Database(migrations_dir=MIGRATIONS) as db:
        summary = run_jobs(_Src(jobs), _profile(3.0), _stretch_settings(1), db, {})
        rows = {
            r["source_job_id"]: (r["eligibility"], r["score"], r["rejection_reason"])
            for r in db.conn.execute(
                "SELECT source_job_id, eligibility, score, rejection_reason FROM jobs"
            )
        }

    assert summary.stretch == 1
    assert summary.eligible == 1
    assert summary.strong == 1  # FT-OK only: a stretch job is never strong
    assert summary.rejected_by_reason == {"EXPERIENCE": 1}
    assert rows["FT-STRETCH"][0] == str(Eligibility.STRETCH)
    assert rows["FT-STRETCH"][1] == rows["FT-OK"][1]  # same scorer, same text
    assert rows["FT-STRETCH"][2] is None
    assert rows["FT-NO"][0] == "REJECTED"


def test_the_stretch_tier_is_off_by_default():
    jobs = [_job("FT-STRETCH", description="Kubernetes. 4 ans d'expérience minimum.")]
    with Database(migrations_dir=MIGRATIONS) as db:
        summary = run_jobs(_Src(jobs), _profile(3.0), _settings(), db, {})
    assert summary.stretch == 0
    assert summary.rejected_by_reason == {"EXPERIENCE": 1}


def test_a_stretch_job_carries_its_note_in_the_breakdown():
    jobs = [_job("FT-STRETCH", description="Kubernetes. 4 ans d'expérience minimum.")]
    with Database(migrations_dir=MIGRATIONS) as db:
        run_jobs(_Src(jobs), _profile(3.0), _stretch_settings(1), db, {})
        raw = db.conn.execute("SELECT scoring_breakdown FROM jobs").fetchone()[0]
    assert "stretch: requires 4y, you have 3" in json.loads(raw)["explanations"]
