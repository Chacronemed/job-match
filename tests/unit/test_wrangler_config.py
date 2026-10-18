"""The Worker config serves ./site as static assets and nothing else; site/ is never committed."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_wrangler_config_is_assets_only_and_points_at_site():
    cfg = json.loads((ROOT / "wrangler.jsonc").read_text(encoding="utf-8"))
    assert cfg["name"] == "job-match"
    assert cfg["assets"]["directory"] == "./site"
    assert "main" not in cfg  # no Worker script: Access is the whole auth story
    assert "compatibility_date" in cfg


def test_site_and_deploy_tooling_are_gitignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/site/" in lines
    assert ".wrangler/" in lines
