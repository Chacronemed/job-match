"""Closure check: ask each source whether the offers we still show are still online.

Runs after collection, on the jobs the digest and the dashboard would show (canonical,
ELIGIBLE or STRETCH, not closed, inside the age cut-off) plus every job kept « À
candidater », at most once per `RECHECK_AFTER` per job. Only a clear "gone" marks a job
closed; a network error, a 5xx or any other unclear answer changes nothing and is retried on
the next run. Sources without `check_offer` are skipped: their jobs rely on
`jobs.max_age_days` alone.

The outage guard (ADR 0027, `pipelines/outage.py`) sits on top: an offer of a source (or an
ATS board) read as down during collection is not even asked, and a source whose answers say
"gone" for more than `outage_guard.max_closed_ratio` of at least `min_checked` offers has
nothing written for it this run. Both count in `suspended`, per source too, so the summary
can say « clôtures suspendues ».
"""
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from job_match.adapters.jobs.base import JobSource, OfferStatus
from job_match.config.schema import Settings
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository
from job_match.pipelines.outage import SourceOutage, banner, closure_outage

logger = logging.getLogger(__name__)

RECHECK_AFTER = timedelta(hours=24)  # the run is daily; nothing to tune


@dataclass(frozen=True, slots=True)
class ClosureStats:
    checked: int = 0    # offers asked at the source
    closed: int = 0     # of which the source said are gone, and were marked so
    errors: int = 0     # of which got no clear answer (left untouched)
    suspended: int = 0  # not asked, or "gone" not applied, because the source is down
    # Per source: {checked, closed, errors, suspended}. Not part of equality: the totals
    # are what the older tests and callers compare.
    by_source: dict[str, dict[str, int]] = field(default_factory=dict, compare=False)
    # The sources the closure answers themselves revealed as down (kind "closures").
    outages: tuple[SourceOutage, ...] = field(default=(), compare=False)


class _SourceState:
    __slots__ = ("checked", "errors", "suspended", "stopped", "open_ids", "closed_ids")

    def __init__(self) -> None:
        self.checked = 0
        self.errors = 0
        self.suspended = 0
        self.stopped = False
        self.open_ids: list[int] = []
        self.closed_ids: list[int] = []


def check_closed(
    sources: Iterable[JobSource],
    settings: Settings,
    db: Database,
    now: datetime,
    *,
    dry_run: bool = False,
    outages: Iterable[SourceOutage] = (),
) -> ClosureStats:
    """`outages`: what the collection already revealed (`detect_collection_outages`); the
    offers they cover are suspended without a call."""
    checkers = {
        source.name: check
        for source in sources
        if (check := getattr(source, "check_offer", None)) is not None
    }
    if not checkers:
        return ClosureStats()
    known = list(outages)

    repo = JobRepository(db.conn)
    candidates = repo.list_to_check(
        now, settings.jobs.max_age_days, recheck_after=RECHECK_AFTER
    )
    states: dict[str, _SourceState] = {}
    for job_id, source_name, source_job_id in candidates:
        check = checkers.get(source_name)
        if check is None:
            continue
        st = states.setdefault(source_name, _SourceState())
        if any(o.covers(source_name, source_job_id) for o in known):
            st.suspended += 1
            continue
        if st.stopped:
            continue
        st.checked += 1
        try:
            status = check(source_job_id)
        except Exception as exc:
            # A source that cannot even be asked (no token, dead host) would fail for every
            # offer: stop asking this source, keep what was learnt, nothing is marked closed.
            logger.warning(
                "closure check stopped at %s: %s", source_name, type(exc).__name__
            )
            st.errors += 1
            st.stopped = True
            continue
        if status is OfferStatus.CLOSED:
            st.closed_ids.append(job_id)
        elif status is OfferStatus.OPEN:
            st.open_ids.append(job_id)
        else:
            st.errors += 1  # UNKNOWN: nothing written, asked again next run

    found: list[SourceOutage] = []
    by_source: dict[str, dict[str, int]] = {}
    checked = closed = errors = suspended = 0
    for source_name in sorted(states):
        st = states[source_name]
        outage = closure_outage(source_name, st.checked, len(st.closed_ids), settings.outage_guard)
        if outage is not None:
            # Too many "gone" at once: the API is down, not the market. Nothing is written
            # for this source today, not even the open marks; every offer is asked again.
            found.append(outage)
            logger.warning("%s", banner(outage))
            st.suspended += len(st.closed_ids)
            st.closed_ids = []
            st.open_ids = []
        if not dry_run:
            repo.mark_checked(st.open_ids, now)
            repo.mark_closed(st.closed_ids, now)
        counts = {
            "checked": st.checked,
            "closed": len(st.closed_ids),
            "errors": st.errors,
            "suspended": st.suspended,
        }
        by_source[source_name] = counts
        checked += st.checked
        closed += len(st.closed_ids)
        errors += st.errors
        suspended += st.suspended

    logger.info(
        "closure check: checked=%d closed=%d unclear=%d suspended=%d",
        checked, closed, errors, suspended,
    )
    return ClosureStats(
        checked=checked, closed=closed, errors=errors, suspended=suspended,
        by_source=by_source, outages=tuple(found),
    )
