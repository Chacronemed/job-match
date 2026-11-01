"""`job_match.clock`: the only clock production code reads, and the proof that no test depends
on the day it runs: the suite is re-run with the clock moved 90 days ahead.
"""
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match import clock

ROOT = Path(__file__).parent.parent.parent


def test_now_is_utc_and_current(monkeypatch):
    monkeypatch.delenv(clock.FAKE_NOW_ENV, raising=False)
    t = clock.now()
    assert t.tzinfo is UTC
    assert abs((datetime.now(UTC) - t).total_seconds()) < 5


def test_fake_now_freezes_the_clock(monkeypatch):
    monkeypatch.setenv(clock.FAKE_NOW_ENV, "2027-03-04T05:06:07+00:00")
    assert clock.now() == datetime(2027, 3, 4, 5, 6, 7, tzinfo=UTC)
    monkeypatch.setenv(clock.FAKE_NOW_ENV, "2027-03-04T05:06:07")  # naive means UTC
    assert clock.now() == datetime(2027, 3, 4, 5, 6, 7, tzinfo=UTC)


def test_frozen_clock_fixture_pins_the_clock(frozen_clock):
    pinned = frozen_clock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    assert clock.now() == pinned


@pytest.mark.skipif(
    bool(os.environ.get(clock.FAKE_NOW_ENV)), reason="already running under a shifted clock"
)
def test_the_suite_passes_with_the_clock_90_days_ahead():
    """Re-runs tests/unit with JOB_MATCH_FAKE_NOW = today + 90 days.

    Any test that quietly relies on the real date (a fixture row aging out of a window, a
    cut-off computed from today) fails here. The Node suite is left out: it never reads this
    clock, and running it twice buys nothing. Plain `pytest`, never `python -m pytest`, so the
    re-run sees the same `sys.path` as CI.
    """
    pytest_bin = Path(sys.executable).with_name("pytest" + (".exe" if os.name == "nt" else ""))
    if not pytest_bin.exists():
        pytest_bin = shutil.which("pytest")
    assert pytest_bin, "pytest executable not found next to the interpreter"
    ahead = (datetime.now(UTC) + timedelta(days=90)).replace(microsecond=0)
    env = {**os.environ, clock.FAKE_NOW_ENV: ahead.isoformat()}
    result = subprocess.run(
        [str(pytest_bin), "-q", "-p", "no:cacheprovider", "tests/unit",
         "--deselect", "tests/unit/test_worker_js.py"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
