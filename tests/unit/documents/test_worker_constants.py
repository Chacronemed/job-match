"""worker/src/documents.js, wrangler.jsonc and settings.yaml `documents:` must agree (ADR 0017):
the Worker generates, the Python side validates the master and reports the cost."""
import json
import re
from pathlib import Path

from job_match.ai.report import PRICES_PER_M
from job_match.config.loader import load_settings

ROOT = Path(__file__).resolve().parents[3]
DOCS_JS = (ROOT / "worker" / "src" / "documents.js").read_text(encoding="utf-8")
WRANGLER = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
WRANGLER_CFG = json.loads(
    "\n".join(ln for ln in WRANGLER.splitlines() if not ln.strip().startswith("//"))
)


def _js_const(name):
    m = re.search(rf"export const {name} = (.+?);", DOCS_JS)
    assert m, name
    return m.group(1).strip().strip('"')


def test_settings_wrangler_and_worker_agree():
    d = load_settings(ROOT / "config" / "settings.yaml").documents
    assert _js_const("DOCUMENTS_MODEL") == d.model == "claude-sonnet-5-5"
    assert _js_const("DOCUMENTS_PROMPT_VERSION") == d.prompt_version
    assert int(_js_const("MONTHLY_BUDGET_USD")) == d.monthly_budget_usd
    assert int(WRANGLER_CFG["vars"]["AI_DOCUMENTS_MONTHLY_USD"]) == d.monthly_budget_usd
    assert float(_js_const("DEFAULT_ESTIMATE_PER_DOCUMENT_USD")) == d.default_estimate_per_document_usd
    assert int(_js_const("BATCH_SIZE")) == d.batch_size
    assert int(_js_const("MAX_BULLETS")) == d.max_bullets
    assert int(_js_const("MAX_SKILLS")) == d.max_skills
    assert int(_js_const("MAX_BULLET_CHARS")) == d.max_bullet_chars
    assert int(_js_const("MAX_PROFILE_CHARS")) == d.max_profile_chars
    assert int(_js_const("MAX_LETTER_CHARS")) == d.max_letter_chars
    assert json.loads(_js_const("FORBIDDEN_PHRASES")) == d.forbidden_phrases


def test_the_prices_and_the_cron_match():
    price_in, price_out = PRICES_PER_M[_js_const("DOCUMENTS_MODEL")]
    assert float(_js_const("PRICE_IN_PER_M")) == price_in
    assert float(_js_const("PRICE_OUT_PER_M")) == price_out
    assert _js_const("DOCUMENTS_CRON") in WRANGLER_CFG["triggers"]["crons"]
    assert _js_const("ANTHROPIC_VERSION") == "2026-10-21"


def test_the_worker_never_logs_and_reads_the_key_once():
    assert "console." not in DOCS_JS
    for leak in ("ANTHROPIC_API_KEY", "x-api-key"):
        assert DOCS_JS.count(leak) <= 2, leak
    assert "contact.json" not in DOCS_JS.split("export async function runDocuments")[1]
