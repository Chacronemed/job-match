"""Offres in a real browser (item 3 of the 2026-11-04 pass): keyboard triage on the rows with
feedback before the API answers, the filters and the density remembered across reloads, the why
ledger, the empty state with its way out, and the phone layout without horizontal scroll."""

import json

ROWS = "#jobs-body tr.row"
READY = "() => document.querySelector('#track-banner').hidden && window.JM.track.status === 'ready'"
ACTIVE_KEY = "document.activeElement.getAttribute('data-key')"
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


def _api(keys):
    return {"applications": [], "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": [], "documents_budget": None}


def _echo(route, request):
    """`PUT /api/applications/<key>` as the Worker answers it: the record sent, stored."""
    body = json.loads(request.post_data or "{}")
    key = request.url.rsplit("/", 1)[1]
    rec = {"job_key": key, "status": "to_review", "applied_at": None, "follow_up_at": None,
           "interview_at": None, "note": None, "cv_url": None,
           "updated_at": "2026-10-20T08:00:00Z"}
    rec.update(body)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"application": rec}))


def _open(open_dashboard, api, **kw):
    page, errors = open_dashboard(api, hash_="#offres", **kw)
    page.route("**/api/applications/*", _echo)  # registered last, so it answers first
    page.wait_for_selector(ROWS)
    page.wait_for_function(READY)
    return page, errors


def _row(key):
    return f'{ROWS}[data-key="{key}"]'


def test_x_s_and_a_act_on_the_focused_row_before_the_api_answers(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, _api(job_keys))
    first = page.locator(ROWS).first
    key = first.get_attribute("data-key")
    first.focus()
    page.keyboard.press("x")
    # the row shows « Ignorée » at once, and the undo toast is up
    page.wait_for_selector(_row(key) + ".st-ignored .status-ignored")
    assert "Offre ignorée" in page.locator("#toast").inner_text()
    page.get_by_role("button", name="Annuler").click()
    page.wait_for_selector(_row(key) + ":not(.is-handled)")
    page.locator(_row(key)).focus()
    page.keyboard.press("s")
    page.wait_for_selector(_row(key) + ".st-to_apply")
    page.keyboard.press("a")
    page.wait_for_selector(_row(key) + ".st-applied")
    assert "Relance ?" in page.locator("#toast").inner_text()  # the follow-up question
    assert errors == []


def test_j_and_k_move_the_focus_and_space_opens_the_why_ledger(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, _api(job_keys))
    rows = page.locator(ROWS)
    rows.first.focus()
    page.keyboard.press("j")
    assert page.evaluate(ACTIVE_KEY) == rows.nth(1).get_attribute("data-key")
    page.keyboard.press("k")
    assert page.evaluate(ACTIVE_KEY) == rows.first.get_attribute("data-key")
    page.keyboard.press("Space")
    page.wait_for_selector("#jobs-body tr.details .why[open] .why-ledger")
    lines = page.locator("#jobs-body tr.details .why-ledger .why-line")
    assert lines.count() >= 3
    # the first lines are the matched skills (the seed stores no weight: the column is
    # empty, never invented); the gate and the score close the ledger
    assert lines.first.get_attribute("class") == "why-line up"
    assert lines.first.locator("dt .why-name").inner_text() == "kubernetes"
    assert lines.first.locator("dd").inner_text() == ""
    gate = page.locator("#jobs-body tr.details .why-line.gate")
    assert "Expérience" in gate.inner_text()
    total = page.locator("#jobs-body tr.details .why-line.total dd")
    assert total.inner_text().strip().isdigit()
    assert errors == []


def test_filters_sort_and_density_outlive_a_reload(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, _api(job_keys))
    page.locator("#density-comfortable").click()
    page.locator("#jobs-controls summary").click()
    page.locator("#f-search").fill("sre")
    page.wait_for_function(f"() => document.querySelectorAll('{ROWS}').length === 1")
    page.locator('th button[data-key="title"]').click()
    hash_ = page.evaluate("location.hash")
    assert "q=sre" in hash_ and "sort=title:asc" in hash_
    # a bare hash on the next visit: the remembered filters, sort and density come back
    page.goto(page.url.split("#")[0] + "#offres")
    page.reload()
    page.wait_for_selector(ROWS)
    assert page.locator("#f-search").input_value() == "sre"
    assert page.locator(ROWS).count() == 1
    assert page.locator('th[aria-sort="ascending"] button[data-key="title"]').count() == 1
    assert page.evaluate("document.body.getAttribute('data-density')") == "comfortable"
    assert errors == []


def test_the_empty_state_says_what_to_do_and_resets(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, _api(job_keys))
    page.locator("#jobs-controls summary").click()
    page.locator("#f-search").fill("rien-ne-correspond")
    page.wait_for_selector("#jobs-empty:not([hidden])")
    assert "rien trouvé pour ces filtres" in page.locator("#jobs-empty-text").inner_text()
    page.locator("#jobs-empty-reset").click()
    page.wait_for_function(f"() => document.querySelectorAll('{ROWS}').length > 1")
    assert page.locator("#f-search").input_value() == ""
    assert errors == []


def test_phone_width_has_no_horizontal_scroll_and_thumb_sized_actions(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, _api(job_keys), viewport=(390, 844))
    assert page.evaluate(OVERFLOW) <= 0
    page.locator(ROWS).first.locator(".expand").click()
    page.wait_for_selector("#jobs-body tr.details .row-actions")
    heights = page.evaluate(
        "Array.from(document.querySelectorAll('#jobs-body tr.details .row-actions .button'))"
        ".map(b => b.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= 44
    assert page.evaluate(OVERFLOW) <= 0
    assert errors == []


def test_light_theme_is_one_click_away_and_remembered(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, _api(job_keys))
    theme = "document.documentElement.getAttribute('data-theme')"
    before = page.evaluate(theme)  # the system setting (Playwright emulates light by default)
    page.locator("#theme-toggle").click()
    after = page.evaluate(theme)
    assert {before, after} == {"dark", "light"}
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg == ("rgb(252, 252, 253)" if after == "light" else "rgb(17, 17, 19)")
    assert page.evaluate("localStorage.getItem('job-match-theme')") == after
    assert errors == []
