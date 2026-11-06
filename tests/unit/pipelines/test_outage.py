"""ADR 0027: the source outage guard. A source down for the day closes nothing, the others
run, the run says so; `ops reopen` undoes closures made while a source was down."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match.adapters.jobs.base import OfferStatus, QueryStat, RequestStats
from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    OutageGuardConfig,
    Profile,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import (
    ContractType,
    Eligibility,
    Job,
    RunRecord,
    RunSummary,
    WorkplaceType,
)
from job_match.notification.assemble import today_outages
from job_match.ops.reopen import format_report, outage_windows, reopen
from job_match.ops.summary import jobs_markdown
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository, RunRepository
from job_match.pipelines.closure import ClosureStats, check_closed
from job_match.pipelines.jobs import run_jobs
from job_match.pipelines.outage import (
    BOARD_EMPTY,
    CLOSURES,
    NO_RESULTS,
    REQUESTS_FAILED,
    SourceOutage,
    banner,
    closure_outage,
    detect_collection_outages,
    fetched_history,
)

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
GUARD = OutageGuardConfig()  # the defaults are settings.yaml's values (tests/unit/config)


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=3),
        skills=Skills(preferred=[SkillWeight(name="kubernetes", weight=25)]),
        filters=Filters(contract_types=[ContractType.CDI]),
        ft_search=FTSearch(keywords=["devops"]),
    )


SETTINGS = Settings(strong_threshold=70, title_bonus=0)


def _job(sid: str, source: str = "france_travail", **overrides) -> Job:
    defaults = dict(
        source=source, source_job_id=sid, title=f"DevOps {sid}", company=f"Acme {sid}",
        location="Paris", workplace_type=WorkplaceType.HYBRID, contract_type=ContractType.CDI,
        description="We need a DevOps engineer with Kubernetes skills.",
        url=f"https://example.com/jobs/{sid}", collected_at=NOW,
        eligibility=Eligibility.ELIGIBLE, score=75,
    )
    return Job(**{**defaults, **overrides})


def _store(db, jobs: list[Job]) -> list[int]:
    repo = JobRepository(db.conn)
    return [repo.save(j).id for j in jobs]


def _history(db, by_source: dict, days: int = 7, **extra) -> None:
    """`days` stored jobs runs, one a day, with these per-source counts."""
    repo = RunRepository(db.conn)
    for i in range(days):
        at = NOW - timedelta(days=i + 1)
        repo.save(RunSummary(pipeline="jobs", by_source=by_source, **extra), at, at)


def _closed(db, job_id) -> str | None:
    return db.conn.execute("SELECT closed_at FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def _checked(db, job_id) -> str | None:
    row = db.conn.execute("SELECT last_checked_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row[0]


class FakeSource:
    """A source with every optional attribute the pipeline reads: `fetch` yields pre-built
    Jobs, `check_offer` answers from a script and records what it was asked."""

    reports_by_company = False

    def __init__(self, name, items=(), answers=None, default=OfferStatus.OPEN,
                 request_stats=None, query_stats=()):
        self.name = name
        self._items = list(items)
        self._answers = answers or {}
        self._default = default
        self.request_stats = request_stats
        self.query_stats = tuple(query_stats)
        self.api_calls_count = len(self._items)
        self.asked: list[str] = []

    def fetch(self, since=None):
        return iter(self._items)

    def to_job(self, raw):
        return raw

    def check_offer(self, source_job_id):
        self.asked.append(source_job_id)
        return self._answers.get(source_job_id, self._default)


class BoardSource(FakeSource):
    reports_by_company = True


# ---------------------------------------------------------------- scenarios through run_jobs

def test_france_travail_down_everywhere_closes_nothing_and_says_so(db):
    """2026-11-06: the search answered 0 offers and every offer page "does not exist"."""
    _history(db, {"france_travail": {"fetched": 30, "eligible": 5}, "ats": {"fetched": 40}})
    ids = _store(db, [_job(f"FT-{i}") for i in range(12)])
    ft = FakeSource("france_travail", items=[], default=OfferStatus.CLOSED,
                    request_stats=RequestStats(attempted=14, failed=0))

    summary = run_jobs([ft], _profile(), SETTINGS, db, {})

    assert ft.asked == []  # not even asked: a dead API's "gone" is worth nothing
    assert summary.closed == 0 and summary.suspended == 12 and summary.checked == 0
    assert [o["kind"] for o in summary.outages] == [NO_RESULTS]
    assert summary.outages[0]["source"] == "france_travail"
    assert summary.outages[0]["label"] == "France Travail"
    assert "30 en moyenne sur les 7 derniers runs" in summary.outages[0]["reason"]
    assert summary.by_source["france_travail"] == {
        "fetched": 0, "eligible": 0, "duplicates": 0, "calls": 0,
        "checked": 0, "closed": 0, "suspended": 12,
    }
    assert all(_closed(db, i) is None and _checked(db, i) is None for i in ids)
    # stored with the run, read back by the digest, the summary and the page
    stored = RunRepository(db.conn).list_recent(("jobs",), limit=1)[0].summary
    assert stored["outages"] == summary.outages and stored["suspended"] == 12
    assert today_outages(db, datetime.now(UTC)) == ("France Travail",)
    md = jobs_markdown(summary, 12.0)
    assert "⚠️ **France Travail indisponible — clôtures suspendues : 0 offre récupérée" in md
    assert "| france_travail ⚠️ down | 0 | 0 | 0 | 0 | 0 | 0 | 12 |" in md
    assert "0 re-checked, 0 closed, 12 closures suspended" in md


def test_no_history_means_no_zero_result_outage(db):
    """The first runs ever (or a source just enabled) have nothing to compare 0 with."""
    ids = _store(db, [_job("FT-1"), _job("FT-2")])
    ft = FakeSource("france_travail", items=[], default=OfferStatus.CLOSED)

    summary = run_jobs([ft], _profile(), SETTINGS, db, {})

    assert summary.outages == [] and summary.closed == 2
    assert all(_closed(db, i) is not None for i in ids)


def test_half_of_the_closure_answers_say_gone_closes_nothing(db):
    """50 % of the offer pages answer 404: an API that lost its data, not 10 closings."""
    _history(db, {"france_travail": {"fetched": 30}})
    ids = _store(db, [_job(f"FT-{i}") for i in range(20)])
    gone = {f"FT-{i}": OfferStatus.CLOSED for i in range(10)}
    fresh = _job("FT-NEW")
    ft = FakeSource("france_travail", items=[fresh], answers=gone, default=OfferStatus.OPEN,
                    request_stats=RequestStats(attempted=21, failed=0))

    summary = run_jobs([ft], _profile(), SETTINGS, db, {})

    assert len(ft.asked) == 20
    assert summary.checked == 20 and summary.closed == 0 and summary.suspended == 10
    assert [o["kind"] for o in summary.outages] == [CLOSURES]
    assert "50 % des 20 offres vérifiées annoncées fermées" in summary.outages[0]["reason"]
    # nothing written for that source, not even the open marks: all asked again next run
    assert all(_closed(db, i) is None and _checked(db, i) is None for i in ids)
    assert summary.by_source["france_travail"]["closed"] == 0
    assert summary.by_source["france_travail"]["suspended"] == 10


def test_mostly_failed_requests_suspend_the_source(db):
    _history(db, {"france_travail": {"fetched": 30}})
    ids = _store(db, [_job("FT-1"), _job("FT-2")])
    ft = FakeSource("france_travail", items=[_job("FT-NEW")], default=OfferStatus.CLOSED,
                    request_stats=RequestStats(attempted=10, failed=6))

    summary = run_jobs([ft], _profile(), SETTINGS, db, {})

    assert ft.asked == [] and summary.closed == 0 and summary.suspended == 2
    assert summary.outages[0]["kind"] == REQUESTS_FAILED
    assert "60 % des requêtes en échec (6/10, seuil 50 %)" in summary.outages[0]["reason"]
    assert all(_closed(db, i) is None for i in ids)


def test_one_workday_board_at_zero_suspends_that_board_only(db):
    """Thales' Workday board lists nothing today after 12 yesterday; Acme's Greenhouse board
    is fine. Only Thales' offers are spared; the other sources are not touched either."""
    repo = RunRepository(db.conn)
    yesterday = NOW - timedelta(days=1)
    repo.save(RunSummary(
        pipeline="jobs",
        by_source={"ats": {"fetched": 20}, "france_travail": {"fetched": 30}},
        by_board={"ats": {"workday:thales.careers": 12, "greenhouse:acme": 8}},
    ), yesterday, yesterday)
    thales = _store(db, [_job(f"workday:thales.careers:R{i}", source="ats") for i in range(3)])
    acme = _store(db, [_job(f"greenhouse:acme:9{i}", source="ats") for i in range(2)])
    ft_ids = _store(db, [_job("FT-1"), _job("FT-2")])
    acme_new = [_job(f"greenhouse:acme:{i}", source="ats") for i in range(8)]
    ats = BoardSource(
        "ats", items=acme_new, default=OfferStatus.CLOSED,
        query_stats=[QueryStat("thales.careers", "workday", 0, 0, "ats"),
                     QueryStat("acme", "greenhouse", 8, 8, "ats")],
    )
    ft = FakeSource("france_travail", items=[_job("FT-NEW")],
                    answers={"FT-1": OfferStatus.CLOSED}, default=OfferStatus.OPEN)

    summary = run_jobs([ats, ft], _profile(), SETTINGS, db, {})

    assert sorted(ats.asked) == ["greenhouse:acme:90", "greenhouse:acme:91"]
    assert [o["kind"] for o in summary.outages] == [BOARD_EMPTY]
    assert summary.outages[0]["boards"] == ["workday:thales.careers"]
    assert "12 au run précédent" in summary.outages[0]["reason"]
    assert all(_closed(db, i) is None for i in thales)   # spared, not asked
    assert all(_closed(db, i) is not None for i in acme)  # the healthy board's answer stands
    assert _closed(db, ft_ids[0]) is not None and _closed(db, ft_ids[1]) is None
    assert summary.by_source["ats"] == {
        "fetched": 8, "eligible": 8, "duplicates": 0, "calls": 8,
        "checked": 2, "closed": 2, "suspended": 3,
    }
    assert summary.by_board == {"ats": {"workday:thales.careers": 0, "greenhouse:acme": 8}}
    assert "(1 board(s)) indisponible — clôtures suspendues" in jobs_markdown(summary, 1.0)
    # a board down alone is not "the source is down": the digest does not announce it
    assert today_outages(db, datetime.now(UTC)) == ()


