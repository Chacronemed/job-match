"""`job-match ops reopen`: undo the closures a run made while its source was down (ADR 0027).

A run "marked down" carries the source in its stored `outages`; a run "beyond the threshold"
closed more than `outage_guard.max_closed_ratio` of at least `min_checked` offers it asked
(per source when the run stored per-source counters, the run's total before ADR 0027, when
only one closing source existed). Every job of the source marked closed between that run's
start and end is reopened: `closed_at` and `last_checked_at` cleared, so it shows again and
is asked about on the next run. Dry-run by default: nothing is written without `apply`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from job_match.config.schema import OutageGuardConfig
from job_match.domain.models import RunRecord
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository, RunRepository
from job_match.pipelines.outage import outages_of

RUNS_LIMIT = 400  # about a year of daily runs; `--since` narrows it further


@dataclass(frozen=True, slots=True)
class OutageWindow:
    run_id: int
    started_at: datetime
    ended_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class ReopenReport:
    source: str
    since: date
    applied: bool
    windows: tuple[OutageWindow, ...] = ()
    # run id → ids of the jobs closed inside its window
    job_ids: dict[int, list[int]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(len(ids) for ids in self.job_ids.values())


def _ratio_reason(checked: int, closed: int, guard: OutageGuardConfig) -> str | None:
    if checked < guard.min_checked or checked == 0:
        return None
    ratio = closed / checked
    if ratio <= guard.max_closed_ratio:
        return None
    return f"{closed}/{checked} offres vérifiées fermées ({round(ratio * 100)} %)"


def outage_windows(
    runs: list[RunRecord], source: str, since: date, guard: OutageGuardConfig
) -> list[OutageWindow]:
    """The jobs runs since `since` during which the source's closures are suspect."""
    windows: list[OutageWindow] = []
    for run in runs:
        if run.pipeline != "jobs" or run.started_at.date() < since:
            continue
        summary = run.summary
        reason: str | None = None
        marked = [o for o in outages_of(summary) if o.source == source and o.whole_source]
        if marked:
            reason = f"run marqué en panne : {marked[0].reason}"
        else:
            per = (summary.get("by_source") or {}).get(source) or {}
            if "checked" in per:
                reason = _ratio_reason(int(per.get("checked", 0) or 0),
                                       int(per.get("closed", 0) or 0), guard)
            elif source in (summary.get("by_source") or {}):
                # Before ADR 0027 only the run's totals were stored.
                reason = _ratio_reason(int(summary.get("checked", 0) or 0),
                                       int(summary.get("closed", 0) or 0), guard)
                if reason:
                    reason += " (compteurs du run entier, antérieurs à la garde)"
        if reason is None:
            continue
        ended = run.finished_at or (run.started_at + timedelta(hours=6))
        windows.append(OutageWindow(run.id, run.started_at, ended, reason))
    return windows


def reopen(
    db: Database, source: str, since: date, guard: OutageGuardConfig, *, apply: bool = False
) -> ReopenReport:
    runs = RunRepository(db.conn).list_recent(("jobs",), limit=RUNS_LIMIT)
    windows = outage_windows(runs, source, since, guard)
    repo = JobRepository(db.conn)
    job_ids: dict[int, list[int]] = {}
    for w in windows:
        closed = repo.list_closed_between(source, w.started_at, w.ended_at)
        ids = [job_id for job_id, _sid in closed]
        if ids:
            job_ids[w.run_id] = ids
    if apply:
        for ids in job_ids.values():
            repo.reopen(ids)
    return ReopenReport(source=source, since=since, applied=apply,
                        windows=tuple(windows), job_ids=job_ids)


def format_report(report: ReopenReport) -> str:
    tag = "APPLIED" if report.applied else "DRY RUN"
    lines = [f"[{tag}] reopen {report.source} since {report.since.isoformat()}"]
    if not report.windows:
        lines.append("  no run marked down or beyond the closure threshold: nothing to reopen")
        return "\n".join(lines)
    for w in report.windows:
        n = len(report.job_ids.get(w.run_id, []))
        day = w.started_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
        lines.append(f"  run {w.run_id} ({day} UTC): {n} offer(s) closed — {w.reason}")
    verb = "reopened" if report.applied else "would be reopened"
    lines.append(f"  {report.total} offer(s) {verb}" + ("" if report.applied else " (add --apply)"))
    return "\n".join(lines)
