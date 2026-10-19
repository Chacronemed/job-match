"""Closure check: ask each source whether the offers we still show are still online.

Runs after collection, on the jobs the digest and the dashboard would show (canonical,
ELIGIBLE or STRETCH, not closed, inside the age cut-off), at most once per
`RECHECK_AFTER` per job. Only a clear "gone" marks a job closed; a network error, a 5xx
or any other unclear answer changes nothing and is retried on the next run. Sources
without `check_offer` are skipped: their jobs rely on `jobs.max_age_days` alone.
"""
import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from job_match.adapters.jobs.base import OfferStatus
from job_match.config.schema import Settings
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository

logger = logging.getLogger(__name__)

RECHECK_AFTER = timedelta(hours=24)  # the run is daily; nothing to tune


class ClosureStats(NamedTuple):
    checked: int = 0  # offers asked at the source
    closed: int = 0   # of which the source said are gone
    errors: int = 0   # of which got no clear answer (left untouched)


def check_closed(
    sources,
    settings: Settings,
    db: Database,
    now: datetime,
    *,
    dry_run: bool = False,
) -> ClosureStats:
    checkers = {
        source.name: check
        for source in sources
        if (check := getattr(source, "check_offer", None)) is not None
    }
    if not checkers:
        return ClosureStats()

    repo = JobRepository(db.conn)
    candidates = repo.list_to_check(
        now, settings.jobs.max_age_days, recheck_after=RECHECK_AFTER
    )
    checked = closed = errors = 0
    open_ids: list[int] = []
    closed_ids: list[int] = []
    for job_id, source_name, source_job_id in candidates:
        check = checkers.get(source_name)
        if check is None:
            continue
        checked += 1
        try:
            status = check(source_job_id)
        except Exception as exc:
            # A source that cannot even be asked (no token, dead host) would fail for every
            # offer: stop here, keep what was learnt, nothing is marked closed.
            logger.warning(
                "closure check stopped at %s: %s", source_name, type(exc).__name__
            )
            errors += 1
            break
        if status is OfferStatus.CLOSED:
            closed += 1
            closed_ids.append(job_id)
        elif status is OfferStatus.OPEN:
            open_ids.append(job_id)
        else:
            errors += 1  # UNKNOWN: nothing written, asked again next run

    if not dry_run:
        repo.mark_checked(open_ids, now)
        repo.mark_closed(closed_ids, now)
    logger.info(
        "closure check: checked=%d closed=%d unclear=%d", checked, closed, errors
    )
    return ClosureStats(checked=checked, closed=closed, errors=errors)
