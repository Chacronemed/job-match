"""Candidatures keeps an application whose offer closed or aged out of the job list."""
from datetime import UTC, datetime

from job_match.config.schema import Settings
from job_match.dashboard.data import build_dashboard_data
from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.persistence.repositories import ApplicationRepository, JobRepository

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)


def _job(sid: str, collected: datetime) -> Job:
    return Job(
        source="france_travail", source_job_id=sid, title=f"DevOps {sid}", company="Acme",
        location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI, description="Kubernetes.",
        url=f"https://ft.example/{sid}", collected_at=collected,
        eligibility=Eligibility.ELIGIBLE, score=80,
    )


def _app(sid: str, status: str) -> dict:
    return {"job_key": f"france_travail:{sid}", "status": status, "applied_at": None,
            "follow_up_at": None, "note": None, "cv_url": None,
            "updated_at": "2026-10-20T10:00:00Z"}


def test_tracked_lists_applied_offers_the_job_list_hides():
    with Database(path=":memory:") as db:
        repo = JobRepository(db.conn)
        listed = repo.save(_job("LIVE", NOW))
        closed = repo.save(_job("GONE", NOW))
        old = repo.save(_job("OLD", datetime(2026, 7, 1, tzinfo=UTC)))
        repo.save(_job("IGNORED", datetime(2026, 7, 1, tzinfo=UTC)))
        repo.mark_closed([closed.id], NOW)
        ApplicationRepository(db.conn).replace_all(
            [_app("LIVE", "applied"), _app("GONE", "interview"), _app("OLD", "to_apply"),
             _app("IGNORED", "ignored")], [])
        data = build_dashboard_data(db, Settings(), NOW)
    assert [j["id"] for j in data["jobs"]] == [listed.id]
    assert sorted(j["key"] for j in data["tracked"]) == [
        "france_travail:GONE", "france_travail:OLD"
    ]
    assert old.id in {j["id"] for j in data["tracked"]}
