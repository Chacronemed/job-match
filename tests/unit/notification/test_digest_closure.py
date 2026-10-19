"""M20: closed and stale jobs never reach the digest, and stay unnotified."""
from datetime import timedelta
from pathlib import Path

import pytest

from job_match.config.schema import JobsConfig, Settings
from job_match.notification.assemble import build_digest
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository

from ._seed import NOW, job

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _settings(max_age_days: int = 45) -> Settings:
    return Settings(strong_threshold=70, jobs=JobsConfig(max_age_days=max_age_days))


def test_closed_jobs_are_left_out_of_the_digest_and_stay_unnotified(db):
    kept = job(db.conn, "K", "Acme", score=80)
    gone = job(db.conn, "G", "Acme", score=90)
    JobRepository(db.conn).mark_closed([gone.id], NOW)

    batch = build_digest(db, _settings(), NOW)

    assert batch.job_ids == (kept.id,)
    assert [j.source_job_id for j in batch.data.strong] == ["K"]
    assert batch.jobs_below_min_score == 0  # a closed job is not "below min score"


def test_jobs_older_than_max_age_days_are_left_out(db):
    kept = job(db.conn, "K", "Acme", score=80)
    stale_posting = job(db.conn, "SP", "Acme", score=85)
    db.conn.execute(
        "UPDATE jobs SET published_at = ? WHERE id = ?",
        ((NOW - timedelta(days=46)).isoformat(), stale_posting.id),
    )
    db.conn.commit()
    job(db.conn, "SC", "Acme", score=85, collected_at=NOW - timedelta(days=46))  # no date

    batch = build_digest(db, _settings(), NOW)
    assert batch.job_ids == (kept.id,)

    # the setting is the lever
    assert len(build_digest(db, _settings(max_age_days=60), NOW).job_ids) == 3
