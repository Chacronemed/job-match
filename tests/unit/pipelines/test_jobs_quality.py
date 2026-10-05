"""Jobs pipeline: relevance gate rejection is stored; source query is stored and DEBUG-logged."""
import logging
from datetime import UTC, datetime
from pathlib import Path

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    RelevanceConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository
from job_match.pipelines.jobs import run_jobs

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 5, 8, 0, 0, tzinfo=UTC)


class FakeSource:
    name = "france_travail"

    def __init__(self, jobs):
        self._jobs = jobs

    def fetch(self, since):
        return iter(self._jobs)

    def to_job(self, raw):
        return raw


def _job(sid: str, title: str, description: str, query: str) -> Job:
    return Job(
        source="france_travail", source_job_id=sid, title=title, company="Acme",
        location="Paris", workplace_type=WorkplaceType.HYBRID, contract_type=ContractType.CDI,
        description=description, url=f"https://ft.test/{sid}", collected_at=_NOW,
        search_query=query,
    )


def _profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=3),
        skills=Skills(preferred=[SkillWeight("kubernetes", 25)]),
        filters=Filters(contract_types=[ContractType.CDI]),
        ft_search=FTSearch(keywords=["devops"]),
    )


def _settings() -> Settings:
    return Settings(title_bonus=0, relevance=RelevanceConfig(target_title_keywords=["devops"]))


def test_irrelevant_job_is_rejected_and_stored_with_its_query(caplog):
    jobs = [
        _job("1", "Réceptionniste en hôtellerie (H/F)", "Accueil clients.", "production"),
        _job("2", "Ingénieur DevOps", "Kubernetes au quotidien.", "devops"),
    ]
    with Database(migrations_dir=MIGRATIONS) as db:
        with caplog.at_level(logging.DEBUG, logger="job_match.pipelines.jobs"):
            summary = run_jobs(FakeSource(jobs), _profile(), _settings(), db, {})
        rows = {r["source_job_id"]: r for r in db.conn.execute("SELECT * FROM jobs")}
        stored = JobRepository(db.conn).get(rows["2"]["id"])

    assert summary.rejected_by_reason == {"NOT_RELEVANT": 1}
    assert summary.eligible == 1
    assert rows["1"]["eligibility"] == str(Eligibility.REJECTED)
    assert rows["1"]["rejection_reason"] == "NOT_RELEVANT"
    assert rows["1"]["search_query"] == "production"
    assert stored.search_query == "devops"
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("query='production'" in r.getMessage() and "NOT_RELEVANT" in r.getMessage()
               for r in debug)
    assert not any("production" in r.getMessage() for r in caplog.records
                   if r.levelno >= logging.INFO)  # keywords never logged at INFO


def test_upsert_without_query_keeps_previous_query():
    with Database(migrations_dir=MIGRATIONS) as db:
        repo = JobRepository(db.conn)
        repo.save(_job("1", "Ingénieur DevOps", "x", "devops"))
        repo.save(_job("1", "Ingénieur DevOps", "x", None))  # type: ignore[arg-type]
        row = db.conn.execute("SELECT search_query FROM jobs").fetchone()
    assert row["search_query"] == "devops"
