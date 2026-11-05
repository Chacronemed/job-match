"""The rendered page: external text can never become markup, and nothing of it is in the HTML."""
import json
import re

import pytest

from job_match.dashboard.render import (
    PDF_FONTS,
    SCRIPTS,
    VENDOR,
    browser_renderer,
    embed_json,
    render_index,
    script_hash,
    strip_comments,
    write_renderer,
    write_site,
)

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
    # scripts: the eight inline ones by their hash, or same-origin files (the document
    # renderer, ADR 0019); never 'unsafe-inline', never a CDN
    script_src = re.search(r"script-src ([^;]*);", html).group(1)
    assert "'unsafe-inline'" not in script_src
    assert "style-src 'unsafe-inline';" in html  # the inlined stylesheets, unchanged
    hashes = script_src.split(" ")
    assert hashes[0] == "'self'" and len(hashes) == len(SCRIPTS) + 1
    inline = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(inline) == len(SCRIPTS)
    assert hashes[1:] == [script_hash(body) for body in inline]
    assert 'rel="stylesheet"' not in html
    assert "<script src=" not in html
    assert re.findall(r'fetchImpl\("([^"]*)"', html) == ["/api/"]
    assert "fetch(" not in html.replace("window.fetch.bind", "")
    assert "innerHTML" not in html
    assert '<meta name="robots" content="noindex, nofollow">' in html
    for marker in ("__CSS__", "__SCRIPTS__", "__SCRIPT_HASHES__", "__DATA__"):
        assert marker not in html


def test_write_site_writes_both_files(tmp_path, dashboard_data):
    data, _ = dashboard_data
    index, data_file = write_site(data, tmp_path / "site")
    assert index == tmp_path / "site" / "index.html" and index.exists()
    assert data_file == tmp_path / "site" / "data.json" and data_file.exists()
    on_disk = json.loads(data_file.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(data))
    assert set(on_disk) == {"generated_at", "thresholds", "jobs", "tracked", "leads", "runs"}


def test_the_page_has_dark_and_light_tokens_one_accent_and_reduced_motion():
    """DESIGN.md: Radix slate on three surfaces, one violet accent; the light tokens override the
    same names under data-theme="light" (tokens.css), and the toggle is visible."""
    html = render_index(_EMPTY)
    assert '<meta name="color-scheme" content="dark light">' in html
    css = html.split("<style>")[1].split("</style>")[0]
    assert ':root[data-theme="light"]' in css and "prefers-color-scheme: light" not in css
    assert "--bg: var(--slate-1)" in html and "--slate-1: #111113" in html
    assert "--accent: var(--violet-9)" in html
    assert 'id="theme-toggle" type="button" aria-pressed="false">' in html
    assert "prefers-reduced-motion: reduce" in html
    assert "linear-gradient" not in html and "radial-gradient" not in html


def test_inter_is_self_hosted_under_the_csp_and_licensed(tmp_path, dashboard_data):
    data, _ = dashboard_data
    html = render_index(data)
    assert "font-src 'self'" in html
    assert 'url("fonts/InterVariable-latin.woff2")' in html
    # no resource from another origin: every url() and href/src is relative or the data block
    assert not re.search(r"url\(\s*[\"']?https?:", html)
    assert not re.search(r'<(link|script|img)[^>]+(href|src)="https?:', html)
    site = tmp_path / "site"
    write_site(data, site)
    font = (site / "fonts" / "InterVariable-latin.woff2").read_bytes()
    assert font[:4] == b"wOF2"
    licences = (site / "LICENSES.md").read_text(encoding="utf-8")
    for name in ("SIL Open Font License", "ISC License", "MIT License", "Inter", "Lucide", "Radix"):
        assert name in licences


def test_jobs_table_shows_the_age_and_keeps_the_posting_date_behind_the_row():
    from job_match.dashboard.render import render_index

    html = render_index(
        {"generated_at": "", "thresholds": {}, "jobs": [], "leads": [], "runs": []}
    )
    assert 'data-key="age_days">Âge<' in html
    assert 'data-key="posted_at"' not in html and 'data-key="collected_at"' not in html
    assert "Publiée depuis" in html and "Collected from" not in html
    assert '"status", "posted_at", "age_days"]' in html  # SORT_KEYS allow-list for the hash


