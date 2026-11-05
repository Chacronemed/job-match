"""Guard the job split of .github/workflows/ci.yml (no live CI involved)."""
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> dict:
    return next(s for s in _wf()["jobs"][job]["steps"] if s.get("name") == name)


def _uses(job: str) -> list[str]:
    return [s.get("uses", "") for s in _wf()["jobs"][job]["steps"]]


def test_check_names_are_the_ones_the_main_ruleset_requires():
    jobs = _wf()["jobs"]
    assert {k: v["name"] for k, v in jobs.items()} == {
        "fast": "fast", "changes": "changes", "browser-worker": "browser-worker",
    }


def test_triggers_every_push_and_pull_requests_to_main():
    triggers = _wf().get("on", _wf().get(True))
    assert triggers["push"] is None  # every branch
    assert triggers["pull_request"] == {"branches": ["main"]}


def test_fast_lints_and_runs_the_unmarked_tests_in_parallel_without_node_or_chromium():
    assert _step("fast", "Lint")["run"] == "ruff check ."
    assert _step("fast", "Test")["run"] == 'pytest -q -n auto -m "not browser and not worker"'
    assert "if" not in _wf()["jobs"]["fast"]
    # write_site needs worker/node_modules (pdf-lib, fontkit, fflate), installed before pytest
    steps = _wf()["jobs"]["fast"]["steps"]
    names = [s.get("name") or s.get("uses") for s in steps]
    node = next(s for s in steps if s.get("uses", "").startswith("actions/setup-node"))
    assert node["with"]["cache"] == "npm"
    assert node["with"]["cache-dependency-path"] == "worker/package-lock.json"
    assert _step("fast", "Install Worker dependencies")["run"] == "npm ci --prefix worker"
    assert names.index("Install Worker dependencies") < names.index("Test")
    assert all("playwright" not in str(s.get("run", "")) for s in steps)
    python = next(s for s in _wf()["jobs"]["fast"]["steps"]
                  if s.get("uses", "").startswith("actions/setup-python"))
    assert python["with"]["cache"] == "pip"


def test_browser_worker_runs_the_marked_tests_on_prs_and_main_when_its_paths_changed():
    job = _wf()["jobs"]["browser-worker"]
    assert job["needs"] == "changes"
    assert job["if"] == "needs.changes.outputs.browser_worker == 'true'"
    assert _wf()["jobs"]["changes"]["if"] == (
        "github.event_name == 'pull_request' || github.ref == 'refs/heads/main'"
    )
    assert _step("browser-worker", "Test")["run"] == 'pytest -q -n auto -m "browser or worker"'

    script = _step("changes", "Changed paths")["run"]
    for path in ("src/job_match/dashboard/", "worker/", "tests/unit/browser/",
                 r"\.github/workflows/"):
        assert path in script, path
    assert "${{" not in script  # refs come through env
    assert '"(no base)"' in script  # nothing to diff against: run


def test_browser_worker_caches_npm_and_the_playwright_browsers_by_version():
    node = next(s for s in _wf()["jobs"]["browser-worker"]["steps"]
                if s.get("uses", "").startswith("actions/setup-node"))
    assert node["with"]["cache"] == "npm"
    assert node["with"]["cache-dependency-path"] == "worker/package-lock.json"

    cache = _step("browser-worker", "Cache Playwright browsers")
    assert cache["with"]["path"] == "~/.cache/ms-playwright"
    assert "steps.pw.outputs.version" in cache["with"]["key"]
    assert "pip show playwright" in _step("browser-worker", "Playwright version")["run"]

    full = _step("browser-worker", "Install Chromium for Playwright")
    deps = _step("browser-worker", "Install Chromium system dependencies")
    assert full["if"] == "steps.pw-cache.outputs.cache-hit != 'true'"
    assert deps["if"] == "steps.pw-cache.outputs.cache-hit == 'true'"


def test_main_runs_are_never_cancelled():
    assert _wf()["concurrency"]["cancel-in-progress"] == "${{ github.ref != 'refs/heads/main' }}"


def test_the_two_markers_are_registered():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = cfg["tool"]["pytest"]["ini_options"]["markers"]
    assert {m.split(":")[0] for m in markers} == {"browser", "worker"}
    assert any(d.startswith("pytest-xdist") for d in cfg["project"]["optional-dependencies"]["dev"])
