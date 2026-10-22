"""Mirror the D1 tracking tables into the jobs DB, from `wrangler d1 execute --json` output.

D1 is the source of truth for my actions; this copy only lets the digest exclude handled
jobs and list follow-ups. Every row is validated like the Worker validates a write, and a
row that fails is skipped and counted. A file that is not the expected shape raises before
anything is written, so the previous mirror (restored with the DB snapshot) stays in place.
Notes and URLs are private: nothing here logs a row, only counts.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from job_match.persistence.repositories import ApplicationRepository
from job_match.tracking.constants import (
    JOB_KEY_RE,
    LABELS,
    NOTE_MAX,
    SKILL_RE,
    STATUSES,
    URL_MAX,
)

APPLICATION_FIELDS = (
    "job_key", "status", "applied_at", "follow_up_at", "note", "cv_url", "updated_at"
)
DECISION_FIELDS = ("id", "job_key", "label", "score_at_decision", "created_at")
SKILL_OVERRIDE_FIELDS = ("skill", "created_at")


class MirrorFormatError(ValueError):
    """The export is not `wrangler d1 execute --json` output for one successful query."""


@dataclass(frozen=True, slots=True)
class MirrorResult:
    applications: int
    decisions: int
    skipped: int
    skill_overrides: int = 0
    # The set of overridden skills differs from the previous mirror: stored jobs need a
    # reprocess to pick it up.
    overrides_changed: bool = False


def read_export(path: Path) -> list[dict]:
    """The `results` rows of a single-statement `wrangler d1 execute --json` export. A UTF-8
    byte order mark is accepted: PowerShell's `>` writes one, bash's does not."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MirrorFormatError(f"unreadable export ({type(exc).__name__})") from None
    if not (isinstance(doc, list) and len(doc) == 1 and isinstance(doc[0], dict)):
        raise MirrorFormatError("expected a list with one result object")
    result = doc[0]
    if result.get("success") is not True or not isinstance(result.get("results"), list):
        raise MirrorFormatError("the query did not succeed")
    if not all(isinstance(row, dict) for row in result["results"]):
        raise MirrorFormatError("a result row is not an object")
    return result["results"]


def _is_date(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_https(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or len(value) > URL_MAX:
        return False
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.netloc)


def _is_timestamp(value) -> bool:
    return isinstance(value, str) and 10 <= len(value) <= 40


def valid_application(row: dict) -> bool:
    return (
        set(row) == set(APPLICATION_FIELDS)
        and isinstance(row["job_key"], str) and JOB_KEY_RE.match(row["job_key"]) is not None
        and row["status"] in STATUSES
        and _is_date(row["applied_at"])
        and _is_date(row["follow_up_at"])
        and (row["note"] is None
             or (isinstance(row["note"], str) and len(row["note"]) <= NOTE_MAX))
        and _is_https(row["cv_url"])
        and _is_timestamp(row["updated_at"])
    )


def valid_decision(row: dict) -> bool:
    score = row.get("score_at_decision")
    return (
        set(row) == set(DECISION_FIELDS)
        and isinstance(row["id"], int) and not isinstance(row["id"], bool)
        and isinstance(row["job_key"], str) and JOB_KEY_RE.match(row["job_key"]) is not None
        and row["label"] in LABELS
        and (score is None
             or (isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100))
        and _is_timestamp(row["created_at"])
    )


def valid_skill_override(row: dict, vocabulary: frozenset[str]) -> bool:
    """A well-formed name that is in the vocabulary: the dashboard only offers those, so
    anything else did not come from it."""
    return (
        set(row) == set(SKILL_OVERRIDE_FIELDS)
        and isinstance(row["skill"], str) and SKILL_RE.match(row["skill"]) is not None
        and row["skill"] in vocabulary
        and _is_timestamp(row["created_at"])
    )


def import_tracking(
    conn,
    applications_path: Path,
    decisions_path: Path,
    skill_overrides_path: Path | None = None,
    vocabulary: tuple[str, ...] = (),
) -> MirrorResult:
    """Validate every export, then replace the mirror tables in one transaction.

    Without `skill_overrides_path` the overrides mirror is left as it is.
    """
    app_rows = read_export(applications_path)
    dec_rows = read_export(decisions_path)
    ovr_rows = read_export(skill_overrides_path) if skill_overrides_path else None
    apps = [r for r in app_rows if valid_application(r)]
    decs = [r for r in dec_rows if valid_decision(r)]
    skipped = len(app_rows) - len(apps) + len(dec_rows) - len(decs)

    repo = ApplicationRepository(conn)
    overrides = None
    changed = False
    if ovr_rows is not None:
        vocab = frozenset(vocabulary)
        overrides = [r for r in ovr_rows if valid_skill_override(r, vocab)]
        skipped += len(ovr_rows) - len(overrides)
        changed = {r["skill"] for r in overrides} != set(repo.list_skill_overrides())
    repo.replace_all(apps, decs, overrides)
    return MirrorResult(
        applications=len(apps),
        decisions=len(decs),
        skipped=skipped,
        skill_overrides=len(overrides) if overrides is not None else 0,
        overrides_changed=changed,
    )
