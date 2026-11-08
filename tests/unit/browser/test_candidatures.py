"""Candidatures in a real browser: the Kanban and the table with an application in every board
status, and 0 console errors (the M26 production bug: the board's status menu was shadowed by
the Offres status filter, and the view came up empty). Then the isolation: one broken card is
logged and replaced, the others show.
"""

import json
from urllib.parse import quote

STATUSES = ["to_apply", "applied", "interview", "rejected"]
BUDGET = {"monthly_usd": 60, "spent_usd": 1.9, "remaining_usd": 58.1, "estimate_usd": 0.07}
# the smallest PDF Chromium accepts as a download: a header and a trailer
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
# every element under `sel` whose content is wider than its box: text-overflow at work
NO_CLIP = """
(sel) => Array.from(document.querySelectorAll(sel)).flatMap((n) => [n, ...n.querySelectorAll('*')])
  .filter((n) => n.scrollWidth > n.clientWidth + 1)
  .map((n) => n.tagName + '.' + n.className + ' ' + n.scrollWidth + '>' + n.clientWidth)
"""
SENTINEL = "1999-12-31"  # the follow_up_at the fault injection throws on
# an arrow function: a bare expression would be eval'ed, which the page's CSP refuses
HAS_CARDS = "() => document.querySelectorAll('#kb-board .kb-card').length > 0"


