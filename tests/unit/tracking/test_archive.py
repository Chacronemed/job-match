"""ADR 0028: auto-archive of stale « À candidater » applications, the Python side. The rule
(`tracking/archive.py`), the mirror's reading of it (`list_archived`, follow-ups), the run
summary and the constants the page and the Worker repeat."""
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from job_match.config.loader import load_settings
from job_match.config.schema import ArchiveConfig, Settings
from job_match.dashboard.data import run_entry
from job_match.domain.models import RunRecord, RunSummary
from job_match.ops.summary import jobs_markdown
from job_match.persistence.db import Database
from job_match.persistence.repositories import ApplicationRepository, JobRepository
from job_match.tracking.archive import KEPT, PUBLISHED, archive_state, kept_day
from job_match.tracking.mirror import import_tracking

ROOT = Path(__file__).resolve().parents[3]
TODAY = date(2026, 11, 6)
CFG = ArchiveConfig()  # settings.yaml's values, checked below


def _ago(days: int) -> str:
    return (datetime(2026, 11, 6, 9, 0, tzinfo=UTC) - timedelta(days=days)).isoformat()


def _state(**over):
    base = dict(
        status="to_apply", reactivated_at=None, decision_label="good_fit",
        decision_created_at=_ago(16), updated_at=_ago(16), published_at=None, closed=False,
        today=TODAY, config=CFG,
    )
    return archive_state(**{**base, **over})


def test_kept_more_than_fifteen_days_ago_is_archived_fifteen_or_less_is_not():
    assert _state(decision_created_at=_ago(16)) is not None
    assert _state(decision_created_at=_ago(16)).reason == KEPT
    assert _state(decision_created_at=_ago(16)).days == 16
    assert _state(decision_created_at=_ago(16)).text == "gardée il y a 16 jours"
    assert _state(decision_created_at=_ago(15)) is None
    assert _state(decision_created_at=_ago(14)) is None


def test_published_more_than_twenty_days_ago_archives_even_an_application_kept_yesterday():
    st = _state(decision_created_at=_ago(1), published_at=_ago(21))
    assert st is not None and st.reason == PUBLISHED and st.days == 21
    assert st.text == "publiée il y a 21 jours"
    assert _state(decision_created_at=_ago(1), published_at=_ago(20)) is None
    # the kept rule is reported first when both fire
    assert _state(decision_created_at=_ago(30), published_at=_ago(40)).reason == KEPT


def test_unknown_publication_leaves_the_kept_rule_alone():
    assert _state(decision_created_at=_ago(10), published_at=None) is None
    # no « Garder » decision (kept from the status menu): no kept day, no kept rule
    assert _state(decision_label=None, decision_created_at=None, updated_at=_ago(40)) is None
    assert _state(decision_label="off_topic", decision_created_at=_ago(40)) is None
    assert kept_day(reactivated_at=None, decision_label=None, decision_created_at=None,
                    updated_at=_ago(40)) is None


@pytest.mark.parametrize("status", ["applied", "interview", "rejected", "ignored", "to_review"])
def test_other_statuses_are_never_archived(status):
    assert _state(status=status, decision_created_at=_ago(60), published_at=_ago(60)) is None


def test_reactivation_restarts_the_counter_and_switches_the_published_rule_off():
    assert _state(decision_created_at=_ago(30), published_at=_ago(40),
                  reactivated_at=_ago(3)) is None
    st = _state(decision_created_at=_ago(30), published_at=_ago(40), reactivated_at=_ago(16))
    assert st is not None and st.reason == KEPT and st.days == 16


def test_expired_wins_over_archived():
    assert _state(decision_created_at=_ago(30), closed=True) is None


def test_thresholds_come_from_settings_and_match_the_page_and_the_worker():
    archive = load_settings(ROOT / "config" / "settings.yaml").archive
    assert archive == ArchiveConfig(kept_days=15, published_days=20)
    worker = (ROOT / "worker" / "src" / "archive.js").read_text(encoding="utf-8")
    page = (ROOT / "src" / "job_match" / "dashboard" / "assets" / "tracking.js").read_text(
        encoding="utf-8")
    assert int(re.search(r"export const KEPT_DAYS = (\d+);", worker).group(1)) == archive.kept_days
    assert int(re.search(r"export const PUBLISHED_DAYS = (\d+);", worker).group(1)) == \
        archive.published_days
    m = re.search(r"var ARCHIVE = \{ kept_days: (\d+), published_days: (\d+) \};", page)
    assert (int(m.group(1)), int(m.group(2))) == (archive.kept_days, archive.published_days)
    assert _state(config=ArchiveConfig(kept_days=10), decision_created_at=_ago(12)) is not None


# ---------------------------------------------------------------- the mirror

def _mirror(db, apps, decisions):
    ApplicationRepository(db.conn).replace_all(apps, decisions)


def _app(key, status="to_apply", **fields):
    row = {"job_key": key, "status": status, "applied_at": None, "follow_up_at": None,
           "note": None, "cv_url": None, "updated_at": _ago(1)}
    row.update(fields)
    return row


def _decision(id_, key, days_ago, label="good_fit"):
    return {"id": id_, "job_key": key, "label": label, "score_at_decision": 70,
            "created_at": _ago(days_ago)}


