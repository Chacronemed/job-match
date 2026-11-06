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


# ---------------------------------------------------------------- outage alerts (ADR 0027)

def _down(source="france_travail", boards=()):
    return {"source": source, "label": source, "kind": "no_results", "reason": "0 offre",
            "boards": list(boards)}


def _run_at(at: datetime, by_source: dict, outages=(), run_id=1) -> RunRecord:
    return RunRecord(id=run_id, pipeline="jobs", started_at=at, finished_at=at,
                     summary={"by_source": by_source, "outages": list(outages)})


def test_outage_alerts_fire_once_a_day_per_source():
    from job_match.ops.summary import outage_alert_text, outage_alerts

    first = _run_at(NOW, {"france_travail": {"fetched": 0}}, [_down()], run_id=2)
    yesterday = _run_at(NOW - timedelta(days=1), {"france_travail": {"fetched": 0}}, [_down()])
    assert [o.source for o in outage_alerts([first, yesterday])] == ["france_travail"]
    # the same day replayed (a second run): already announced, no second email
    replay = _run_at(NOW + timedelta(hours=2), {"france_travail": {"fetched": 0}}, [_down()], 3)
    assert outage_alerts([replay, first, yesterday]) == []
    # a new source down in the replay is announced; a healthy latest run says nothing
    both = _run_at(NOW + timedelta(hours=2), {}, [_down(), _down("ats")], 3)
    assert [o.source for o in outage_alerts([both, first])] == ["ats"]
    assert outage_alerts([_run_at(NOW, {"france_travail": {"fetched": 50}}), first]) == []
    assert outage_alerts([]) == []
    subject, body = outage_alert_text(outage_alerts([first]), "2026-11-06")
    assert subject == "[job-match] France Travail indisponible — clôtures suspendues (2026-11-06)"
    assert "France Travail indisponible — clôtures suspendues : 0 offre" in body
    assert "job-match ops reopen --since 2026-11-06 --source <source> --apply" in body
    assert "Expirée" in body


def _seed_outage_run(db_path: str) -> None:
    with Database(path=db_path) as db:
        repo = RunRepository(db.conn)
        for i in range(3, 0, -1):
            at = NOW - timedelta(days=i)
            repo.save(RunSummary(pipeline="jobs", fetched=30,
                                 by_source={"france_travail": {"fetched": 30, "calls": 3}}),
                      started_at=at, finished_at=at)
        repo.save(RunSummary(pipeline="jobs", fetched=0, suspended=12, outages=[_down()],
                             by_source={"france_travail": {"fetched": 0, "calls": 14,
                                                           "checked": 0, "closed": 0,
                                                           "suspended": 12}}),
                  started_at=NOW, finished_at=NOW)


def test_check_sources_emails_the_outage_once_and_writes_the_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db_path = str(tmp_path / "data" / "jobs.sqlite")
    _seed_outage_run(db_path)
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    notifier = MagicMock()
    notifier.send_text.return_value = True
    with patch("job_match.notification.email_notifier.EmailNotifier") as cls:
        cls.from_env.return_value = notifier
        _cmd_check_sources(argparse.Namespace(days=3))
    assert notifier.send_text.call_count == 1  # one day at 0 is not "silent for 3 runs"
    subject = notifier.send_text.call_args.args[0]
    assert subject.startswith("[job-match] France Travail indisponible — clôtures suspendues (")
    summary = target.read_text(encoding="utf-8")
    assert "## ⚠️ Source indisponible" in summary
    assert "- France Travail indisponible — clôtures suspendues : 0 offre" in summary
    assert "::warning title=Source down::" in capsys.readouterr().out

    # the same day again (a replay of the daily run): no second email
    with Database(path=db_path) as db:
        later = NOW + timedelta(hours=1)
        RunRepository(db.conn).save(
            RunSummary(pipeline="jobs", outages=[_down()],
                       by_source={"france_travail": {"fetched": 0}}), later, later)
    notifier.reset_mock()
    with patch("job_match.notification.email_notifier.EmailNotifier") as cls:
        cls.from_env.return_value = notifier
        _cmd_check_sources(argparse.Namespace(days=3))
    assert not notifier.send_text.called
    assert "none down on the last run" in capsys.readouterr().out


def test_digest_markdown_names_the_source_down_instead_of_zero_jobs():
    md = digest_markdown(jobs=0, strong=0, leads=0, followups=0, sent=False,
                         outages=("France Travail",))
    assert "⚠️ **France Travail indisponible aujourd'hui** : clôtures suspendues" in md
    assert "outages" not in digest_markdown(jobs=0, strong=0, leads=0, followups=0, sent=False)


def test_reopen_command_prints_and_writes_counts_only_to_the_summary(tmp_path, monkeypatch, capsys):
    """`job-match ops reopen` (ADR 0027): the report goes to stdout and the job summary; run
    ids, counts and reasons only, never a title; dry run unless --apply."""
    import shutil

    from job_match.cli import _cmd_reopen
    from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
    from job_match.persistence.repositories import JobRepository

    monkeypatch.chdir(tmp_path)
    shutil.copytree(Path(__file__).resolve().parents[2] / "config", tmp_path / "config")
    (tmp_path / "data").mkdir()
    start = NOW - timedelta(days=1)
    with Database(path=str(tmp_path / "data" / "jobs.sqlite")) as db:
        RunRepository(db.conn).save(
            RunSummary(pipeline="jobs", outages=[_down()],
                       by_source={"france_travail": {"fetched": 0}}),
            start, start + timedelta(minutes=10))
        job = JobRepository(db.conn).save(Job(
            source="france_travail", source_job_id="SECRET-TITLE-1", title="Secret title",
            company="Acme", location="Paris", workplace_type=WorkplaceType.UNKNOWN,
            contract_type=ContractType.CDI, description="x", url="https://x.test/1",
            collected_at=NOW, eligibility=Eligibility.ELIGIBLE, score=70))
        JobRepository(db.conn).mark_closed([job.id], start + timedelta(minutes=5))
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    args = argparse.Namespace(since=(NOW - timedelta(days=2)).date().isoformat(),
                              source="france_travail", dry_run=True, apply=False)
    _cmd_reopen(args)
    out = capsys.readouterr().out
    summary = target.read_text(encoding="utf-8")
    assert "[DRY RUN]" in out and "1 offer(s) would be reopened (add --apply)" in out
    assert "## Reopen" in summary and "1 offer(s) would be reopened" in summary
    for leak in ("Secret title", "SECRET-TITLE-1"):
        assert leak not in out and leak not in summary
    with Database(path=str(tmp_path / "data" / "jobs.sqlite")) as db:
        assert db.conn.execute("SELECT closed_at FROM jobs").fetchone()[0] is not None
    _cmd_reopen(argparse.Namespace(**{**vars(args), "apply": True}))
    assert "1 offer(s) reopened" in capsys.readouterr().out
    with Database(path=str(tmp_path / "data" / "jobs.sqlite")) as db:
        assert db.conn.execute("SELECT closed_at FROM jobs").fetchone()[0] is None