def test_a_normal_run_with_a_few_closures_applies_them(db):
    _history(db, {"france_travail": {"fetched": 30}})
    ids = _store(db, [_job(f"FT-{i}") for i in range(40)])
    gone = {"FT-3": OfferStatus.CLOSED, "FT-17": OfferStatus.CLOSED}  # 5 %
    ft = FakeSource("france_travail", items=[_job("FT-NEW")], answers=gone,
                    request_stats=RequestStats(attempted=41, failed=1))

    summary = run_jobs([ft], _profile(), SETTINGS, db, {})

    assert summary.outages == [] and summary.suspended == 0
    assert summary.checked == 40 and summary.closed == 2
    assert sum(_closed(db, i) is not None for i in ids) == 2
    assert sum(_checked(db, i) is not None for i in ids) == 40
    assert summary.by_source["france_travail"]["closed"] == 2
    assert "closures suspended" not in jobs_markdown(summary, 1.0)


def test_a_down_run_is_not_what_normal_looks_like(db):
    """Day 2 of an outage: yesterday's 0 (marked down) does not drag the mean under 20."""
    _history(db, {"france_travail": {"fetched": 30}}, days=7)
    repo = RunRepository(db.conn)
    down = SourceOutage("france_travail", NO_RESULTS, "0 offre").as_dict()
    repo.save(RunSummary(pipeline="jobs", by_source={"france_travail": {"fetched": 0}},
                         outages=[down]), NOW - timedelta(hours=20), NOW - timedelta(hours=20))
    ids = _store(db, [_job("FT-1")])
    ft = FakeSource("france_travail", items=[], default=OfferStatus.CLOSED)

    summary = run_jobs([ft], _profile(), SETTINGS, db, {})

    assert [o["kind"] for o in summary.outages] == [NO_RESULTS]
    assert _closed(db, ids[0]) is None


