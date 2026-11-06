"""Auto-archive rule (ADR 0028), the Python copy of `tracking.js` / `worker/src/archive.js`.

An « À candidater » application nobody handled leaves the lists by itself, without being
deleted: archived when kept more than `kept_days` ago without being sent, or when its offer
was published more than `published_days` ago. The kept day is the « Réactiver » date when
there is one (it restarts the counter and switches the published rule off), else the
« Garder » decision (the latest decision, when it is `good_fit`); an application kept with no
decision (the status menu) has no kept day, so only the published rule can archive it.
Unknown publication: the kept rule alone. « Expirée » (the offer closed) wins: an expired
application is never archived. Nothing here writes anything; the Python side only counts and
keeps archived applications out of the digest's follow-ups.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from job_match.config.schema import ArchiveConfig

KEPT = "kept"
PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class ArchiveState:
    reason: str  # KEPT | PUBLISHED
    days: int

    @property
    def text(self) -> str:
        """« gardée il y a 17 jours » / « publiée il y a 23 jours », as the page says it."""
        verb = "gardée" if self.reason == KEPT else "publiée"
        return f"{verb} il y a {self.days} jour{'s' if self.days != 1 else ''}"


def day_of(value: str | datetime | date | None) -> date | None:
    """The calendar day of an ISO timestamp or date; None when unreadable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def kept_day(
    *,
    reactivated_at: str | None,
    decision_label: str | None,
    decision_created_at: str | None,
    updated_at: str | None,
) -> date | None:
    reactivated = day_of(reactivated_at)
    if reactivated is not None:
        return reactivated
    if decision_label == "good_fit":
        return day_of(decision_created_at)
    return None


def archive_state(
    *,
    status: str | None,
    reactivated_at: str | None,
    decision_label: str | None,
    decision_created_at: str | None,
    updated_at: str | None,
    published_at: str | datetime | None,
    closed: bool,
    today: date,
    config: ArchiveConfig,
) -> ArchiveState | None:
    """Why the application is archived today, or None when it is not (other statuses, an
    expired application, or neither threshold passed)."""
    if status != "to_apply" or closed:
        return None
    kept = kept_day(
        reactivated_at=reactivated_at, decision_label=decision_label,
        decision_created_at=decision_created_at, updated_at=updated_at,
    )
    if kept is not None:
        days = (today - kept).days
        if days > config.kept_days:
            return ArchiveState(KEPT, days)
    if reactivated_at is None:
        published = day_of(published_at)
        if published is not None:
            days = (today - published).days
            if days > config.published_days:
                return ArchiveState(PUBLISHED, days)
    return None
