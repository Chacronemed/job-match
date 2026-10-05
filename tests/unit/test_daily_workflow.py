"""Guard the step order of .github/workflows/daily.yml (no live CI involved)."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parent.parent.parent / ".github" / "workflows" / "daily.yml"


def _steps() -> list[dict]:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return wf["jobs"]["run"]["steps"]


def _index(name: str) -> int:
    return next(i for i, s in enumerate(_steps()) if s.get("name") == name)


def test_funding_runs_after_jobs_and_before_checkpoint_and_digest():
    funding = _index("Run funding pipeline")
    assert _index("Run pipeline") < funding < _index("WAL checkpoint and VACUUM")
    assert funding < _index("Send digest")


def test_funding_step_runs_funding_command_without_secrets_and_cannot_block_digest():
    step = _steps()[_index("Run funding pipeline")]
    assert step["run"].strip() == "job-match funding run"
    assert step.get("continue-on-error") is True
    assert "env" not in step  # RSS needs no secrets