# ---------------------------------------------------------------- the guard's pieces

def _record(i, by_source, outages=(), by_board=None):
    at = NOW - timedelta(days=i)
    summary = {"by_source": by_source, "outages": list(outages)}
    if by_board is not None:
        summary["by_board"] = by_board
    return RunRecord(id=100 - i, pipeline="jobs", started_at=at, finished_at=at, summary=summary)


def test_fetched_history_skips_runs_without_the_source_and_down_runs():
    runs = [
        _record(0, {"france_travail": {"fetched": 0}},
                [SourceOutage("france_travail", NO_RESULTS, "x").as_dict()]),
        _record(1, {"ats": {"fetched": 9}}),
        _record(2, {"france_travail": {"fetched": 25}}),
        _record(3, {"france_travail": {"fetched": 35}}),
        RunRecord(id=1, pipeline="funding", started_at=NOW, finished_at=NOW,
                  summary={"by_source": {"france_travail": {"fetched": 999}}}),
    ]
    assert fetched_history(runs, "france_travail", 7) == [25, 35]
    assert fetched_history(runs, "france_travail", 1) == [25]


def test_detection_thresholds_are_strict_and_in_order():
    history = [_record(i + 1, {"france_travail": {"fetched": 20}}) for i in range(7)]
    guard = OutageGuardConfig()
    # mean exactly 20 counts; 19 does not
    assert detect_collection_outages(
        {"france_travail": {"fetched": 0}}, {}, {}, history, guard)[0].kind == NO_RESULTS
    low = [_record(i + 1, {"france_travail": {"fetched": 19}}) for i in range(7)]
    assert detect_collection_outages({"france_travail": {"fetched": 0}}, {}, {}, low, guard) == []
    # exactly half the requests failed is not "more than half"
    half = {"france_travail": RequestStats(10, 5)}
    assert detect_collection_outages({"france_travail": {"fetched": 3}}, half, {}, [], guard) == []
    more = {"france_travail": RequestStats(10, 6)}
    found = detect_collection_outages({"france_travail": {"fetched": 3}}, more, {}, [], guard)
    assert [o.kind for o in found] == [REQUESTS_FAILED]
    # a source without request stats (jooble) is judged on its results only
    none = {"jooble": None}
    assert detect_collection_outages({"jooble": {"fetched": 3}}, none, {}, [], guard) == []
    # one outage per source: 0 results wins over the request ratio
    found = detect_collection_outages({"france_travail": {"fetched": 0}}, more, {}, history, guard)
    assert [o.kind for o in found] == [NO_RESULTS]


