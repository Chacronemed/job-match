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
    # since M13 the date is shared with the jobs reprocess, so the scope must select it
    assert "inputs.reprocess_scope == 'funding'" in step["if"]
    assert "inputs.reprocess_scope == 'both'" in step["if"]
    # the input is passed via env, never interpolated into the shell script
    assert step["env"]["REPROCESS_SINCE"] == "${{ inputs.reprocess_since }}"
    assert step["run"].strip() == 'job-match funding reprocess --since "$REPROCESS_SINCE"'
    assert "${{" not in step["run"]


def test_reprocess_scope_input_is_a_choice_defaulting_to_jobs():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))
    inp = triggers["workflow_dispatch"]["inputs"]["reprocess_scope"]

    assert inp["required"] is False and inp["type"] == "choice"
    assert inp["default"] == "jobs"
    assert inp["options"] == ["jobs", "funding", "both"]


def test_jobs_reprocess_runs_before_the_checkpoint_and_the_digest():
    """Re-admitted jobs must reach today's digest, and the cleaned DB must be the pushed one."""
    jobs_rep = _index("Reprocess jobs")

    assert _index("Run pipeline") < jobs_rep
    assert jobs_rep < _index("Reprocess funding articles")
    assert jobs_rep < _index("WAL checkpoint and VACUUM")
    assert jobs_rep < _index("Send digest")


def test_jobs_reprocess_is_manual_scoped_and_cannot_block_the_digest():
    step = _steps()[_index("Reprocess jobs")]
    cond = step["if"]

    assert "workflow_dispatch" in cond
    assert "inputs.reprocess_since != ''" in cond
    assert "inputs.reprocess_scope == 'jobs'" in cond
    assert "inputs.reprocess_scope == 'both'" in cond
    assert step.get("continue-on-error") is True


def test_jobs_reprocess_takes_the_date_by_env_and_logs_counts_only():
    step = _steps()[_index("Reprocess jobs")]

    assert step["env"]["REPROCESS_SINCE"] == "${{ inputs.reprocess_since }}"
    assert step["run"].strip() == 'job-match reprocess --since "$REPROCESS_SINCE" --limit 0'
    assert "${{" not in step["run"]  # never interpolated into the shell script
    assert "--limit 0" in step["run"]  # public log: aggregate counts, no job titles


# ---------------------------------------------------------------------------
# Dashboard build + deploy (M19). The repo is public: site/ is never an artifact and the
# Worker URL never reaches the log.
# ---------------------------------------------------------------------------

def _dashboard_steps() -> list[dict]:
    return [_steps()[_index(n)] for n in ("Build dashboard", "Set up Node", "Deploy dashboard")]


def test_dashboard_steps_run_after_the_db_push_and_cannot_block_it():
    push = _index("Push DB to data repo")
    assert _index("Send digest") < push
    assert push < _index("Build dashboard") < _index("Set up Node") < _index("Deploy dashboard")
    for step in _dashboard_steps():
        assert step.get("continue-on-error") is True
        # same guard as the push: run even if the digest failed, never on a broken DB
        assert step["if"] == "always() && steps.wal.outcome == 'success'"


def test_build_step_prints_counts_only():
    build = _steps()[_index("Build dashboard")]
    assert build["run"].strip() == "job-match dashboard --out site"
    assert "env" not in build


def test_deploy_step_uses_both_cloudflare_secrets_and_hides_the_worker_url():
    deploy = _steps()[_index("Deploy dashboard")]
    assert deploy["env"]["CLOUDFLARE_API_TOKEN"] == "${{ secrets.CLOUDFLARE_API_TOKEN }}"
    assert deploy["env"]["CLOUDFLARE_ACCOUNT_ID"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    assert "${{" not in deploy["run"]
    assert "wrangler" in deploy["run"] and "deploy > /dev/null" in deploy["run"]
    assert "2>&1" not in deploy["run"]  # stderr stays readable for a failed deploy


def test_site_is_never_uploaded_or_printed():
    for step in _steps():
        assert not str(step.get("uses", "")).startswith("actions/upload-artifact")
        run = str(step.get("run", ""))
        assert "cat site" not in run and "ls site" not in run
        assert "upload" not in run.lower()
