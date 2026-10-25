"""The Worker config: ./site as static assets, the Worker only on /api/*, one D1 binding.

The Access identifiers are Worker secrets, never config; site/ and .dev.vars are never committed.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def _config() -> dict:
    # wrangler.jsonc allows comments; ours are whole-line `//` comments only.
    text = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
    return json.loads("\n".join(lines))


def test_assets_are_served_first_and_the_worker_only_runs_on_the_api():
    cfg = _config()
    assert cfg["name"] == "job-match"
    assert cfg["main"] == "worker/src/index.js"
    assert (ROOT / cfg["main"]).is_file()
    assert cfg["assets"]["directory"] == "./site"
    assert cfg["assets"]["binding"] == "ASSETS"
    assert cfg["assets"]["run_worker_first"] == ["/api/*"]
    assert "compatibility_date" in cfg


def test_one_d1_database_with_the_repo_migrations():
    (db,) = _config()["d1_databases"]
    assert db["binding"] == "DB"  # the Worker reads env.DB
    assert db["database_name"] == "job-match"
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                        db["database_id"])
    assert set(db["database_id"]) != {"0", "-"}  # not the placeholder
    # `wrangler dev` must never reach the production D1.
    assert "remote" not in db
    assert db["migrations_dir"] == "worker/migrations"
    assert (ROOT / db["migrations_dir"] / "0001_tracking.sql").is_file()


def test_access_identifiers_are_secrets_not_config():
    text = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    cfg = _config()
    # `vars` carries plain knobs only (the AI cap): never an Access identifier nor a key.
    for key, value in cfg.get("vars", {}).items():
        assert key.startswith("AI_"), key
        assert not key.startswith("CF_ACCESS") and "KEY" not in key and "SECRET" not in key
        assert isinstance(value, str) and "sk-" not in value
    assert "cloudflareaccess.com" not in text


def test_the_ai_rerank_has_two_crons_a_cap_and_the_workers_ai_binding():
    cfg = _config()
    assert cfg["triggers"]["crons"] == ["30 7 * * *", "30 9 * * *"]
    assert cfg["vars"]["AI_DAILY_LIMIT"].isdigit()
    assert cfg["ai"] == {"binding": "AI"}


def test_site_and_deploy_tooling_are_gitignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/site/" in lines
    assert ".wrangler/" in lines
    assert ".dev.vars" in lines