def test_every_offres_filter_is_present_and_wired():
    html = render_index(_EMPTY)
    for control in ('id="f-search"', 'id="f-department"', 'id="f-status"', 'id="f-ai"',
                    'id="f-min-score"',
                    'id="f-from"', 'id="f-to"', 'id="f-reset"', 'data-section="strong"',
                    'data-section="eligible"', 'data-section="stretch"', 'id="filters-count"'):
        assert control in html, control
    for key in ("score", "title", "company", "department", "contract", "age_days"):
        assert f'data-key="{key}"' in html, key
    script = html.split("function applyHash()")[1].split("function rowByKey(")[0]
    for param in ("p.q", "p.hide", "p.dept", "p.st", "p.ia", "p.min", "p.from", "p.to", "p.sort"):
        assert param in script, param
    for listener in ('searchInput.addEventListener("input"',
                     'deptSelect.addEventListener("change"',
                     'statusSelect.addEventListener("change"',
                     'aiSelect.addEventListener("change"',
                     'minScoreInput.addEventListener("input"',
                     'fromInput.addEventListener("change"',
                     'toInput.addEventListener("change"',
                     'byId("f-reset").addEventListener("click"'):
        assert listener in html, listener
    # The filters travel in the hash whatever the tab (Tri -> Offres keeps them).
    sync = html.split("function syncHash()")[1].split("function parseHash()")[0]
    assert 'currentTab === "jobs"' not in sync and 'currentTab === "offres"' not in sync


def test_audit_p1_fixes_are_in_the_page():
    """docs/design/AUDIT.md P1-1 to P1-3 and P2-16, at the markup level."""
    html = render_index(_EMPTY)
    # P1-1: the follow-up question lives in the toast, never in a board card.
    assert 'id="toast-actions"' in html and "kb-prompt" not in html
    assert "followUpAsk(key, today)" in html
    # P1-2: a word search, with an example query.
    assert 'placeholder="ex. orbital kubernetes"' in html
    assert "T.matchesWords(j, searchWords())" in html
    # P1-3: the reason step names the offer, as the one that just left (not the card shown).
    assert 'id="tri-reasons-title"' in html and '"Dernière offre écartée' in html
    # P2-16: the row count is the one live region of the list (the counts sit in the chips).
    assert 'class="kpis"' not in html
    assert '<span class="controls-hint" id="jobs-rowcount" aria-live="polite">' in html


def test_tracking_script_is_inlined_before_the_dashboard_script():
    html = render_index(_EMPTY)
    assert html.index("root.JMTracking = api") < html.index("var T = window.JMTracking;")
    # every shared module is defined before the page reads it
    for module, reader in (("root.JMDesc = api", "var D = window.JMDesc;"),
                           ("root.JMScore = api", "var S = window.JMScore;"),
                           ("root.JMUI = api", "var U = window.JMUI;")):
        assert html.index(module) < html.index(reader), module


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


def test_executions_has_the_ai_runs_block():
    html = render_index(_EMPTY)
    for needle in ('id="ai-runs-list"', 'id="ai-runs-empty"', "Rerank IA", "Aucun passage de l’IA",
                   "function renderAiRuns()", "res.ai_runs"):
        assert needle in html, needle


def test_ai_profile_is_a_separate_file_the_page_never_embeds(tmp_path, dashboard_data):
    from job_match.dashboard.render import AI_PROFILE

    data, _ = dashboard_data
    site = tmp_path / "site"
    profile = {"preferred": [{"name": "kubernetes-marker", "band": "fort"}], "mobility": "france"}
    write_site(data, site, profile)
    on_disk = json.loads((site / AI_PROFILE).read_text(encoding="utf-8"))
    assert on_disk == profile
    assert "kubernetes-marker" not in (site / "index.html").read_text(encoding="utf-8")
    assert "kubernetes-marker" not in (site / "data.json").read_text(encoding="utf-8")
    # Without a profile the stale file goes: the Worker's cron must not read last week's.
    write_site(data, site)
    assert not (site / AI_PROFILE).exists()


def test_candidatures_has_the_kanban_table_toggle_and_the_table_container():
    from pathlib import Path

    from job_match.dashboard import render as render_module

    html = (Path(render_module.__file__).parent / "assets" / "index.template.html").read_text(
        encoding="utf-8"
    )
    assert 'id="kb-board"' in html and 'id="kb-table"' in html
    assert 'id="apps-view-kanban"' in html and 'id="apps-view-table"' in html
    assert 'aria-label="Affichage des candidatures"' in html