def test_board_rule_needs_a_previous_run_with_enough_postings():
    guard = OutageGuardConfig()
    before = [_record(1, {"ats": {"fetched": 20}},
                      by_board={"ats": {"workday:a": 5, "lever:b": 4, "ashby:c": 0}})]
    now = {"ats": {"workday:a": 0, "lever:b": 0, "ashby:c": 0, "greenhouse:new": 0}}
    found = detect_collection_outages({"ats": {"fetched": 3}}, {}, now, before, guard)
    assert len(found) == 1 and found[0].kind == BOARD_EMPTY
    assert found[0].boards == ("workday:a",)  # b had 4 (< 5), c was already 0, new is unknown
    assert not found[0].whole_source
    assert found[0].covers("ats", "workday:a:R1") and not found[0].covers("ats", "lever:b:1")
    # a run older than ADR 0027 stored no by_board: nothing to compare with
    assert detect_collection_outages(
        {"ats": {"fetched": 3}}, {}, now, [_record(1, {"ats": {"fetched": 20}})], guard) == []


def test_closure_outage_needs_min_checked_and_more_than_the_ratio():
    guard = OutageGuardConfig()
    assert closure_outage("ats", 9, 9, guard) is None  # fewer than 10 asked proves nothing
    assert closure_outage("ats", 10, 3, guard) is None  # exactly 30 %
    out = closure_outage("ats", 10, 4, guard)
    assert out is not None and out.kind == CLOSURES and out.whole_source
    assert banner(out) == ("Pages carrière (ATS) indisponible — clôtures suspendues : 40 % des 10 "
                           "offres vérifiées annoncées fermées (seuil 30 %, minimum 10 vérifiées)")
    assert SourceOutage.from_dict(out.as_dict()) == out


def test_check_closed_counts_per_source_and_keeps_asking_the_other_source(db):
    """One source that cannot be asked stops only itself (before ADR 0027 it stopped all)."""
    ids = _store(db, [_job("A"), _job("B"), _job("J1", source="jooble")])

    class Dead(FakeSource):
        def check_offer(self, sid):
            self.asked.append(sid)
            raise RuntimeError("no token")

    dead = Dead("france_travail")
    jooble = FakeSource("jooble", answers={"J1": OfferStatus.CLOSED})
    stats = check_closed([dead, jooble], SETTINGS, db, NOW)

    assert stats == ClosureStats(checked=2, closed=1, errors=1, suspended=0)
    assert dead.asked == ["A"] and jooble.asked == ["J1"]
    assert stats.by_source == {
        "france_travail": {"checked": 1, "closed": 0, "errors": 1, "suspended": 0},
        "jooble": {"checked": 1, "closed": 1, "errors": 0, "suspended": 0},
    }
    assert _closed(db, ids[2]) is not None and _closed(db, ids[0]) is None


