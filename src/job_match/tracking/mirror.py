"""Mirror the D1 tracking tables into the jobs DB, from `wrangler d1 execute --json` output.

D1 is the source of truth for my actions; this copy only lets the digest exclude handled
jobs and list follow-ups. Every row is validated like the Worker validates a write, and a
row that fails is skipped and counted. A file that is not the expected shape raises before
anything is written, so the previous mirror (restored with the DB snapshot) stays in place.
Notes and URLs are private: nothing here logs a row, only counts.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from job_match.persistence.repositories import AiRepository, ApplicationRepository
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
# The AI rerank tables (worker/migrations/0004_ai_verdicts.sql, ADR 0016).
AI_VERDICT_FIELDS = (
    "id", "job_key", "hash", "provider", "model", "prompt_version", "score", "level",
    "reasons", "red_flags", "created_at",
)
AI_USAGE_FIELDS = ("day", "provider", "calls", "tokens_in", "tokens_out")
DISAGREEMENT_FIELDS = (
    "id", "job_key", "hash", "python_score", "python_section", "ai_score", "ai_level", "kind",
    "created_at",
)
AI_RUN_FIELDS = (
    "id", "started_at", "finished_at", "outcome", "http_status", "provider", "counters",
)
AI_RUN_OUTCOMES = ("ok", "stopped", "no_profile", "failed")
AI_PROVIDERS = ("anthropic", "workers_ai")
AI_LEVELS = ("fort", "tenter", "hors_sujet")
DISAGREEMENT_KINDS = ("gap", "off_topic_strong")
AI_REASONS_MAX = 3
AI_REASON_LENGTH = 160
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _is_int(value, lo: int = 0, hi: int | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        return False
    return hi is None or value <= hi


def _is_reasons(value) -> bool:
    """A JSON list of at most AI_REASONS_MAX short strings, as the Worker stores it."""
    if not isinstance(value, str):
        return False
    try:
        items = json.loads(value)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(items, list) and len(items) <= AI_REASONS_MAX
        and all(isinstance(i, str) and 0 < len(i) <= AI_REASON_LENGTH for i in items)
    )


def valid_ai_verdict(row: dict) -> bool:
    return (
        set(row) == set(AI_VERDICT_FIELDS)
        and _is_int(row["id"], 1)
        and isinstance(row["job_key"], str) and JOB_KEY_RE.match(row["job_key"]) is not None
        and isinstance(row["hash"], str) and _HASH_RE.match(row["hash"]) is not None
        and row["provider"] in AI_PROVIDERS
        and isinstance(row["model"], str) and 0 < len(row["model"]) <= 80
        and isinstance(row["prompt_version"], str) and 0 < len(row["prompt_version"]) <= 16
        and _is_int(row["score"], 0, 100)
        and row["level"] in AI_LEVELS
        and _is_reasons(row["reasons"]) and _is_reasons(row["red_flags"])
        and _is_timestamp(row["created_at"])
    )


def valid_ai_usage(row: dict) -> bool:
    return (
        set(row) == set(AI_USAGE_FIELDS)
        and row["day"] is not None and _is_date(row["day"])
        and row["provider"] in AI_PROVIDERS
        and all(_is_int(row[k]) for k in ("calls", "tokens_in", "tokens_out"))
    )


def valid_disagreement(row: dict) -> bool:
    return (
        set(row) == set(DISAGREEMENT_FIELDS)
        and _is_int(row["id"], 1)
        and isinstance(row["job_key"], str) and JOB_KEY_RE.match(row["job_key"]) is not None
        and isinstance(row["hash"], str) and _HASH_RE.match(row["hash"]) is not None
        and _is_int(row["python_score"], 0, 100)
        and isinstance(row["python_section"], str) and len(row["python_section"]) <= 16
        and _is_int(row["ai_score"], 0, 100)
        and row["ai_level"] in AI_LEVELS
        and row["kind"] in DISAGREEMENT_KINDS
        and _is_timestamp(row["created_at"])
    )


def _is_counters(value) -> bool:
    """A JSON object of non-negative integers, as the Worker writes its counters."""
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        obj = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict) and all(
        isinstance(k, str) and _is_int(v) for k, v in obj.items()
    )


def valid_ai_run(row: dict) -> bool:
    status = row.get("http_status")
    return (
        set(row) == set(AI_RUN_FIELDS)
        and _is_int(row["id"], 1)
        and _is_timestamp(row["started_at"]) and _is_timestamp(row["finished_at"])
        and row["outcome"] in AI_RUN_OUTCOMES
        and (status is None or _is_int(status, 100, 599))
        and (row["provider"] is None or row["provider"] in AI_PROVIDERS)
        and _is_counters(row["counters"])
    )


@dataclass(frozen=True, slots=True)
class AiMirrorResult:
    verdicts: int
    usage: int
    disagreements: int
    skipped: int
    runs: int = 0


def import_ai(
    conn, verdicts_path: Path, usage_path: Path, disagreements_path: Path,
    runs_path: Path | None = None,
) -> AiMirrorResult:
    """Validate the AI exports, then replace the mirror tables in one transaction. Without
    `runs_path` the runs mirror is emptied too: the four tables travel together."""
    v_rows = read_export(verdicts_path)
    u_rows = read_export(usage_path)
    d_rows = read_export(disagreements_path)
    r_rows = read_export(runs_path) if runs_path else []
    verdicts = [r for r in v_rows if valid_ai_verdict(r)]
    usage = [r for r in u_rows if valid_ai_usage(r)]
    disagreements = [r for r in d_rows if valid_disagreement(r)]
    runs = [r for r in r_rows if valid_ai_run(r)]
    AiRepository(conn).replace_all(verdicts, usage, disagreements, runs)
    return AiMirrorResult(
        verdicts=len(verdicts), usage=len(usage), disagreements=len(disagreements),
        skipped=len(v_rows) + len(u_rows) + len(d_rows) + len(r_rows)
        - len(verdicts) - len(usage) - len(disagreements) - len(runs),
        runs=len(runs),
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
