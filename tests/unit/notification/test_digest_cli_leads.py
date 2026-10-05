"""M12: `job-match digest` sends leads and marks them only after a successful send."""
import argparse
from unittest.mock import MagicMock, patch

import pytest

from job_match.persistence.db import Database
from job_match.persistence.repositories import LeadRepository

from ._seed import NOW, funding, job

_NOTIFIER = "job_match.notification.email_notifier.EmailNotifier"


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text("strong_threshold: 70\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JOB_MATCH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("JOB_MATCH_DATA_DIR", raising=False)
    return tmp_path


def _db_path(tmp_project) -> str:
    return str(tmp_project / "data" / "jobs.sqlite")


def _seed(tmp_project, *, with_job: bool = True) -> int:
    with Database(path=_db_path(tmp_project)) as db:
        _, lead = funding(db.conn, "inbolt", "Inbolt", priority="high", hiring="recruter")
        if with_job:
            job(db.conn, "J1", "Inbolt")
    return lead.id


def _notified_lead_ids(tmp_project) -> list[int]:
    with Database(path=_db_path(tmp_project)) as db:
        rows = db.conn.execute("SELECT id FROM leads WHERE notified_at IS NOT NULL").fetchall()
    return [r[0] for r in rows]


def _run_digest(send_ok: bool, resend_since=None) -> MagicMock:
    from job_match.cli import _cmd_digest

    notifier = MagicMock()
    notifier.send.return_value = send_ok
    with patch(_NOTIFIER) as cls:
        cls.from_env.return_value = notifier
        _cmd_digest(argparse.Namespace(dry_run=False, resend_since=resend_since))
    return notifier


def test_successful_send_marks_leads(tmp_project):
    lead_id = _seed(tmp_project)
    notifier = _run_digest(send_ok=True)

    sent = notifier.send.call_args.args[0]
    assert [lead.company for lead in sent.leads] == ["Inbolt"]
    assert _notified_lead_ids(tmp_project) == [lead_id]


def test_failed_send_marks_no_leads(tmp_project):
    _seed(tmp_project)
    with pytest.raises(SystemExit) as exc:
        _run_digest(send_ok=False)
    assert exc.value.code == 1
    assert _notified_lead_ids(tmp_project) == []


def test_leads_only_digest_is_still_sent(tmp_project):
    lead_id = _seed(tmp_project, with_job=False)
    notifier = _run_digest(send_ok=True)
    notifier.send.assert_called_once()
    assert _notified_lead_ids(tmp_project) == [lead_id]


def test_nothing_to_send(tmp_project, capsys):
    from job_match.cli import _cmd_digest

    with patch(_NOTIFIER) as cls:
        _cmd_digest(argparse.Namespace(dry_run=False, resend_since=None))
        cls.from_env.assert_not_called()
    assert "No new jobs or leads to send." in capsys.readouterr().out


def test_resend_since_also_resets_leads(tmp_project):
    lead_id = _seed(tmp_project)
    with Database(path=_db_path(tmp_project)) as db:
        LeadRepository(db.conn).mark_notified([lead_id], NOW)

    notifier = _run_digest(send_ok=True, resend_since=NOW.date().isoformat())

    assert len(notifier.send.call_args.args[0].leads) == 1
    assert _notified_lead_ids(tmp_project) == [lead_id]


def test_dry_run_preview_contains_leads_and_marks_nothing(tmp_project):
    from job_match.cli import _cmd_digest

    _seed(tmp_project)
    _cmd_digest(argparse.Namespace(dry_run=True, resend_since=None))

    preview = (tmp_project / "data" / "digest_preview.html").read_text(encoding="utf-8")
    assert "Funding Leads (1)" in preview
    assert _notified_lead_ids(tmp_project) == []
