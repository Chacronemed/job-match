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
    return [_steps()[_index(n)] for n in ("Build dashboard", "Deploy dashboard")]


_SITE_IF = ("always() && env.RUN_SITE == 'true' && steps.restore.outcome == 'success' && "
            "(steps.wal.outcome == 'success' || env.STAGE == 'site')")


def test_dashboard_steps_run_after_the_db_push_and_cannot_block_it():
    push = _index("Push DB to data repo")
    assert _index("Send digest") < push
    assert push < _index("Set up Node") < _index("Install Worker dependencies")
    assert _index("Install Worker dependencies") < _index("Build dashboard")
    assert _index("Build dashboard") < _index("Deploy dashboard")
    for name in ("Set up Node", "Install Worker dependencies", "Build dashboard",
                 "Deploy dashboard"):
        step = _steps()[_index(name)]
        assert step.get("continue-on-error") is True, name
        # run even if the digest failed, never on a broken DB; alone, on the restored one
        assert step["if"] == _SITE_IF, name


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


# ---------------------------------------------------------------------------
# DB snapshot in the data repo: gunzip in, VACUUM, gzip + orphan force-push out
# ---------------------------------------------------------------------------

_SNAPSHOT = "python -m job_match.persistence.snapshot"


def test_db_round_trip_step_order():
    clone = _index("Clone data repo")
    restore = _index("Restore DB")
    vacuum = _index("WAL checkpoint and VACUUM")
    push = _index("Push DB to data repo")
    assert clone < restore < _index("Run pipeline") < vacuum < push
    # every writer runs before the VACUUM, so the pushed file is the compacted one
    for writer in ("Run funding pipeline", "Reprocess jobs", "Reprocess funding articles",
                   "Export tracking"):
        assert _index(writer) < vacuum


def test_restore_step_gunzips_through_the_snapshot_module():
    step = _steps()[_index("Restore DB")]
    assert step["run"].strip() == (
        f"{_SNAPSHOT} restore --repo data-repo --db data/jobs.sqlite"
    )


def test_push_step_publishes_through_the_snapshot_module_after_a_successful_vacuum():
    step = _steps()[_index("Push DB to data repo")]
    assert step["run"].strip() == (
        f"{_SNAPSHOT} publish --repo data-repo --db data/jobs.sqlite"
    )
    assert step["if"] == "always() && steps.wal.outcome == 'success'"
    # the size guard must turn the step red: never swallowed
    assert step.get("continue-on-error") is not True


def test_vacuum_step_checkpoints_then_vacuums():
    script = _steps()[_index("WAL checkpoint and VACUUM")]["run"]
    assert script.index("wal_checkpoint(TRUNCATE)") < script.index('"VACUUM"')


def test_no_step_copies_the_plain_db_into_the_data_repo_any_more():
    for step in _steps():
        run = step.get("run", "")
        assert "data-repo/jobs.sqlite " not in run + " "
        assert "git push" not in run  # only the snapshot module pushes, and it force-pushes



# ---------------------------------------------------------------------------
# Application tracking: D1 -> read-only mirror in the jobs DB, before the digest
# ---------------------------------------------------------------------------

def test_tracking_steps_order_restore_migrate_export_then_pipeline():
    # The mirror lands before the jobs pipeline: the run merges the skill overrides into the
    # profile, and the digest further down still reads today's statuses.
    migrate = _index("Apply D1 migrations")
    export = _index("Export tracking")
    assert _index("Restore DB") < migrate < export < _index("Run pipeline")
    # The Worker's PDF/DOCX libraries (ADR 0017) are only needed by the deploy: installed
    # there, quietly, and never blocking the run.
    deps = _steps()[_index("Install Worker dependencies")]
    assert _index("Set up Node") < _index("Install Worker dependencies") < _index(
        "Deploy dashboard"
    )
    assert deps["run"].strip() == "npm ci --prefix worker > /dev/null"
    assert deps.get("continue-on-error") is True
    for later in ("Reprocess jobs", "Reprocess funding articles", "WAL checkpoint and VACUUM",
                  "Send digest", "Push DB to data repo", "Deploy dashboard"):
        assert export < _index(later), later


def test_override_reprocess_runs_only_when_the_overrides_changed():
    step = _steps()[_index("Reprocess for skill overrides")]
    assert _index("Export tracking") < _index("Reprocess for skill overrides") < _index(
        "Run pipeline"
    )
    assert step["if"] == (
        "${{ env.RUN_JOBS == 'true' && steps.tracking.outputs.overrides_changed == 'true' }}"
    )
    assert step.get("continue-on-error") is True
    assert 'job-match reprocess --since "$since" --limit 0' in step["run"]
    assert "jobs.max_age_days" in step["run"]  # the cut-off comes from settings.yaml
    assert "${{" not in step["run"]