def _api(keys, broken=False):
    apps = []
    day = "2026-10-20"
    # three listed offers, then one whose offer the page no longer lists (rejected)
    for status, key in zip(STATUSES, list(keys[:3]) + ["france_travail:GONE1"]):
        app = {"job_key": key, "status": status, "applied_at": None, "follow_up_at": None,
               "note": None, "cv_url": None, "updated_at": "2026-10-20T08:00:00Z",
               "sent_documents_version": None}
        if status == "applied":
            app["applied_at"] = day
            if broken:  # the card and the table row both format this date
                app["follow_up_at"] = SENTINEL
        if status == "interview":
            app["applied_at"] = day
            app["follow_up_at"] = "2026-01-02"  # due long ago
        apps.append(app)
    documents = [
        # ready but not rendered yet (files False): the links show anyway, the Worker renders
        # on the first download
        {"job_key": keys[0], "version": 1, "status": "ready", "language": "fr",
         "error_code": None, "updated_at": "2026-10-20T09:00:00Z", "files": False},
        {"job_key": keys[1], "version": 1, "status": "failed", "language": "fr",
         "error_code": "invented_number", "updated_at": "2026-10-20T09:00:00Z", "files": False},
    ]
    run = {"id": 1, "started_at": "2026-10-20T07:30:00Z", "finished_at": "2026-10-20T07:31:00Z",
           "outcome": "ok", "http_status": None, "provider": "anthropic",
           "counters": {"scored": 3, "cached": 1}}
    # keys[2] (interview) has no documents row: the one « Générer les manquants » counts
    return {"applications": apps, "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [run], "documents": documents, "documents_budget": BUDGET}


def _open_candidatures(open_dashboard, api, **kw):
    page, errors = open_dashboard(api, **kw)
    page.wait_for_function(HAS_CARDS)
    return page, errors


def test_kanban_shows_every_status_without_console_errors(open_dashboard, job_keys):
    page, errors = _open_candidatures(open_dashboard, _api(job_keys))
    cols = page.locator("#kb-board .kb-col")
    assert cols.count() == 4
    assert [c.get_attribute("data-status") for c in cols.all()] == STATUSES
    assert [cols.nth(i).locator(".kb-card").count() for i in range(4)] == [1, 1, 1, 1]
    menus = page.locator("#kb-board select.kb-status")
    assert [m.input_value() for m in menus.all()] == STATUSES
    assert page.locator("#kb-board button", has_text="J’ai postulé").count() == 1
    assert page.locator("#kb-due").is_visible()
    assert "1 relance en retard" in page.locator("#kb-due").inner_text()
    # IMPECCABLE_AUDIT C3: a gone offer is named in words, its key only in the tooltip
    gone = page.locator("#kb-board .kb-card", has_text="Offre retirée (France Travail)")
    assert gone.count() == 1 and "france_travail:GONE1" not in gone.inner_text()
    assert page.locator("#kb-board .kb-card-broken").count() == 0
    assert errors == []


def test_csp_runs_the_page_and_blocks_an_injected_inline_script(open_dashboard, job_keys):
    """script-src names the page's own scripts by hash: they run (the board renders with no
    console error), and an inline script added afterwards is refused by the browser."""
    page, errors = _open_candidatures(open_dashboard, _api(job_keys))
    assert page.locator("#kb-board .kb-card").count() == 4
    assert errors == []
    page.evaluate(
        "() => { const s = document.createElement('script');"
        " s.textContent = 'window.__cspProbe = 1'; document.body.appendChild(s); }"
    )
    assert page.evaluate("window.__cspProbe") is None
    assert len(errors) == 1 and "Content Security Policy" in errors[0]


def test_table_shows_every_row_without_console_errors(open_dashboard, job_keys):
    page, errors = _open_candidatures(open_dashboard, _api(job_keys))
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    assert page.locator("#kb-board").is_hidden()
    assert page.locator("#kb-table tbody tr").count() == 4
    menus = page.locator("#kb-table select.kb-status")
    assert sorted(m.input_value() for m in menus.all()) == sorted(STATUSES)
    gone = page.locator("#kb-table tbody tr", has_text="Offre retirée (France Travail)")
    assert gone.count() == 1
    assert page.locator("#kb-table th").count() == 8
    # the ready version: PDF + DOCX for the CV and the letter; the failed one: « Échec » with
    # the code as the tooltip and « Regénérer »; a row without documents: « — » and « Générer »
    assert page.locator("#kb-table a.doc-dl").count() == 4
    labels = [a.inner_text() for a in page.locator("#kb-table a.doc-dl").all()]
    assert labels == ["⬇ PDF", "⬇ DOCX"] * 2
    # ready = links, never a badge
    assert page.locator("#kb-table .doc-badge", has_text="Prêt").count() == 0
    failed = page.locator("#kb-table .doc-badge", has_text="Échec")
    assert failed.count() == 1
    assert failed.first.get_attribute("title") == "invented_number"
    assert page.locator("#kb-table td.apps-docs button", has_text="Regénérer").count() == 1
    buttons = page.locator("#kb-table td.apps-docs button", has_text="Générer")
    assert buttons.count() == 2  # one of them is Regénérer; none on the gone, rejected offer
    assert page.locator("#kb-table td.apps-docs .doc-badge.kind-none", has_text="—").count() == 1
    assert page.locator("#apps-generate-missing").inner_text() == "Générer les manquants (1)"
    assert not page.locator("#apps-generate-missing").is_disabled()
    assert page.evaluate("location.hash").endswith("view=table")
    assert errors == []
    # back to the Kanban, still clean
    page.click("#apps-view-kanban")
    page.wait_for_function(HAS_CARDS)
    assert errors == []


# `format` is an accessor on the prototype (it returns a bound function): wrap the getter.
FAULT = """
(() => {
  const SENTINEL = '__SENTINEL__';
  const proto = Intl.DateTimeFormat.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'format');
  Object.defineProperty(proto, 'format', { configurable: true, get() {
    const f = desc.get.call(this);
    return (d) => {
      if (d instanceof Date && d.toISOString().startsWith(SENTINEL)) throw new Error('fault');
      return f(d);
    };
  } });
})();
""".replace("__SENTINEL__", SENTINEL)


def test_one_broken_card_is_logged_and_the_others_still_show(open_dashboard, job_keys):
    api = _api(job_keys, broken=True)
    page, errors = _open_candidatures(open_dashboard, api, init_script=FAULT)
    assert page.locator("#kb-board .kb-card").count() == 4
    broken = page.locator("#kb-board .kb-card-broken")
    assert broken.count() == 1
    assert broken.first.get_attribute("data-key") == job_keys[1]
    assert "Carte illisible" in broken.first.inner_text()
    assert broken.first.locator("select.kb-status").input_value() == "applied"
    assert page.locator("#kb-board .kb-card:not(.kb-card-broken)").count() == 3
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    assert page.locator("#kb-table tbody tr").count() == 4
    broken_row = page.locator("#kb-table tbody tr.kb-card-broken")
    assert broken_row.count() == 1
    assert "ligne illisible" in broken_row.inner_text()
    logged = [e for e in errors if e.startswith("candidatures: carte illisible")]
    assert len(logged) == 2, errors  # one for the card, one for the row
    assert all(job_keys[1] in e for e in logged)
    assert len(errors) == 2, errors  # nothing else: no uncaught exception, no blank view


def test_run_now_buttons_are_enabled_once_tracking_loaded(open_dashboard, job_keys):
    page, errors = open_dashboard(_api(job_keys), hash_="#executions")
    page.wait_for_function("() => !document.getElementById('ai-run-now').disabled")
    assert not page.locator("#docs-run-now").is_disabled()
    assert page.locator("#ai-runs-list .run-ai").count() == 1
    assert errors == []


def _open_table(open_dashboard, api, **kw):
    page, errors = _open_candidatures(open_dashboard, api, **kw)
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    return page, errors


def test_table_cells_are_never_truncated_at_1440_and_390(open_dashboard, job_keys):
    for viewport in ((1440, 900), (390, 844)):
        page, errors = _open_table(open_dashboard, _api(job_keys), viewport=viewport)
        # the longest status label, « Candidature envoyée » (applied), is in the second row
        assert page.locator("#kb-table select.kb-status").nth(0).is_visible()
        clipped = page.evaluate(NO_CLIP, "#kb-table td.apps-status, #kb-table td.apps-docs, "
                                "#kb-table td.doc-cell, #kb-table .kb-table-bar")
        assert clipped == [], (viewport, clipped)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), viewport
        # the title ellipsizes and keeps the full text in its tooltip
        first = page.locator("#kb-table td.apps-title .link-btn").first
        assert first.get_attribute("title") == first.inner_text()
        assert errors == []