# ---------------------------------------------------------------- ops reopen

def _closed_at(db, job_id, when):
    db.conn.execute("UPDATE jobs SET closed_at = ?, last_checked_at = ? WHERE id = ?",
                    (when.isoformat(), when.isoformat(), job_id))
    db.conn.commit()


def test_reopen_dry_run_then_apply_on_a_run_marked_down_and_a_legacy_run(db):
    repo = RunRepository(db.conn)
    # day -3: a run before the guard existed, totals only, 10 of 20 closed (beyond 30 %)
    legacy_start = NOW - timedelta(days=3)
    legacy_end = legacy_start + timedelta(minutes=20)
    repo.save(RunSummary(pipeline="jobs", checked=20, closed=10,
                         by_source={"france_travail": {"fetched": 0, "calls": 21}}),
              legacy_start, legacy_end)
    # day -2: a healthy run (2 of 40 closed)
    ok_start = NOW - timedelta(days=2)
    repo.save(RunSummary(pipeline="jobs", checked=40, closed=2,
                         by_source={"france_travail": {"fetched": 30, "checked": 40, "closed": 2,
                                                       "suspended": 0}}),
              ok_start, ok_start + timedelta(minutes=20))
    # day -1: a run marked down (its closures were already withheld; a few slipped before)
    down_start = NOW - timedelta(days=1)
    repo.save(RunSummary(pipeline="jobs",
                         outages=[SourceOutage("france_travail", NO_RESULTS, "0 offre").as_dict()],
                         by_source={"france_travail": {"fetched": 0, "checked": 0, "closed": 0,
                                                       "suspended": 30}}),
              down_start, down_start + timedelta(minutes=20))
    ids = _store(db, [_job(f"FT-{i}") for i in range(6)] + [_job("ATS-1", source="ats")])
    for i in range(3):
        _closed_at(db, ids[i], legacy_start + timedelta(minutes=10))  # legacy window
    _closed_at(db, ids[3], ok_start + timedelta(minutes=10))          # healthy run: stays
    _closed_at(db, ids[4], down_start + timedelta(minutes=10))        # down run
    _closed_at(db, ids[5], NOW - timedelta(days=10))                  # before --since
    _closed_at(db, ids[6], legacy_start + timedelta(minutes=10))      # another source

    since = (NOW - timedelta(days=4)).date()
    report = reopen(db, "france_travail", since, GUARD)

    assert not report.applied and report.total == 4
    assert [w.run_id for w in report.windows] == [3, 1]  # newest first, the healthy run absent
    assert "run marqué en panne" in report.windows[0].reason
    assert "antérieurs à la garde" in report.windows[1].reason
    assert all(_closed(db, i) is not None for i in ids)  # dry run wrote nothing
    text = format_report(report)
    assert "[DRY RUN]" in text and "4 offer(s) would be reopened (add --apply)" in text

    applied = reopen(db, "france_travail", since, GUARD, apply=True)
    assert applied.applied and applied.total == 4
    assert [_closed(db, i) is None for i in ids] == [True, True, True, False, True, False, False]
    assert _checked(db, ids[0]) is None  # asked again on the next run
    assert "[APPLIED]" in format_report(applied) and "4 offer(s) reopened" in format_report(applied)
    # nothing left to reopen
    assert reopen(db, "france_travail", since, GUARD).total == 0
    assert "nothing to reopen" in format_report(reopen(db, "ats", since, GUARD))


def test_outage_windows_respects_since_and_the_per_source_counters():
    runs = [
        _record(0, {"ats": {"fetched": 5, "checked": 12, "closed": 6, "suspended": 0}}),
        _record(1, {"ats": {"fetched": 5, "checked": 12, "closed": 1, "suspended": 0}}),
        _record(9, {"ats": {"fetched": 5, "checked": 12, "closed": 12, "suspended": 0}}),
    ]
    since = (NOW - timedelta(days=5)).date()
    windows = outage_windows(runs, "ats", since, GUARD)
    assert [w.run_id for w in windows] == [100]
    assert windows[0].reason == "6/12 offres vérifiées fermées (50 %)"
    assert outage_windows(runs, "france_travail", since, GUARD) == []
