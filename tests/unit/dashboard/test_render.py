"""The rendered page: external text can never become markup, and nothing of it is in the HTML."""
import json
import re

from job_match.dashboard.render import embed_json, render_index, write_site

_DATA_BLOCK = re.compile(
    r'<script type="application/json" id="data">(.*?)</script>', re.S
)
_EMPTY = {"generated_at": "2026-10-18T07:00:00+00:00", "thresholds": {}, "jobs": [],
          "leads": [], "runs": []}


def test_embed_json_escapes_every_angle_bracket_and_round_trips(dashboard_data):
    _, seed = dashboard_data
    data = {"t": seed.xss_title, "c": "Beta <b>Corp</b>", "n": 1, "u": "é"}
    out = embed_json(data)
    assert "<" not in out
    assert "\\u003c" in out
    assert json.loads(out) == data


def test_index_contains_no_job_text_and_the_data_block_parses_back(dashboard_data):
    data, seed = dashboard_data
    html = render_index(data)

    assert "alert(1)" not in html.replace("\\u003c", "<").split('id="data">')[0]
    assert "<img src=x" not in html
    assert "</script><script>alert" not in html
    assert "<!-- x -->" not in html
    # exactly one JSON block, and it still carries the title verbatim after parsing
    blocks = _DATA_BLOCK.findall(html)
    assert len(blocks) == 1
    parsed = json.loads(blocks[0])
    assert parsed == json.loads(json.dumps(data))
    assert seed.xss_title in [j["title"] for j in parsed["jobs"]]
    assert "Beta <b>Corp</b>" in [j["company"] for j in parsed["jobs"]]


def test_index_is_self_contained_with_no_external_resources(dashboard_data):
    data, _ = dashboard_data
    html = render_index(data)
    assert html.startswith("<!doctype html>")
    assert '<html lang="fr">' in html  # native date inputs render dd/mm/yyyy
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html
    assert 'rel="stylesheet"' not in html
    assert "<script src=" not in html
    assert "fetch(" not in html
    assert "innerHTML" not in html
    assert '<meta name="robots" content="noindex, nofollow">' in html
    for marker in ("__CSS__", "__JS__", "__DATA__"):
        assert marker not in html


def test_write_site_writes_both_files(tmp_path, dashboard_data):
    data, _ = dashboard_data
    index, data_file = write_site(data, tmp_path / "site")
    assert index == tmp_path / "site" / "index.html" and index.exists()
    assert data_file == tmp_path / "site" / "data.json" and data_file.exists()
    on_disk = json.loads(data_file.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(data))
    assert set(on_disk) == {"generated_at", "thresholds", "jobs", "leads", "runs"}


def test_light_and_dark_tokens_are_both_defined():
    html = render_index(_EMPTY)
    assert '[data-theme="light"]' in html
    assert "prefers-color-scheme: light" in html
    assert "prefers-reduced-motion" in html
    assert "--canvas: #010102" in html
    assert "--canvas: #ffffff" in html


def test_jobs_table_has_posted_and_age_columns_and_no_collected_column():
    from job_match.dashboard.render import render_index

    html = render_index(
        {"generated_at": "", "thresholds": {}, "jobs": [], "leads": [], "runs": []}
    )
    assert 'data-key="posted_at">Posted<' in html
    assert 'data-key="age_days">Age<' in html
    assert 'data-key="collected_at"' not in html
    assert "Posted from" in html and "Collected from" not in html
    assert '"posted_at", "age_days"]' in html  # SORT_KEYS allow-list for the hash