# The page inlines its data: blank the first offer's company as the script reads it.
BLANK_COMPANY = """
(() => { const parse = JSON.parse; JSON.parse = function (t) {
  const v = parse.apply(this, arguments);
  if (v && Array.isArray(v.jobs) && v.jobs.length) v.jobs[0].company = "";
  return v; }; })();
"""


def test_unknown_company_reads_non_communiquee(open_dashboard, job_keys):
    page, errors = _open_table(open_dashboard, _api(job_keys), init_script=BLANK_COMPANY)
    unknown = page.locator("#kb-table td.apps-company .apps-unknown")
    assert unknown.count() == 1
    assert unknown.first.inner_text() == "Non communiquée"
    assert page.locator("#kb-table td.apps-company", has_text="—").count() == 0
    assert errors == []


def test_generate_missing_confirms_with_count_and_cost_then_posts(open_dashboard, job_keys):
    missing_key = job_keys[2]
    answer = {"requested": 1, "skipped_budget": 0, "remaining_usd": 58.04,
              "documents": [{"job_key": missing_key, "version": 1, "status": "pending"}]}
    routes = {("POST", "/api/documents/missing"): (200, {"content-type": "application/json"},
                                                   json.dumps(answer))}
    page, errors = _open_table(open_dashboard, _api(job_keys), routes=routes)
    page.click("#apps-generate-missing")
    toast = page.locator("#toast")
    assert "1 document · ≈ 0,07\u00a0$ (reste 58,10\u00a0$ ce mois)" in toast.inner_text()
    page.get_by_role("button", name="Annuler").click()
    assert page.api_calls[1:] == []  # nothing without the confirmation
    page.click("#apps-generate-missing")
    page.get_by_role("button", name="Confirmer").click()
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'#kb-table td.apps-docs .doc-badge.kind-pending').length === 1")
    assert page.api_calls[1:] == [("POST", "/api/documents/missing")]
    assert "1 génération demandée" in toast.inner_text()
    assert page.locator("#apps-generate-missing").inner_text() == "Générer les manquants (0)"
    assert page.locator("#apps-generate-missing").is_disabled()
    assert errors == []


