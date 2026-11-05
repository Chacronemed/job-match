"""Ops (item 4 of the 2026-11-04 pass): the job summary, the loud failure and the alert when
a source returns nothing three runs in a row."""
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_match.cli import _cmd_check_sources, _fail_loudly
from job_match.domain.models import RunRecord, RunSummary
from job_match.ops.summary import (
    alert_text,
    append_step_summary,
    digest_markdown,
    failure_markdown,
    jobs_markdown,
    silent_sources,
)
from job_match.persistence.db import Database
from job_match.persistence.repositories import RunRepository

NOW = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)


def _run(i: int, by_source: dict, pipeline: str = "jobs") -> RunRecord:
    at = NOW - timedelta(days=i)
    return RunRecord(id=100 - i, pipeline=pipeline, started_at=at, finished_at=at,
                     summary={"fetched": sum(c.get("fetched", 0) for c in by_source.values()),
                              "by_source": by_source})


def test_a_source_silent_in_each_of_the_last_three_runs_is_reported():
    runs = [_run(i, {"france_travail": {"fetched": 0, "calls": 3}, "ats": {"fetched": 40}})
            for i in range(3)]
    assert silent_sources(runs) == ["france_travail"]


def test_two_runs_or_one_day_with_results_or_a_day_without_the_source_is_not_an_alert():
    silent = {"france_travail": {"fetched": 0}}
    assert silent_sources([_run(0, silent), _run(1, silent)]) == []
    assert silent_sources([_run(0, silent), _run(1, {"france_travail": {"fetched": 7}}),
                           _run(2, silent)]) == []
    # not enabled on one day (no key): it did not run, so it is not silent
    other = {"ats": {"fetched": 3}}
    assert silent_sources([_run(0, silent), _run(1, other), _run(2, silent)]) == []
    # funding runs between the jobs runs are ignored
    runs = [_run(0, silent), _run(0, {}, "funding"), _run(1, silent), _run(2, silent)]
    assert silent_sources(runs) == ["france_travail"]


def test_the_alert_names_the_sources_and_the_days():
    subject, body = alert_text(["ats", "jooble"], 3)
    assert subject == "[job-match] ats, jooble: 0 results for 3 days"
    assert "last 3 runs" in body and "config/settings.yaml" in body


def test_step_summary_is_appended_only_inside_actions(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert append_step_summary("## x") is False
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert append_step_summary("## first") and append_step_summary("## second\n")
    assert target.read_text(encoding="utf-8") == "## first\n\n## second\n\n"


def test_jobs_markdown_has_sources_gates_scored_and_time():
    summary = RunSummary(
        pipeline="jobs", fetched=120, queries=7, api_calls=37, rejected_jobs=90,
        rejected_by_reason={"EXPERIENCE": 40, "LOCATION": 55}, duplicates=5, eligible=20,
        strong=6, stretch=5, checked=30, closed=2, errors=1,
        by_source={"france_travail": {"fetched": 120, "eligible": 20, "duplicates": 5, "calls": 7},
                   "ats": {"fetched": 0, "eligible": 0, "duplicates": 0, "calls": 30}},
    )
    md = jobs_markdown(summary, 83.4)
    assert "**120 fetched** in 83 s · 7 queries · 37 API calls · ⚠️ 1 error(s)" in md
    assert "| france_travail | 120 | 20 | 5 | 7 |" in md
    assert "| ats ⚠️ 0 | 0 | 0 | 0 | 30 |" in md
    assert "| EXPERIENCE | 40 |" in md and "| **total rejected jobs** | **90** |" in md
    assert "**Scored: 25** (20 eligible of which 6 strong, 5 stretch)" in md
    assert digest_markdown(jobs=4, strong=1, leads=2, followups=0, sent=True).startswith(
        "## Digest\n\n**Emailed**: 4 jobs (1 strong), 2 leads")


def test_a_failure_is_announced_in_the_summary_and_as_an_annotation(
    tmp_path, monkeypatch, capsys
):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    _fail_loudly("Jobs run", RuntimeError("France Travail token refused"))
    assert "## ❌ Jobs run failed" in target.read_text(encoding="utf-8")
    assert "RuntimeError: France Travail token refused" in target.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "::error title=Jobs run failed::RuntimeError: France Travail token refused" in out
    assert failure_markdown("x", ValueError("y")) == "## ❌ x failed\n\n`ValueError: y`"


def _seed_runs(db_path: str, fetched: list[int]) -> None:
    with Database(path=db_path) as db:
        repo = RunRepository(db.conn)
        for i, n in enumerate(fetched):
            at = NOW - timedelta(days=len(fetched) - i)
            repo.save(RunSummary(pipeline="jobs", fetched=n,
                                 by_source={"france_travail": {"fetched": n, "calls": 3}}),
                      started_at=at, finished_at=at)


def test_check_sources_emails_the_alert_and_writes_the_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _seed_runs(str(tmp_path / "data" / "jobs.sqlite"), [12, 0, 0, 0])
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    notifier = MagicMock()
    notifier.send_text.return_value = True
    with patch("job_match.notification.email_notifier.EmailNotifier") as cls:
        cls.from_env.return_value = notifier
        _cmd_check_sources(argparse.Namespace(days=3))
    subject = notifier.send_text.call_args.args[0]
    assert subject == "[job-match] france_travail: 0 results for 3 days"
    assert "## ⚠️ Silent source" in target.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "::warning title=Silent source::" in out and "alert emailed." in out


def test_check_sources_is_quiet_when_a_source_answered_and_never_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _seed_runs(str(tmp_path / "data" / "jobs.sqlite"), [0, 0, 5])
    with patch("job_match.notification.email_notifier.EmailNotifier") as cls:
        _cmd_check_sources(argparse.Namespace(days=3))
        assert not cls.from_env.called
    assert "none silent for 3 runs" in capsys.readouterr().out
    # without SMTP the alert is printed, not emailed, and the command still exits 0
    (tmp_path / "silent").mkdir()
    monkeypatch.chdir(tmp_path / "silent")
    (tmp_path / "silent" / "data").mkdir()
    _seed_runs(str(tmp_path / "silent" / "data" / "jobs.sqlite"), [0, 0, 0])
    for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO"):
        monkeypatch.delenv(var, raising=False)
    _cmd_check_sources(argparse.Namespace(days=3))
    assert "SMTP not configured" in capsys.readouterr().err


def test_check_sources_without_a_database_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _cmd_check_sources(argparse.Namespace(days=3))
    assert "nothing to check" in capsys.readouterr().out
    assert not Path("data").exists()
