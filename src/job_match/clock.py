"""The one place production code reads the clock.

`now()` is `datetime.now(UTC)`, unless `JOB_MATCH_FAKE_NOW` holds an ISO 8601 instant: then
every call returns that instant. The variable is a test hook (the suite re-runs itself with
the clock moved 90 days ahead to prove no test depends on the day it runs); it is never set
in CI workflows nor in production. Pipeline entry points also take an explicit `now=` so a
test can pin the clock without touching the environment.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

FAKE_NOW_ENV = "JOB_MATCH_FAKE_NOW"


def now() -> datetime:
    """Current UTC instant, or the frozen one from `JOB_MATCH_FAKE_NOW`."""
    fake = os.environ.get(FAKE_NOW_ENV)
    if fake:
        parsed = datetime.fromisoformat(fake)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)