# What GET /api/documents/<key>/v1/content.json answers (ADR 0019): the generated text, the
# master and the contact sheet. Small, and every value is made up.
BUNDLE = {
    "content": {
        "job_key": None, "version": 1, "language": "fr", "model": "test", "prompt_version": "4",
        "generated_at": "2026-10-20T09:00:00Z",
        "offer": {"key": None, "title": "Ingénieur DevOps", "company": "Initech"},
        "profile": "Ingénieur DevOps orienté Kubernetes. Disponible à partir de janvier 2027.",
        "selected_bullets": [{"id": "exp1.b1", "text": "Migration de 12 services vers GKE."}],
        "skill_groups": [{"group": "Conteneurs", "items": ["Kubernetes (GKE)", "Helm"]}],
        "headline_techs": ["Kubernetes", "Helm"],
        "letter": {"paragraphs": [
            {"sentences": [{"text": "Votre offre chez Initech correspond à ce que je cherche.",
                            "sources": []}]},
            {"sentences": [{"text": "Disponible à partir de janvier 2027, je serais heureux d’en "
                                    "discuter avec vous.", "sources": []}]}]},
        "highlights": ["Kubernetes"],
        "availability": "Disponible à partir de janvier 2027.",
        "cv": {"experiences": [{"id": "exp1", "employer": "Acme Cloud", "title": "DevOps",
                                "start": "2025-01", "end": None, "location": "Nantes",
                                "bullets": [{"id": "exp1.b1",
                                             "text": "Migration de 12 services vers GKE."}]}],
               "projects": []},
    },
    "master": {
        "headline": "Ingénieur DevOps", "skill_groups": [],
        "education": [{"degree": "Ingénieur", "school": "ENSIAS", "location": "Rabat",
                       "start": "2022-09", "end": "2025-06"}],
        "languages": [{"name": "Français", "level": "bilingue"}], "extras": [],
    },
    "contact": {"first_name": "Mohamed", "last_name": "Chacrone", "title": "Ingénieur DevOps",
                "email": "m@example.com", "phone": "+33 6 00 00 00 00", "linkedin": "",
                "github": "", "location": "Lyon"},
}


def _bundle_routes(key):
    bundle = json.loads(json.dumps(BUNDLE))
    bundle["content"]["job_key"] = key
    bundle["content"]["offer"]["key"] = key
    path = f"/api/documents/{quote(key, safe='')}/v1/content.json"
    headers = {"content-type": "application/json", "cache-control": "no-store"}
    return path, {("GET", path): (200, headers, json.dumps(bundle))}


def _download(page, label):
    link = page.locator("#kb-table a.doc-dl", has_text=label).first
    with page.expect_download() as info:
        link.click()
    download = info.value
    with open(download.path(), "rb") as fh:
        head = fh.read(5)
    page.wait_for_function("() => !document.querySelector('#kb-table a.doc-dl[aria-busy]')")
    return download.suggested_filename, head


def test_pdf_link_renders_in_the_page_and_saves_under_the_template_name(open_dashboard, job_keys):
    content, routes = _bundle_routes(job_keys[0])
    page, errors = _open_table(open_dashboard, _api(job_keys), routes=routes)
    link = page.locator("#kb-table a.doc-dl", has_text="\u2b07 PDF").first
    assert link.get_attribute("href") == "#"
    name, head = _download(page, "\u2b07 PDF")
    assert name == "CV_Mohamed_Chacrone_Initech.pdf"
    assert head == b"%PDF-"
    assert len(page.context.pages) == 1  # no new tab
    assert page.url.endswith("view=table")  # href="#" did not move the page
    # one content.json call (no file route), and once each the renderer, its three libraries
    # and the two Latin fonts (preloaded when Candidatures opened, or fetched by the click)
    assert page.api_calls[1:] == [("GET", content)]
    assert sorted(page.file_calls) == sorted([
        "/assets/render.js", "/vendor/pdf-lib.min.js", "/vendor/fontkit.umd.min.js",
        "/vendor/fflate.js", "/fonts/Inter-Bold-latin.ttf", "/fonts/Inter-Regular-latin.ttf"])
    # the second file reuses everything, content.json included: no request at all
    name, head = _download(page, "\u2b07 DOCX")
    assert name == "CV_Mohamed_Chacrone_Initech.docx"
    assert head[:2] == b"PK"
    assert page.api_calls[2:] == []
    assert len(page.file_calls) == 6
    assert errors == []