def test_tracking_steps_cannot_block_the_digest_or_the_push():
    for name in ("Apply D1 migrations", "Export tracking"):
        step = _steps()[_index(name)]
        assert step.get("continue-on-error") is True, name
        # a stage guard only: never a condition on an earlier step's outcome
        assert "steps." not in step["if"], name
    assert _steps()[_index("Export tracking")]["if"] == "env.RUN_JOBS == 'true'"
    assert _steps()[_index("Apply D1 migrations")]["if"] == (
        "env.RUN_JOBS == 'true' || env.RUN_SITE == 'true'"
    )


def test_tracking_steps_use_the_cloudflare_secrets_and_print_nothing_from_d1():
    for name in ("Apply D1 migrations", "Export tracking"):
        step = _steps()[_index(name)]
        assert step["env"]["CLOUDFLARE_API_TOKEN"] == "${{ secrets.CLOUDFLARE_API_TOKEN }}"
        assert step["env"]["CLOUDFLARE_ACCOUNT_ID"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
        assert "${{" not in step["run"]
    assert "> /dev/null" in _steps()[_index("Apply D1 migrations")]["run"]

    export = _steps()[_index("Export tracking")]["run"]
    assert "set -euo pipefail" in export
    assert "umask 077" in export
    assert "trap 'rm -rf \"$dir\"' EXIT" in export
    # each query's JSON goes to a file, never to the log
    assert export.count('> "$dir/') == 7
    assert "--json" in export and "--remote" in export
    for leak in ("cat ", "echo", "tee", "head", "jq", "upload"):
        assert leak not in export, leak
    assert ('job-match tracking import --applications "$dir/applications.json" '
            '--decisions "$dir/decisions.json" '
            '--skill-overrides "$dir/skill_overrides.json" '
            '--ai-verdicts "$dir/ai_verdicts.json" --ai-usage "$dir/ai_usage.json" '
            '--disagreements "$dir/disagreements.json" --ai-runs "$dir/ai_runs.json"') in export


def test_export_selects_exactly_the_mirrored_columns():
    export = _steps()[_index("Export tracking")]["run"]
    assert ("SELECT job_key, status, applied_at, follow_up_at, note, cv_url, updated_at, "
            "reactivated_at FROM applications") in export
    assert "SELECT id, job_key, label, score_at_decision, created_at FROM decisions" in export
    assert "SELECT skill, created_at FROM skill_overrides" in export
    # The AI rerank mirror (ADR 0016): the Worker's three tables, whole.
    assert ("SELECT id, job_key, hash, provider, model, prompt_version, score, level, reasons, "
            "red_flags, created_at FROM ai_verdicts") in export
    assert "SELECT day, provider, model, calls, tokens_in, tokens_out FROM ai_usage" in export
    assert ("SELECT id, job_key, hash, python_score, python_section, ai_score, ai_level, kind, "
            "created_at FROM disagreements") in export
    assert ("SELECT id, started_at, finished_at, outcome, http_status, provider, counters "
            "FROM ai_runs") in export


def test_check_sources_runs_after_the_pipeline_with_smtp_and_cannot_block_anything():
    """Item 4 (2026-11-04): the silent-source alert, between the run and the funding step."""
    step = _steps()[_index("Check sources")]
    assert _index("Run pipeline") < _index("Check sources") < _index("Run funding pipeline")
    assert step["run"].strip() == "job-match ops check-sources --days 3"
    assert step.get("continue-on-error") is True
    assert "steps.pipeline.outcome != 'skipped'" in step["if"]
    smtp = {"SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO"}
    assert set(step["env"]) == smtp
    assert step["env"]["SMTP_PORT"] == "${{ vars.SMTP_PORT }}"


# ---------------------------------------------------------------------------
# Stages (workflow_dispatch input `stage`): every step's `if` evaluated per stage by a tiny
# GitHub-expression evaluator, all steps succeeding unless told otherwise.
# ---------------------------------------------------------------------------

class _NS(dict):
    def __getattr__(self, key):
        return self.get(key, "")


def _value(expr: str, ctx: dict):
    expr = expr.strip()
    if expr.startswith("${{"):
        expr = expr[3:-2]
    py = expr.replace("&&", " and ").replace("||", " or ")
    return eval(py, {"__builtins__": {}}, ctx)  # noqa: S307 - our own workflow file


def _eval(expr: str, ctx: dict) -> bool:
    return bool(_value(expr, ctx))


def _simulate(stage: str | None, fail: frozenset[str] = frozenset()) -> list[str]:
    """Names of the steps that run, in order, for `stage` (None: the cron, no inputs)."""
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = wf["jobs"]["run"]
    inputs = _NS(stage=stage or "", reprocess_since="", reprocess_scope="jobs")
    funcs = {
        "contains": lambda seq, x: x in seq,
        "fromJSON": __import__("json").loads,
        "always": lambda: True,
    }
    github = _NS(event_name="workflow_dispatch" if stage else "schedule")
    env = _NS()
    for key, value in job["env"].items():
        raw = _value(value, {**funcs, "inputs": inputs, "github": github})
        # GitHub turns an expression's value into a string: booleans as "true" / "false"
        env[key] = ("true" if raw else "false") if isinstance(raw, bool) else raw
    steps, ran, failed = _NS(), [], False
    for step in job["steps"]:
        cond = step.get("if")
        ctx = {**funcs, "env": env, "steps": steps, "github": github, "inputs": inputs}
        if cond is None:
            go = not failed
        else:
            go = (_eval(cond, ctx)) and ("always()" in cond or not failed)
        name = step.get("name") or step.get("uses")
        outcome = "skipped"
        if go:
            ran.append(name)
            outcome = "failure" if name in fail else "success"
            if outcome == "failure" and step.get("continue-on-error") is not True:
                failed = True
        if "id" in step:
            steps[step["id"]] = _NS(outcome=outcome, outputs=_NS())
    return ran


_COMMON = ("Install", "Restore profile", "Set up data-repo SSH", "Clone data repo", "Restore DB",
           "Stage summary")
_JOBS = ("Export tracking", "Run pipeline", "Check sources")
_FUNDING = ("Run funding pipeline",)
_SNAPSHOT_STEPS = ("WAL checkpoint and VACUUM", "Send digest", "Push DB to data repo")
_SITE = ("Set up Node", "Install Worker dependencies", "Build dashboard", "Deploy dashboard")


def test_stage_input_is_a_choice_defaulting_to_all():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))
    inp = triggers["workflow_dispatch"]["inputs"]["stage"]
    assert inp["type"] == "choice" and inp["required"] is False
    assert inp["default"] == "all"
    assert inp["options"] == ["all", "jobs", "funding", "site"]
    assert triggers["schedule"]  # the cron, which runs all (below)