def test_executions_has_the_run_now_buttons():
    """« Lancer maintenant » for the AI rerank and the documents pass: in the page and wired."""
    html = render_index(_EMPTY)
    for needle in ('id="ai-run-now"', 'id="docs-run-now"', "Lancer maintenant", 'id="h-docs-runs"',
                   "api.runAi()", "api.runDocuments()", "Rerank IA lancé",
                   "function runNowButtons()",
                   'runAi: function () { return call("POST", "ai/run"); }',
                   'runDocuments: function () { return call("POST", "documents/run"); }'):
        assert needle in html, needle
    assert html.count(">Lancer maintenant</button>") == 2


def test_candidatures_render_is_isolated_per_card():
    """One broken card or row is logged with its key and replaced, the others still show."""
    html = render_index(_EMPTY)
    for needle in ("function safeNode(key, build, fallback)",
                   'console.error("candidatures: carte illisible", key, err)',
                   "function brokenCard(key)", "function brokenRow(key)", "kb-card-broken",
                   "function statusMenu(key, j, status)", "Affichage interrompu"):
        assert needle in html, needle
    # The Offres status filter and the board's status menu must not share a name (prod bug, M26).
    assert "function statusSelect(" not in html


def test_the_site_ships_the_renderer_its_libraries_and_the_pdf_fonts(tmp_path, dashboard_data):
    """ADR 0019: the browser renders the CV and the letter from the Worker's own render.js."""
    data, _ = dashboard_data
    site = tmp_path / "site"
    write_site(data, site)
    renderer = (site / "assets" / "render.js").read_text(encoding="utf-8")
    assert not re.search(r"^import\b", renderer, re.M)
    for line in ("const fontkit = globalThis.fontkit;",
                 "const { strToU8, zipSync } = globalThis.fflate;",
                 "const { PDFDocument, rgb } = globalThis.PDFLib;"):
        assert line in renderer
    assert "export function fileName" in renderer
    assert "export async function renderCvPdf" in renderer
    for name in VENDOR:
        assert (site / "vendor" / name).stat().st_size > 10_000
    for name in PDF_FONTS:
        assert (site / "fonts" / name).is_file()
    for name in ("Inter-Regular-latin.ttf", "Inter-Bold-latin.ttf"):  # TTF, Latin subsets
        font = (site / "fonts" / name).read_bytes()
        assert font[:4] == b"\x00\x01\x00\x00" and len(font) < 60_000
    licences = (site / "LICENSES.md").read_text(encoding="utf-8")
    for name in ("pdf-lib", "fontkit", "fflate", "pako"):
        assert name in licences
    html = (site / "index.html").read_text(encoding="utf-8")
    for src in ("vendor/pdf-lib.min.js", "vendor/fontkit.umd.min.js", "vendor/fflate.js",
                "./assets/render.js", "fonts/Inter-Regular-latin.ttf",
                "fonts/Inter-Bold-latin.ttf"):
        assert src in html  # preloaded with Candidatures, same origin


def test_the_renderer_rewrite_refuses_an_import_it_does_not_know():
    src = ('import fontkit from "@pdf-lib/fontkit";\nimport { strToU8, zipSync } from "fflate";\n'
           'import { PDFDocument, rgb } from "pdf-lib";\nexport const X = 1;\n')
    assert "import" not in browser_renderer(src)
    with pytest.raises(ValueError):
        browser_renderer(src + 'import x from "other";\n')
    with pytest.raises(ValueError):
        browser_renderer(src.replace('import { PDFDocument, rgb } from "pdf-lib";\n', ""))


def test_write_renderer_names_the_missing_npm_install(tmp_path):
    worker = tmp_path / "worker"
    (worker / "src").mkdir(parents=True)
    (worker / "src" / "render.js").write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="npm ci --prefix worker"):
        write_renderer(tmp_path / "site", worker)


def test_the_page_ships_the_code_without_its_comment_lines():
    """`strip_comments`: whole comment lines go, code and strings stay (bundle size, item 3c)."""
    src = (
        "/* head\n   note */\n"
        "(function () {\n"
        "  /* one line */\n"
        "  var a = \"/* not a comment */\";  /* trailing stays */\n"
        "  /* multi\n     line\n     comment */\n"
        "  var re = /x/;\n"
        "})();\n"
    )
    out = strip_comments(src)
    assert "note" not in out and "one line" not in out and "multi" not in out
    assert 'var a = "/* not a comment */";  /* trailing stays */' in out
    assert "var re = /x/;" in out and out.count("\n") == 4
    html = render_index(_EMPTY)
    assert "/* ---------- " not in html and "function applyHash()" in html
