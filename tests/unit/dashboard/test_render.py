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
    # the one network call allowed: the tracking API on the same origin
    assert "connect-src 'self'" in html
    assert 'rel="stylesheet"' not in html
    assert "<script src=" not in html
    assert re.findall(r'fetchImpl\("([^"]*)"', html) == ["/api/"]
    assert "fetch(" not in html.replace("window.fetch.bind", "")
    assert "innerHTML" not in html
    assert '<meta name="robots" content="noindex, nofollow">' in html
    for marker in ("__CSS__", "__JS__", "__TRACKING_JS__", "__DATA__"):
        assert marker not in html


def test_write_site_writes_both_files(tmp_path, dashboard_data):
    data, _ = dashboard_data
    index, data_file = write_site(data, tmp_path / "site")
    assert index == tmp_path / "site" / "index.html" and index.exists()
    assert data_file == tmp_path / "site" / "data.json" and data_file.exists()
    on_disk = json.loads(data_file.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(data))
    assert set(on_disk) == {"generated_at", "thresholds", "jobs", "tracked", "leads", "runs"}


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
    assert 'data-key="posted_at">Publiée<' in html
    assert 'data-key="age_days">Âge<' in html
    assert 'data-key="collected_at"' not in html
    assert "Publiée depuis" in html and "Collected from" not in html
    assert '"status", "posted_at", "age_days"]' in html  # SORT_KEYS allow-list for the hash


def test_tri_is_the_default_tab_and_the_nav_is_in_french():
    html = render_index(_EMPTY)
    assert 'id="tab-tri" aria-controls="panel-tri" aria-selected="true"' in html
    for tab, label in (("candidatures", "Candidatures"), ("offres", "Offres"), ("leads", "Leads"),
                       ("executions", "Exécutions")):
        assert f'id="tab-{tab}" aria-controls="panel-{tab}" aria-selected="false"' in html
        assert f'data-tab="{tab}">{label} <span' in html
        assert f'id="panel-{tab}" role="tabpanel" aria-labelledby="tab-{tab}" hidden>' in html
    assert 'var TABS = ["tri", "candidatures", "offres", "leads", "executions"];' in html
    assert 'today: "tri", jobs: "offres", runs: "executions"' in html  # old links still work
    assert 'id="tri-stage"' in html and 'id="kb-board"' in html and 'id="tri-live"' in html
    assert 'id="track-banner"' in html


def test_every_offres_filter_is_present_and_wired():
    html = render_index(_EMPTY)
    for control in ('id="f-search"', 'id="f-department"', 'id="f-status"', 'id="f-min-score"',
                    'id="f-from"', 'id="f-to"', 'id="f-reset"', 'data-section="strong"',
                    'data-section="eligible"', 'data-section="stretch"', 'id="filters-count"'):
        assert control in html, control
    for key in ("title", "company", "department", "contract", "score", "required_years",
                "status", "posted_at", "age_days"):
        assert f'data-key="{key}"' in html, key
    script = html.split("function applyHash()")[1].split("/* ---------- leads")[0]
    for param in ("p.q", "p.hide", "p.dept", "p.st", "p.min", "p.from", "p.to", "p.sort"):
        assert param in script, param
    for listener in ('searchInput.addEventListener("input"',
                     'deptSelect.addEventListener("change"',
                     'statusSelect.addEventListener("change"',
                     'minScoreInput.addEventListener("input"',
                     'fromInput.addEventListener("change"',
                     'toInput.addEventListener("change"',
                     'byId("f-reset").addEventListener("click"'):
        assert listener in html, listener
    # The filters travel in the hash whatever the tab (Tri -> Offres keeps them).
    sync = html.split("function syncHash()")[1].split("function parseHash()")[0]
    assert 'currentTab === "jobs"' not in sync and 'currentTab === "offres"' not in sync


def test_tracking_script_is_inlined_before_the_dashboard_script():
    html = render_index(_EMPTY)
    assert html.index("root.JMTracking = api") < html.index("var T = window.JMTracking;")


def test_the_interface_is_in_french():
    """No English label left in the markup or the scripts' visible strings."""
    import re

    html = render_index(_EMPTY)
    text_nodes = re.findall(r">([^<>]+)<", html.split('<script type="application/json"')[0])
    visible = " ".join(t.strip() for t in text_nodes if t.strip())
    for word in ("Title", "Company", "Status", "Posted", "Link", "Filters", "Reset", "Strong",
                 "Eligible", "Stretch", "To apply", "To review", "Follow", "Light mode", "Runs"):
        assert not re.search(rf"\b{word}\b", visible), word
    scripts = html.split('<script type="application/json"')[1]
    for phrase in ('"Saving…"', '"Saved"', '"Retry"', '"Open"', '"Not saved', '"Verdict saved"',
                   '"To review"', '"Applied"', '"Good fit"'):
        assert phrase not in scripts, phrase


def test_write_site_adds_an_installable_manifest_and_no_service_worker(tmp_path):
    import json as _json

    from job_match.dashboard.render import ICONS, write_site

    write_site(_EMPTY, tmp_path)
    manifest = _json.loads((tmp_path / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone" and manifest["start_url"] == "./#tri"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
    for name in ICONS:
        assert (tmp_path / "icons" / name).read_bytes().startswith(b"\x89PNG")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="manifest.webmanifest" crossorigin="use-credentials">' in html
    assert "manifest-src 'self'" in html
    assert "serviceWorker" not in html  # data.json and the page are never cached
