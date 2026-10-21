"""The digest reads the tracking mirror: handled jobs are left out, due follow-ups are listed."""
import argparse
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from job_match.config.schema import Settings
from job_match.notification.assemble import build_digest
from job_match.notification.digest import render_html, render_text
from job_match.persistence.db import Database
from job_match.persistence.repositories import ApplicationRepository, JobRepository
from job_match.tracking.constants import STATUSES

TODAY = date(2026, 10, 20)


def _mirror(conn, rows, *, application):
    ApplicationRepository(conn).replace_all([application(*r[:2], **r[2]) for r in rows], [])


@pytest.fixture
def now():
    return datetime(2026, 10, 20, 7, 0, tzinfo=UTC)


@pytest.mark.parametrize("status", STATUSES)
def test_list_unnotified_leaves_out_handled_jobs_only(status, save_job, rows, now):
    with Database(path=":memory:") as db:
        tracked = save_job(db.conn, "T1")
        untracked = save_job(db.conn, "U1")
        _mirror(db.conn, [("france_travail:T1", status, {})], application=rows.application)
        listed = {j.id for j in JobRepository(db.conn).list_unnotified(now=now, max_age_days=45)}
    assert untracked.id in listed
    assert (tracked.id in listed) == (status in ("to_review", "to_apply"))


def test_the_same_id_at_another_source_is_not_excluded(save_job, rows, now):
    with Database(path=":memory:") as db:
        job = save_job(db.conn, "T1")
        _mirror(db.conn, [("adzuna:T1", "ignored", {})], application=rows.application)
        listed = JobRepository(db.conn).list_unnotified(now=now, max_age_days=45)
    assert [j.id for j in listed] == [job.id]


def test_followups_due_today_or_overdue_oldest_first(save_job, rows):
    with Database(path=":memory:") as db:
        save_job(db.conn, "A", title="Platform engineer")
        _mirror(db.conn, [
            ("france_travail:A", "applied", {"follow_up_at": "2026-10-20"}),
            ("france_travail:GONE", "interview", {"follow_up_at": "2026-10-15"}),
            ("france_travail:B", "applied", {"follow_up_at": "2026-10-21"}),   # future
            ("france_travail:C", "rejected", {"follow_up_at": "2026-10-10"}),  # closed
            ("france_travail:D", "ignored", {"follow_up_at": "2026-10-10"}),   # closed
            ("france_travail:E", "to_apply", {"follow_up_at": "2026-10-19"}),
            ("france_travail:F", "applied", {}),                               # no date
        ], application=rows.application)
        due = ApplicationRepository(db.conn).list_followups_due(TODAY)
    assert [f.job_key for f in due] == [
        "france_travail:GONE", "france_travail:E", "france_travail:A"
    ]
    assert due[2].title == "Platform engineer" and due[2].url == "https://ft.example/A"
    assert due[0].title is None  # the offer left the DB; the key is still listed


def test_digest_lists_followups_first_without_the_note(save_job, rows, now):
    with Database(path=":memory:") as db:
        save_job(db.conn, "A", title="Platform <b>engineer</b>")
        save_job(db.conn, "N", score=90)
        _mirror(db.conn, [
            ("france_travail:A", "applied",
             {"follow_up_at": "2026-10-17", "note": rows.note, "cv_url": rows.url}),
        ], application=rows.application)
        batch = build_digest(db, Settings(), now)
    data = batch.data
    assert [f.job_key for f in data.followups] == ["france_travail:A"]
    # the applied job is handled: it is not in the job sections, so never marked by this send
    assert all(j.source_job_id != "A" for j in data.strong + data.eligible + data.stretch)
    html, text = render_html(data), render_text(data)
    for out in (html, text):
        assert "Relances du jour (1)" in out
        assert "3 j de retard" in out
        assert "private-marker" not in out and "private-cv-marker" not in out
    assert html.index("Relances du jour") < html.index("Strong Matches")
    assert "Platform &lt;b&gt;engineer&lt;/b&gt;" in html
    assert "1 follow-up" in text


def test_followups_alone_are_sent_and_never_marked(tmp_path, monkeypatch, save_job, rows):
    from job_match.cli import _cmd_digest

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text("strong_threshold: 70\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("JOB_MATCH_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(data_dir))
    db_path = str(data_dir / "jobs.sqlite")
    with Database(path=db_path) as db:
        save_job(db.conn, "A")
        _mirror(db.conn, [("france_travail:A", "applied", {"follow_up_at": "2000-01-01"})],
                application=rows.application)

    notifier = MagicMock()
    notifier.send.return_value = True
    with patch("job_match.notification.email_notifier.EmailNotifier") as cls:
        cls.from_env.return_value = notifier
        _cmd_digest(argparse.Namespace(dry_run=False, resend_since=None))
        _cmd_digest(argparse.Namespace(dry_run=False, resend_since=None))

    assert notifier.send.call_count == 2  # due again the next day: never marked
    sent = notifier.send.call_args.args[0]
    assert [f.job_key for f in sent.followups] == ["france_travail:A"]
    assert not sent.strong and not sent.eligible
    with Database(path=db_path) as db:
        assert db.conn.execute("SELECT COUNT(*) FROM jobs WHERE notified_at IS NOT NULL")\
            .fetchone()[0] == 0


def test_subject_counts_followups():
    from job_match.domain.models import FollowUp
    from job_match.notification.digest import DigestData
    from job_match.notification.email_notifier import EmailNotifier

    notifier = EmailNotifier(host="h", port=465, user="u", password="p", recipient="r")
    data = DigestData(strong=(), eligible=(), followups=(
        FollowUp(job_key="adzuna:1", status="applied", follow_up_at=TODAY),
    ))
    with patch("smtplib.SMTP_SSL") as smtp:
        assert notifier.send(data)
    sent = smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
    assert b"1 relance" in sent
