"""Runs the Node tests: the Worker API (auth, origin, validation, D1) and the dashboard's
tracking logic. They need Node 22+ and nothing else (no npm install).

Skipped only on a machine without Node; in CI (`CI` set, Node installed by ci.yml) a missing
Node is a failure, never a silent skip.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
TESTS = sorted((ROOT / "worker" / "test").glob("*.test.mjs"))


def test_node_test_files_exist():
    names = {p.name for p in TESTS}
    assert {"api.test.mjs", "dashboard-tracking.test.mjs", "triage.test.mjs"} <= names


def test_worker_and_dashboard_tracking_node_tests_pass():
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node is required in CI (actions/setup-node in ci.yml)")
        pytest.skip("Node is not installed")
    result = subprocess.run(
        [node, "--experimental-sqlite", "--no-warnings", "--test", *map(str, TESTS)],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
    passed = int(result.stdout.split("# pass ", 1)[1].split()[0])
    assert passed >= 90  # the suites really ran