def test_letter_docx_downloads_too_and_a_failed_content_call_says_so(open_dashboard, job_keys):
    content, routes = _bundle_routes(job_keys[0])
    page, errors = _open_table(open_dashboard, _api(job_keys), routes=routes)

    # a version the Worker no longer has: a toast, no download, the link usable again
    def gone(route, _req):
        route.fulfill(status=404, content_type="application/json",
                      body='{"error":"document: not found"}')

    page.route("**/content.json", gone)
    page.locator("#kb-table a.doc-dl", has_text="\u2b07 PDF").first.click()
    page.wait_for_selector("#toast", state="visible")
    assert "non téléchargé" in page.locator("#toast").inner_text()
    page.wait_for_function("() => !document.querySelector('#kb-table a.doc-dl[aria-busy]')")
    # the failure is not kept: once the Worker answers again, the same link downloads
    page.unroute("**/content.json", gone)
    name, head = _download(page, "\u2b07 PDF")  # the letter's PDF is the third link
    assert name == "CV_Mohamed_Chacrone_Initech.pdf"
    letter = page.locator("#kb-table td.doc-cell").nth(1).locator("a.doc-dl.alt")
    with page.expect_download() as info:
        letter.click()
    assert info.value.suggested_filename == "Lettre_Mohamed_Chacrone_Initech.docx"
    assert [e for e in errors if "404" not in e] == []  # the deliberate 404 is logged by Chromium


def test_remembered_table_view_presses_the_right_chip(open_dashboard, job_keys):
    seed = "try { localStorage.setItem('jm.appsView', 'table'); } catch (e) {}"
    page, errors = open_dashboard(_api(job_keys), init_script=seed)
    page.wait_for_selector("#kb-table table.data.apps")
    assert page.locator("#kb-board").is_hidden()
    assert page.locator("#apps-view-table").get_attribute("aria-pressed") == "true"
    assert page.locator("#apps-view-kanban").get_attribute("aria-pressed") == "false"
    assert errors == []


def test_generer_runs_now_and_the_links_appear_without_a_reload(open_dashboard, job_keys):
    key = job_keys[2]  # the row without documents
    calls = {"n": 0}

    def api():
        calls["n"] += 1
        payload = _api(job_keys)
        if calls["n"] >= 3:  # the second poll: the Worker's immediate pass is done
            payload["documents"].append({"job_key": key, "version": 1, "status": "ready",
                                         "language": "fr", "error_code": None,
                                         "updated_at": "2026-10-20T10:00:00Z", "files": True})
        elif calls["n"] == 2:
            payload["documents"].append({"job_key": key, "version": 1, "status": "running",
                                         "language": "fr", "error_code": None,
                                         "updated_at": "2026-10-20T10:00:00Z", "files": False})
        return payload

    regen = f"/api/documents/{quote(key, safe='')}/regenerate"
    answer = json.dumps({"document": {"job_key": key, "version": 1, "status": "pending"}})
    routes = {("POST", regen): (201, {"content-type": "application/json"}, answer)}
    page, errors = _open_table(open_dashboard, api, routes=routes,
                               init_script="window.__jmWatchMs = 200;")
    generate = page.get_by_role("button", name="Générer", exact=True)  # not « Regénérer »
    assert generate.count() == 1
    generate.click()
    # the ⬇ links come up where the button was: a pointer left there would prefetch content.json
    page.mouse.move(0, 0)
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'#kb-table td.apps-docs .doc-badge.kind-pending').length === 1")
    badge = page.locator("#kb-table td.apps-docs .doc-badge.kind-pending")
    assert badge.inner_text() == "En cours…"
    assert page.locator("#kb-table td.apps-docs button").count() == 1  # « Regénérer » only
    page.wait_for_function(
        "() => document.querySelectorAll('#kb-table a.doc-dl').length === 8")
    assert page.locator("#kb-table td.apps-docs .doc-badge", has_text="En cours").count() == 0
    page.wait_for_timeout(600)  # three more intervals: the watch has stopped
    assert calls["n"] == 3, calls
    assert page.api_calls == [("GET", "/api/applications"), ("POST", regen),
                              ("GET", "/api/applications"), ("GET", "/api/applications")]
    assert errors == []
