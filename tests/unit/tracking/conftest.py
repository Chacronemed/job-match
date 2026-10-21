"""Fixtures for the tracking mirror: wrangler-shaped export files and a seeded jobs DB."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
from job_match.persistence.repositories import JobRepository

NOW = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)
SECRET_NOTE = "salary 58k, recruiter Jeanne private-marker"
SECRET_URL = "https://drive.example.com/private-cv-marker.pdf"


def application(key, status="applied", **fields):
    row = {
        "job_key": key, "status": status, "applied_at": None, "follow_up_at": None,
        "note": None, "cv_url": None, "updated_at": "2026-10-19T10:00:00.000Z",
    }
    row.update(fields)
    return row


def decision(id_, key, label="good_fit", score=72):
    return {"id": id_, "job_key": key, "label": label, "score_at_decision": score,
            "created_at": "2026-10-19T10:00:00.000Z"}


@pytest.fixture
def rows():
    """Row builders shaped like D1's, plus private markers that must never be logged."""
    return SimpleNamespace(application=application, decision=decision,
                           note=SECRET_NOTE, url=SECRET_URL)


@pytest.fixture
def export(tmp_path):
    """Write rows as `wrangler d1 execute --json` prints them; returns the path."""
    counter = iter(range(100))

    def _write(rows, *, success=True, raw=None):
        path = tmp_path / f"export{next(counter)}.json"
        doc = raw if raw is not None else [{"results": rows, "success": success, "meta": {}}]
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def save_job():
    """Insert an eligible canonical job; returns it with its id."""

    def _save(conn, sid, *, score=80, title=None, eligibility=Eligibility.ELIGIBLE):
        return JobRepository(conn).save(Job(
            source="france_travail", source_job_id=sid, title=title or f"DevOps {sid}",
            company="Acme", location="75 - Paris", workplace_type=WorkplaceType.HYBRID,
            contract_type=ContractType.CDI, description="Kubernetes.",
            url=f"https://ft.example/{sid}", collected_at=NOW, eligibility=eligibility,
            score=score,
        ))

    return _save