def test_one_daily_run_at_a_time_and_never_cancelled():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert wf["concurrency"] == {"group": "daily", "cancel-in-progress": False}
    assert list(wf["jobs"]) == ["run"]  # one job: the stages share the restored DB


def test_cron_runs_the_same_steps_as_all():
    assert _simulate(None) == _simulate("all")


def test_all_runs_jobs_then_funding_then_site():
    ran = _simulate("all")
    for name in _COMMON + _JOBS + _FUNDING + _SNAPSHOT_STEPS + _SITE + ("Apply D1 migrations",):
        assert name in ran, name
    assert ran.index("Run pipeline") < ran.index("Run funding pipeline")
    assert ran.index("Run funding pipeline") < ran.index("Push DB to data repo")
    assert ran.index("Push DB to data repo") < ran.index("Set up Node")
    assert ran.index("Deploy dashboard") < ran.index("Stage summary") == len(ran) - 1
    # manual-only steps stay off without their inputs
    assert "Reprocess jobs" not in ran and "Reprocess funding articles" not in ran


def test_jobs_stage_collects_scores_and_snapshots_without_funding_or_site():
    ran = _simulate("jobs")
    for name in _COMMON + _JOBS + _SNAPSHOT_STEPS + ("Apply D1 migrations",):
        assert name in ran, name
    for name in _FUNDING + _SITE:
        assert name not in ran, name


def test_funding_stage_runs_funding_and_snapshots_only():
    ran = _simulate("funding")
    for name in _COMMON + _FUNDING + _SNAPSHOT_STEPS:
        assert name in ran, name
    for name in _JOBS + _SITE + ("Apply D1 migrations",):
        assert name not in ran, name


def test_site_stage_rebuilds_from_the_snapshot_and_writes_nothing_back():
    ran = _simulate("site")
    for name in _COMMON + _SITE + ("Apply D1 migrations",):
        assert name in ran, name
    for name in _JOBS + _FUNDING + _SNAPSHOT_STEPS:
        assert name not in ran, name


def test_heavy_node_setup_runs_only_with_the_site_stage():
    for stage in ("jobs", "funding"):
        ran = _simulate(stage)
        assert "Set up Node" not in ran and "Install Worker dependencies" not in ran, stage


def test_a_failed_jobs_pipeline_still_blocks_the_push_and_the_site_in_all():
    ran = _simulate("all", fail=frozenset({"Run pipeline"}))
    assert "WAL checkpoint and VACUUM" not in ran
    assert "Push DB to data repo" not in ran
    assert "Build dashboard" not in ran and "Deploy dashboard" not in ran
    assert ran[-1] == "Stage summary"


def test_a_failed_digest_still_pushes_and_deploys():
    ran = _simulate("all", fail=frozenset({"Send digest"}))
    assert "Push DB to data repo" in ran and "Deploy dashboard" in ran


def test_a_failed_restore_skips_the_site_stage():
    ran = _simulate("site", fail=frozenset({"Restore DB"}))
    assert "Build dashboard" not in ran and "Deploy dashboard" not in ran
    assert ran[-1] == "Stage summary"


def test_stage_summary_lists_played_and_skipped_stages_without_interpolation():
    step = _steps()[_index("Stage summary")]
    assert step["if"] == "always()"
    assert "${{" not in step["run"]
    for stage in ("jobs:$RUN_JOBS", "funding:$RUN_FUNDING", "site:$RUN_SITE"):
        assert stage in step["run"]
    assert "played" in step["run"] and "skipped" in step["run"]
    assert '>> "$GITHUB_STEP_SUMMARY"' in step["run"]