@pytest.fixture
def db():
    with Database(path=":memory:") as d:
        yield d


def test_list_archived_reads_decisions_offers_closures_and_reactivation(db, save_job):
    old = save_job(db.conn, "OLD")  # published 23 days ago
    db.conn.execute("UPDATE jobs SET published_at = ? WHERE id = ?", (_ago(23), old.id))
    gone = save_job(db.conn, "GONE")
    JobRepository(db.conn).mark_closed([gone.id], datetime(2026, 11, 5, tzinfo=UTC))
    save_job(db.conn, "KEPT16")
    save_job(db.conn, "KEPT14")
    save_job(db.conn, "SENT")
    _mirror(db, [
        _app("france_travail:KEPT16"), _app("france_travail:KEPT14"),
        _app("france_travail:OLD"), _app("france_travail:GONE"),
        _app("france_travail:SENT", "applied"),
        _app("france_travail:REACT", reactivated_at=_ago(2)),
        _app("france_travail:NODEC"),
    ], [
        _decision(1, "france_travail:KEPT16", 16), _decision(2, "france_travail:KEPT14", 14),
        _decision(3, "france_travail:OLD", 1), _decision(4, "france_travail:GONE", 30),
        _decision(5, "france_travail:SENT", 30), _decision(6, "france_travail:REACT", 30),
        # a later, non-keep decision on KEPT16 would hide the kept date: stays good_fit here
    ])
    archived = ApplicationRepository(db.conn).list_archived(TODAY, CFG)
    assert [(a.job_key, a.reason, a.days, a.new_today) for a in archived] == [
        ("france_travail:KEPT16", KEPT, 16, True),   # the first day over the threshold
        ("france_travail:OLD", PUBLISHED, 23, False),
    ]
    assert archived[0].text == "gardée il y a 16 jours" and archived[0].title == "DevOps KEPT16"
    # the next day KEPT16 is no longer new, KEPT14 is still live
    later = ApplicationRepository(db.conn).list_archived(TODAY + timedelta(days=1), CFG)
    assert [(a.job_key, a.new_today) for a in later] == [
        ("france_travail:KEPT16", False), ("france_travail:OLD", False)]


def test_an_archived_application_has_no_follow_up_but_the_rule_is_opt_in(db, save_job):
    save_job(db.conn, "A")
    save_job(db.conn, "B")
    _mirror(db, [
        _app("france_travail:A", follow_up_at="2026-11-01"),
        _app("france_travail:B", follow_up_at="2026-11-01"),
    ], [_decision(1, "france_travail:A", 20), _decision(2, "france_travail:B", 2)])
    repo = ApplicationRepository(db.conn)
    assert [f.job_key for f in repo.list_followups_due(TODAY, CFG)] == ["france_travail:B"]
    assert [f.job_key for f in repo.list_followups_due(TODAY)] == [
        "france_travail:A", "france_travail:B"]


def test_the_mirror_accepts_exports_with_and_without_reactivated_at(export, rows, db):
    with_col = {**rows.application("france_travail:R1"), "reactivated_at": _ago(2)}
    without = rows.application("france_travail:R2")
    bad = {**rows.application("france_travail:R3"), "reactivated_at": 12}
    result = import_tracking(db.conn, export([with_col, without, bad]), export([]))
    assert (result.applications, result.skipped) == (2, 1)
    stored = {r["job_key"]: r["reactivated_at"] for r in db.conn.execute(
        "SELECT job_key, reactivated_at FROM applications")}
    assert stored == {"france_travail:R1": _ago(2), "france_travail:R2": None}


def test_the_run_summary_counts_the_archived_applications(db, save_job):
    from job_match.pipelines.jobs import run_jobs

    class Quiet:
        name = "jooble"

        def fetch(self, since=None):
            return iter(())

        def to_job(self, raw):
            return raw

    save_job(db.conn, "A")
    save_job(db.conn, "B")
    today = datetime.now(UTC)
    kept = lambda days: (today - timedelta(days=days)).isoformat()  # noqa: E731
    _mirror(db, [_app("france_travail:A"), _app("france_travail:B")], [
        {**_decision(1, "france_travail:A", 0), "created_at": kept(16)},
        {**_decision(2, "france_travail:B", 0), "created_at": kept(40)},
    ])
    summary = run_jobs([Quiet()], _profile(), Settings(), db, {})
    assert (summary.archived, summary.archived_today) == (2, 1)
    md = jobs_markdown(summary, 1.0)
    assert "**1 candidature archivée aujourd'hui** · 2 archivées au total" in md
    record = RunRecord(id=1, pipeline="jobs", started_at=today, finished_at=today,
                       summary={"archived": 2, "archived_today": 1})
    entry = run_entry(record)
    assert (entry["archived"], entry["archived_today"]) == (2, 1)
    assert "archivée" not in jobs_markdown(RunSummary(pipeline="jobs"), 1.0)


def _profile():
    from job_match.config.schema import Candidate, Filters, FTSearch, Profile, Skills

    return Profile(candidate=Candidate(experience_years=3), skills=Skills(), filters=Filters(),
                   ft_search=FTSearch(keywords=["devops"]))
