"""CLI-level tests for `job-match digest`.

Tests that the digest command:
- Exits 1 and does NOT mark jobs when SMTP config is missing.
- Does NOT mark jobs when send() returns False.
- Marks jobs only after a successful send.
- --resend-since resets notified_at and allows a re-send.
"""
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"

_NOW = datetime(2026, 10, 3, 8, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eligible_job(sid: str, score: int = 75) -> Job:
    return Job(
        source="france_travail",
        source_job_id=sid,
        title="DevOps Engineer",
        company="Acme",
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="A job.",
        url=f"https://example.com/{sid}",
        collected_at=_NOW,
        eligibility=Eligibility.ELIGIBLE,
        score=score,
    )


@pytest.fixture
def tmp_project(tmp_path):
    """Minimal project layout: config/settings.yaml + data/ directory."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        "strong_threshold: 70\nbase_score: 50\ntitle_bonus: 0\n"
        "dedup_window_days: 30\nfuzzy_title_threshold: 0.85\n"
        "fuzzy_desc_threshold: 0.80\n",
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    return tmp_path


def _seed_db(db_path: str) -> list[int]:
    """Insert two eligible jobs; return their IDs."""
    with Database(path=db_path) as db:
        repo = JobRepository(db.conn)
        j1 = repo.save(_eligible_job("FT-001", score=80))
        j2 = repo.save(_eligible_job("FT-002", score=65))
    return [j1.id, j2.id]


def _notified_ids(db_path: str) -> list[int]:
    with Database(path=db_path) as db:
        rows = db.conn.execute(
            "SELECT id FROM jobs WHERE notified_at IS NOT NULL"
        ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# send failure → no jobs marked
# ---------------------------------------------------------------------------

def test_send_failure_does_not_mark_jobs(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    db_path = str(tmp_project / "data" / "jobs.sqlite")
    _seed_db(db_path)

    fake_notifier = MagicMock()
    fake_notifier.send.return_value = False

    _NOTIFIER = "job_match.notification.email_notifier.EmailNotifier"
    with (
        patch(_NOTIFIER) as mock_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        mock_cls.from_env.return_value = fake_notifier
        import argparse

        from job_match.cli import _cmd_digest
        args = argparse.Namespace(dry_run=False, resend_since=None)
        _cmd_digest(args)

    assert exc_info.value.code == 1
    assert _notified_ids(db_path) == []


# ---------------------------------------------------------------------------
# missing SMTP config → exit 1, no marking
# ---------------------------------------------------------------------------

def test_missing_smtp_config_exits_1(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    db_path = str(tmp_project / "data" / "jobs.sqlite")
    _seed_db(db_path)

    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO"):
        monkeypatch.delenv(k, raising=False)

    import argparse

    from job_match.cli import _cmd_digest
    args = argparse.Namespace(dry_run=False, resend_since=None)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_digest(args)

    assert exc_info.value.code == 1
    assert _notified_ids(db_path) == []


# ---------------------------------------------------------------------------
# successful send → jobs are marked
# ---------------------------------------------------------------------------

def test_successful_send_marks_jobs(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    db_path = str(tmp_project / "data" / "jobs.sqlite")
    ids = _seed_db(db_path)

    fake_notifier = MagicMock()
    fake_notifier.send.return_value = True

    _NOTIFIER = "job_match.notification.email_notifier.EmailNotifier"
    with patch(_NOTIFIER) as mock_cls:
        mock_cls.from_env.return_value = fake_notifier
        import argparse

        from job_match.cli import _cmd_digest
        args = argparse.Namespace(dry_run=False, resend_since=None)
        _cmd_digest(args)

    assert sorted(_notified_ids(db_path)) == sorted(ids)


# ---------------------------------------------------------------------------
# --resend-since resets and re-sends
# ---------------------------------------------------------------------------

def test_resend_since_resets_notified_at(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    db_path = str(tmp_project / "data" / "jobs.sqlite")
    ids = _seed_db(db_path)

    # Mark both jobs as already notified on Oct 2
    with Database(path=db_path) as db:
        JobRepository(db.conn).mark_notified(ids, datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC))

    assert sorted(_notified_ids(db_path)) == sorted(ids)

    fake_notifier = MagicMock()
    fake_notifier.send.return_value = True

    _NOTIFIER = "job_match.notification.email_notifier.EmailNotifier"
    with patch(_NOTIFIER) as mock_cls:
        mock_cls.from_env.return_value = fake_notifier
        import argparse

        from job_match.cli import _cmd_digest
        args = argparse.Namespace(dry_run=False, resend_since="2026-10-02")
        _cmd_digest(args)

    # After resend, both are notified again (with a new timestamp)
    assert sorted(_notified_ids(db_path)) == sorted(ids)
    fake_notifier.send.assert_called_once()


def test_resend_since_invalid_date_exits_1(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)

    import argparse

    from job_match.cli import _cmd_digest
    args = argparse.Namespace(dry_run=False, resend_since="not-a-date")

    with pytest.raises(SystemExit) as exc_info:
        _cmd_digest(args)

    assert exc_info.value.code == 1
