"""The Worker (worker/src/ai.js, wrangler.jsonc `vars`) and settings.yaml must agree on the AI
rerank constants: the Python report reads settings.yaml, the cron reads the var."""
import json
import re
from pathlib import Path

from job_match.config.loader import load_settings

ROOT = Path(__file__).resolve().parents[3]
AI_JS = (ROOT / "worker" / "src" / "ai.js").read_text(encoding="utf-8")
WRANGLER = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
WRANGLER_CFG = json.loads(
    "\n".join(ln for ln in WRANGLER.splitlines() if not ln.strip().startswith("//"))
)


def _js_const(name):
    m = re.search(rf"export const {name} = (.+?);", AI_JS)
    assert m, name
    return m.group(1).strip().strip('"')


def test_settings_and_worker_agree():
    ai = load_settings(ROOT / "config" / "settings.yaml").ai
    # The cap the Worker runs with is the wrangler var; the JS constant is only its fallback.
    assert int(WRANGLER_CFG["vars"]["AI_DAILY_LIMIT"]) == ai.daily_limit
    assert int(_js_const("DAILY_LIMIT")) == ai.daily_limit
    assert int(_js_const("DISAGREEMENT_GAP")) == ai.disagreement_gap
    assert _js_const("PROMPT_VERSION") == ai.prompt_version


def test_the_worker_uses_the_documented_model_and_api_version():
    assert _js_const("ANTHROPIC_MODEL") == "claude-haiku-5-5"
    assert _js_const("ANTHROPIC_VERSION") == "2026-10-21"
    assert "@cf/meta/llama-3.3-70b-instruct-fp8-fast" in AI_JS


def test_the_crons_run_after_the_daily_run_and_workers_ai_is_bound():
    daily = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert 'cron: "0 7 * * *"' in daily
    assert WRANGLER_CFG["triggers"]["crons"] == ["30 7 * * *", "30 9 * * *"]
    assert '"binding": "AI"' in WRANGLER
    assert "ANTHROPIC" not in json.dumps(WRANGLER_CFG)  # the key stays a secret, not a var
    assert "sk-ant" not in WRANGLER


def test_the_worker_never_logs_a_prompt_a_key_or_an_answer():
    assert "console." not in AI_JS
    for leak in ("ANTHROPIC_API_KEY", "x-api-key"):
        assert AI_JS.count(leak) <= 2, leak  # read once, sent once
