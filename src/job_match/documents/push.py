"""Push the master CV and the contact sheet to the private R2 bucket, as JSON objects.

Through `npx wrangler r2 object put`: wrangler is already the tool this repo uses for D1
and the deploy, the local `wrangler login` is enough, and no S3 key pair has to exist
anywhere. The command is run by hand, never from a GitHub workflow: the content leaves this
machine for R2 and nowhere else. Output is object keys and sizes only.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

BUCKET = "job-match-docs"
MASTER_KEY = "master/cv_master.json"
CONTACT_KEY = "master/contact.json"
WRANGLER = ["npx", "--yes", "wrangler@4"]


class PushError(RuntimeError):
    pass


def push_objects(
    objects: dict[str, str],
    *,
    bucket: str = BUCKET,
    local: bool = False,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, int]:
    """Upload each `key -> JSON text`; returns `key -> bytes`. Raises PushError with
    wrangler's status (never its output, which could echo the object) on failure."""
    run = run or subprocess.run  # resolved at call time, so a test can patch subprocess.run
    sizes: dict[str, int] = {}
    tmp = Path(tempfile.mkdtemp(prefix="cv-push-"))
    try:
        for key, text in objects.items():
            path = tmp / key.replace("/", "_")
            data = text.encode("utf-8")
            path.write_bytes(data)
            cmd = [*WRANGLER, "r2", "object", "put", f"{bucket}/{key}", "--file", str(path),
                   "--content-type", "application/json"]
            cmd.append("--local" if local else "--remote")
            result = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         shell=sys.platform == "win32")
            if result.returncode != 0:
                # wrangler's stderr carries the reason (a missing bucket, no login), never the
                # object; its stdout is not shown.
                reason = " ".join((result.stderr or "").split())[-300:]
                raise PushError(f"wrangler r2 object put {key}: exit {result.returncode}"
                                + (f" ({reason})" if reason else ""))
            sizes[key] = len(data)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return sizes


def private_dir() -> Path:
    """Private directory: $JOB_MATCH_PRIVATE_DIR or ./private (gitignored)."""
    env = os.environ.get("JOB_MATCH_PRIVATE_DIR")
    return Path(env) if env else Path("private")
