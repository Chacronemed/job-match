"""D1 and R2 through the local `wrangler login` (like `cv push`), for `job-match apply`.

Read: the latest ready documents version of an offer and its content.json. Write (`--sent`
only, a command I type): the application becomes « Envoyée » with its date, its follow-up
date and the documents version sent. The job key is checked against JOB_KEY_RE before it
enters any SQL text (letters, digits and `._:-` only), dates are ISO days. Output of wrangler
is parsed, never printed: content.json holds my documents.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

from job_match.documents.push import BUCKET, WRANGLER
from job_match.tracking.constants import JOB_KEY_RE

DATABASE = "job-match"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")


class RemoteError(RuntimeError):
    pass


def _check_key(key: str) -> str:
    if not JOB_KEY_RE.match(key or ""):
        raise RemoteError(f"invalid job key: {key!r}")
    return key


def _run(cmd: list[str], run: Callable | None) -> subprocess.CompletedProcess:
    run = run or subprocess.run
    result = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                 shell=sys.platform == "win32")
    if result.returncode != 0:
        reason = " ".join((result.stderr or "").split())[-300:]
        raise RemoteError(f"wrangler {cmd[3] if len(cmd) > 3 else ''}: exit {result.returncode}"
                          + (f" ({reason})" if reason else ""))
    return result


def d1(sql: str, run: Callable | None = None) -> list[dict]:
    """The rows of the last statement of a `wrangler d1 execute --remote --json` call."""
    out = _run([*WRANGLER, "d1", "execute", DATABASE, "--remote", "--json", "--command", sql],
               run).stdout
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RemoteError("wrangler d1 execute: not JSON") from exc
    if not isinstance(data, list) or not data or not isinstance(data[-1], dict):
        raise RemoteError("wrangler d1 execute: unexpected output")
    rows = data[-1].get("results")
    return rows if isinstance(rows, list) else []


def latest_ready_version(key: str, run: Callable | None = None) -> int | None:
    k = _check_key(key)
    rows = d1("SELECT MAX(version) AS v FROM documents WHERE job_key = "
              f"'{k}' AND status = 'ready'", run)
    v = rows[0].get("v") if rows else None
    return int(v) if isinstance(v, int) else None


def fetch_r2_json(object_key: str, run: Callable | None = None) -> dict | None:
    with tempfile.TemporaryDirectory(prefix="apply-") as tmp:
        path = Path(tmp) / "object.json"
        try:
            _run([*WRANGLER, "r2", "object", "get", f"{BUCKET}/{object_key}", "--file",
                  str(path), "--remote"], run)
        except RemoteError:
            return None
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def fetch_content(key: str, version: int, run: Callable | None = None) -> dict | None:
    return fetch_r2_json(f"docs/{_check_key(key)}/v{int(version)}/content.json", run)


def mark_sent(key: str, applied: date, follow_up: date, version: int | None,
              now_iso: str, run: Callable | None = None) -> None:
    """« Envoyée »: an existing applied date and follow-up date are kept (a second `--sent`
    changes nothing), the documents version is the latest ready one."""
    k = _check_key(key)
    a, f = applied.isoformat(), follow_up.isoformat()
    if not (_DAY.match(a) and _DAY.match(f)) or not re.match(r"^[\d:.TZ+-]{10,40}\Z", now_iso):
        raise RemoteError("bad date")
    sql = (
        "INSERT INTO applications (job_key, status, applied_at, follow_up_at, updated_at)"
        f" VALUES ('{k}', 'applied', '{a}', '{f}', '{now_iso}')"
        " ON CONFLICT(job_key) DO UPDATE SET status = 'applied',"
        " applied_at = COALESCE(applications.applied_at, excluded.applied_at),"
        " follow_up_at = COALESCE(applications.follow_up_at, excluded.follow_up_at),"
        " updated_at = excluded.updated_at;"
    )
    if version is not None:
        sql += (f" UPDATE applications SET sent_documents_version = {int(version)}"
                f" WHERE job_key = '{k}';")
    d1(sql, run)


def kept_applications(run: Callable | None = None) -> list[dict]:
    """The applications « À candidater », {job_key, status, updated_at}."""
    rows = d1("SELECT job_key, status, updated_at FROM applications"
              " WHERE status = 'to_apply' ORDER BY updated_at, job_key", run)
    return [r for r in rows if isinstance(r, dict) and JOB_KEY_RE.match(str(r.get("job_key")))]
