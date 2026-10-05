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


def test_reprocess_input_and_step_order():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses the bare key `on` as boolean True
    triggers = wf.get("on", wf.get(True))
    inp = triggers["workflow_dispatch"]["inputs"]["reprocess_since"]
    assert inp["required"] is False and inp["type"] == "string"

    step = _steps()[_index("Reprocess funding articles")]
    assert _index("Run funding pipeline") < _index("Reprocess funding articles")
    assert _index("Reprocess funding articles") < _index("WAL checkpoint and VACUUM")
    assert _index("Reprocess funding articles") < _index("Send digest")
    assert "workflow_dispatch" in step["if"] and "inputs.reprocess_since != ''" in step["if"]
    # the input is passed via env, never interpolated into the shell script
    assert step["env"]["REPROCESS_SINCE"] == "${{ inputs.reprocess_since }}"
    assert step["run"].strip() == 'job-match funding reprocess --since "$REPROCESS_SINCE"'
    assert "${{" not in step["run"]
