"""Candidatures table (ADR 0024): « Postuler » copies the one `job-match apply` command and
names its number, or opens the offer; « Pré-remplissage » / « Manuel » under the title; an
application on a closed offer is « Expirée » (grey, last, out of the Kanban, no documents,
no button); the title opens the record."""

# The page inlines its data: make offer 0 a Greenhouse form, 1 a by-hand one, 2 closed (a
# kept offer the source closed), as the script reads it. The clipboard is recorded.
SETUP = """
(() => { const parse = JSON.parse; JSON.parse = function (t) {
  const v = parse.apply(this, arguments);
  if (v && Array.isArray(v.jobs) && v.jobs.length > 2 && !v.__jm) {
    v.__jm = true;
    v.jobs[0].apply_form = "greenhouse"; v.jobs[0].url = "https://boards.greenhouse.io/acme/jobs/1";
    v.jobs[1].apply_form = null; v.jobs[1].url = "https://jobs.smartrecruiters.com/Devoteam/3";
    v.jobs[2].apply_form = "lever"; v.jobs[2].closed = true;
    v.jobs[2].title = "Consultant Cloud Ops (H/F)";
  }
  return v; };
  window.__copied = [];
  window.__opened = [];
  Object.defineProperty(navigator, "clipboard", { value: { writeText: (t) => {
    window.__copied.push(t); return Promise.resolve(); } } });
  window.open = (u) => { window.__opened.push(u); return null; };
})();
"""


def _app(key, updated):
    return {"job_key": key, "status": "to_apply", "applied_at": None, "follow_up_at": None,
            "note": None, "cv_url": None, "updated_at": updated, "sent_documents_version": None}


def _api(keys):
    apps = [_app(keys[0], "2026-10-21T08:00:00Z"), _app(keys[1], "2026-10-20T08:00:00Z"),
            _app(keys[2], "2026-10-19T08:00:00Z")]
    return {"applications": apps, "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": [], "documents_budget": None}


def _table(open_dashboard, api, **kw):
    page, errors = open_dashboard(api, init_script=SETUP, **kw)
    page.wait_for_function("() => document.querySelectorAll('#kb-board .kb-card').length > 0")
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    return page, errors


def _row(page, key):
    return page.locator(f'#kb-table tbody tr[data-key="{key}"]')


def test_postuler_copies_the_command_and_names_the_number(open_dashboard, job_keys):
    # offer 1 (kept earlier) is an Ashby form too: offer 0 is n° 2 of the CLI's list (oldest
    # kept first); offer 2 is closed and not in it
    setup = SETUP.replace("v.jobs[1].apply_form = null", 'v.jobs[1].apply_form = "ashby"')
    page, errors = open_dashboard(_api(job_keys), init_script=setup)
    page.wait_for_function("() => document.querySelectorAll('#kb-board .kb-card').length > 0")
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    row = _row(page, job_keys[0])
    assert row.locator(".apps-form").inner_text() == "Pré-remplissage"
    row.locator("button.apps-apply").click()
    page.wait_for_function("() => window.__copied.length === 1")
    assert page.evaluate("window.__copied") == [r".venv\Scripts\job-match apply"]
    toast = page.locator("#toast")
    assert "Colle dans PowerShell et choisis le n° 2" in toast.inner_text()
    assert page.evaluate("window.__opened") == []
    assert errors == []


def test_postuler_on_a_manual_form_opens_the_offer(open_dashboard, job_keys):
    page, errors = _table(open_dashboard, _api(job_keys))
    row = _row(page, job_keys[1])
    assert row.locator(".apps-form").inner_text() == "Manuel"
    row.locator("button.apps-apply").click()
    page.wait_for_function("() => window.__opened.length === 1")
    assert page.evaluate("window.__opened") == ["https://jobs.smartrecruiters.com/Devoteam/3"]
    assert page.evaluate("window.__copied") == []
    assert errors == []


def test_a_kept_application_on_a_closed_offer_is_expired(open_dashboard, job_keys):
    page, errors = _table(open_dashboard, _api(job_keys))
    row = _row(page, job_keys[2])
    assert row.locator(".status-badge.is-expired").inner_text() == "Expirée"
    assert row.locator("button.apps-apply").count() == 0
    assert row.get_attribute("class") == "is-expired"
    # last row, and not counted by « Générer les manquants » (2 open ones lack documents)
    keys = [r.get_attribute("data-key") for r in page.locator("#kb-table tbody tr").all()]
    assert keys[-1] == job_keys[2]
    assert "(2)" in page.locator("#apps-generate-missing").inner_text()
    # the Kanban's « À candidater » column leaves it out
    page.click("#apps-view-kanban")
    col = page.locator('#kb-board .kb-col[data-status="to_apply"]')
    assert col.locator(".kb-card").count() == 2
    assert col.locator(f'.kb-card[data-key="{job_keys[2]}"]').count() == 0
    assert errors == []


def test_the_row_title_opens_the_record(open_dashboard, job_keys):
    for viewport in ((1440, 900), (390, 844)):
        page, errors = _table(open_dashboard, _api(job_keys), viewport=viewport)
        _row(page, job_keys[0]).locator("td.apps-title .link-btn").click()
        page.wait_for_function("() => !document.getElementById('record').hidden")
        assert page.locator("#record").is_visible(), viewport
        assert "fiche=" in page.evaluate("location.hash")
        assert errors == []
