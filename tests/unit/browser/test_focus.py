"""The Focus layout (docs/design/JOB_MATCH_FOCUS.md) in a real browser: the Offres split view at
1440 (the first offer selected without taking the focus, a click selects another and keeps
the filters), the drawer at 1024, the full-screen record with its back button at 390, the
record's footer actions, the section chips, the unknown experience said as such, and the
tracking error state."""

import json

ROWS = "#jobs-body tr.row"
READY = "() => document.querySelector('#track-banner').hidden && window.JM.track.status === 'ready'"
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


def _api():
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


def _open(open_dashboard, viewport=(1440, 900), hash_="#offres", **kw):
    page, errors = open_dashboard(_api(), hash_=hash_, viewport=viewport, **kw)
    page.route("**/api/applications/*", _echo)
    page.wait_for_selector(ROWS)
    page.wait_for_function(READY)
    return page, errors


def test_split_view_selects_the_first_offer_without_taking_the_focus(open_dashboard, job_keys):
    page, errors = _open(open_dashboard)
    page.wait_for_function("() => !document.getElementById('record').hidden")
    assert page.evaluate("document.getElementById('record').parentElement.id") == "offres-split"
    assert page.evaluate("document.body.classList.contains('record-split')")
    first = page.locator(ROWS).first
    assert "is-selected" in first.get_attribute("class")
    assert page.locator(f"{ROWS}.is-selected").count() == 1
    title = first.locator(".title-text > span").inner_text()
    assert page.locator("#record-title").inner_text() == title
    assert f"fiche={job_keys[0]}" in page.evaluate("decodeURIComponent(location.hash)")
    # the focus stays where it was: j/k start from the list, not from the record
    assert page.evaluate("document.activeElement === document.body")
    # the split keeps the list and the record side by side, the record ~420 px wide
    width = page.evaluate("document.getElementById('record').getBoundingClientRect().width")
    assert 400 <= width <= 440
    right = page.evaluate("document.getElementById('record').getBoundingClientRect().right")
    assert right <= 1440
    assert errors == []


def test_a_click_selects_another_offer_and_keeps_the_filters(open_dashboard, job_keys):
    page, errors = _open(open_dashboard)
    page.locator("#f-search").fill("devops")
    page.wait_for_function(f"() => document.querySelectorAll('{ROWS}').length === 1")
    row = page.locator(ROWS).first
    key = row.get_attribute("data-key")
    row.click()
    page.wait_for_function(f"() => decodeURIComponent(location.hash).includes('fiche={key}')")
    assert page.locator("#record-title").inner_text() == "Ingénieur DevOps"
    assert "is-selected" in row.get_attribute("class")
    # the filters survive the selection, and the record took the focus (a user click)
    assert page.locator("#f-search").input_value() == "devops"
    assert page.locator(ROWS).count() == 1
    assert "q=devops" in page.evaluate("location.hash")
    assert page.evaluate("document.activeElement.id") == "record-title"
    # an unknown experience is said as such, never a number
    pills = page.locator("#record .record-tags .pill", has_text="Années non précisées")
    assert pills.count() == 1
    assert errors == []


def test_the_record_is_a_drawer_at_1024_and_escape_returns_to_the_row(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, viewport=(1024, 768))
    assert page.evaluate("document.getElementById('record').hidden")  # no automatic selection
    row = page.locator(ROWS).nth(1)
    row.click()
    page.wait_for_function("() => !document.getElementById('record').hidden")
    position = page.evaluate("getComputedStyle(document.getElementById('record')).position")
    assert position == "fixed"
    assert page.evaluate("document.getElementById('main').hasAttribute('inert')")
    assert page.evaluate("document.getElementById('record').parentElement.className") == "app"
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.getElementById('record').hidden")
    assert not page.evaluate("document.getElementById('main').hasAttribute('inert')")
    focused = page.evaluate("document.activeElement.getAttribute('data-key')")
    assert focused == row.get_attribute("data-key")
    assert errors == []


def test_phone_record_fills_the_screen_and_its_back_restores_the_list(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, viewport=(390, 844))
    assert page.evaluate("document.getElementById('record').hidden")
    rows = page.locator(ROWS)
    rows.nth(2).click()
    page.wait_for_function("() => !document.getElementById('record').hidden")
    rect = page.evaluate("(() => { const r = document.getElementById('record')"
                         ".getBoundingClientRect(); return [r.left, r.width, r.bottom]; })()")
    assert rect[0] == 0 and rect[1] == 390 and rect[2] <= 844 - 64  # above the tab bar
    assert page.evaluate(OVERFLOW) <= 0
    back = page.locator("#record .record-back")
    assert back.is_visible() and back.inner_text().strip() == "Retour aux 3 offres"
    close = page.evaluate(
        "getComputedStyle(document.querySelector('#record .record-close')).display")
    assert close == "none"
    foot = page.locator("#record .record-foot .button")
    heights = [b.bounding_box()["height"] for b in foot.all()]
    assert heights and min(heights) >= 44
    back.click()
    page.wait_for_function("() => document.getElementById('record').hidden")
    assert page.locator(ROWS).count() == 3
    focused = page.evaluate("document.activeElement.getAttribute('data-key')")
    assert focused == rows.nth(2).get_attribute("data-key")
    assert errors == []


def test_the_record_footer_keeps_the_offer_and_follows_its_status(open_dashboard, job_keys):
    page, errors = _open(open_dashboard)
    page.wait_for_function("() => !document.getElementById('record').hidden")
    foot = page.locator("#record .record-foot")
    assert foot.locator("a", has_text="Voir l’annonce").get_attribute("target") == "_blank"
    foot.get_by_role("button", name="Garder").click()
    key = job_keys[0]
    page.wait_for_selector(f'{ROWS}[data-key="{key}"].st-to_apply')
    assert "À candidater" in page.locator("#toast").inner_text()
    # the footer follows: the next step is to say it was sent; the row keeps its selection
    assert foot.get_by_role("button", name="Candidature envoyée").count() == 1
    assert foot.get_by_role("button", name="Garder").count() == 0
    assert "is-selected" in page.locator(f'{ROWS}[data-key="{key}"]').get_attribute("class")
    foot.get_by_role("button", name="Écarter l’offre").click()
    page.wait_for_selector(f'{ROWS}[data-key="{key}"].st-ignored')
    assert foot.get_by_role("button", name="Garder").count() == 1
    assert errors == []


def test_section_chips_toggle_and_toutes_puts_every_section_back(open_dashboard, job_keys):
    page, errors = _open(open_dashboard)
    assert page.locator("#section-all").get_attribute("aria-pressed") == "true"
    assert page.locator("#kpi-all").inner_text() == "3"
    page.locator('.chip[data-section="strong"]').click()
    page.wait_for_function(f"() => document.querySelectorAll('{ROWS}').length === 2")
    assert page.locator("#section-all").get_attribute("aria-pressed") == "false"
    assert "hide=strong" in page.evaluate("location.hash")
    page.locator("#section-all").click()
    page.wait_for_function(f"() => document.querySelectorAll('{ROWS}').length === 3")
    assert page.locator('.chip[data-section="strong"]').get_attribute("aria-pressed") == "true"
    assert "hide=" not in page.evaluate("location.hash")
    # the sort bar still sorts, from the list's header
    page.locator('th button[data-key="company"]').click()
    assert page.locator('th[aria-sort="ascending"] button[data-key="company"]').count() == 1
    assert errors == []


def test_a_tracking_error_is_said_and_leaves_only_the_offer_link(open_dashboard, job_keys):
    page, errors = open_dashboard(lambda: None, hash_="#offres",
                                  routes={("GET", "/api/applications"): (500, {}, "boom")})
    page.wait_for_selector(ROWS)
    page.wait_for_function("() => window.JM.track.status === 'error'")
    banner = page.locator("#track-banner")
    assert banner.is_visible() and "n’a pas pu être chargé" in banner.inner_text()
    assert page.locator("#track-retry").is_visible()
    page.wait_for_function("() => !document.getElementById('record').hidden")
    foot = page.locator("#record .record-foot")
    assert foot.locator("a", has_text="Voir l’annonce").count() == 1
    assert foot.locator("button").count() == 0
    assert "Suivi indisponible" in page.locator("#record .track-off").inner_text()


# ---------- Tri ----------

TRI_READY = ("() => window.JM.track.status === 'ready'"
             " && document.querySelector('#tri-stage .tcard:not(.is-next)')")
SECOND = "() => document.querySelector('#tri-count').textContent === 'Offre 2 sur 3'"


def _open_tri(open_dashboard, viewport=(1440, 900)):
    page, errors = open_dashboard(_api(), hash_="#tri", viewport=viewport)
    page.route("**/api/applications/*", _echo)
    page.route("**/api/decisions", lambda r: r.fulfill(
        status=200, content_type="application/json", body='{"decision": {"id": 1}}'))
    page.wait_for_function(TRI_READY)
    return page, errors


def test_tri_card_is_centred_wide_and_counts_the_queue(open_dashboard, job_keys):
    page, errors = _open_tri(open_dashboard)
    card = page.locator("#tri-stage .tcard:not(.is-next)")
    box = card.bounding_box()
    assert 680 <= box["width"] <= 760
    main = page.locator("#main").bounding_box()
    centre = box["x"] + box["width"] / 2 - main["x"]
    assert abs(centre - main["width"] / 2) < 8
    assert page.locator("#tri-count").inner_text() == "Offre 1 sur 3"
    assert "2 restantes après celle-ci" in page.locator("#tri-left").inner_text()
    # the score is the row's own, the band its word, the ledger open with its lines
    assert card.locator(".score-big .num").inner_text() == "85"
    assert card.locator(".tcard-top .band").inner_text().strip() == "Forte"
    assert card.locator(".ledger.is-open .ledger-total-n").inner_text() == "85"
    assert "Relevé du score" in card.locator(".ledger-sum").inner_text()
    assert card.locator(".fact", has_text="2 ans requis").count() == 1
    # → keeps: the next card comes up, the undo wakes
    page.keyboard.press("ArrowRight")
    page.wait_for_function(SECOND)
    assert not page.locator("#tri-undo").is_disabled()
    assert page.evaluate(f"window.JM.track.apps[{json.dumps(job_keys[0])}].status") == "to_apply"
    # ↵ opens this exact offer's record, said as the one being triaged
    page.keyboard.press("Enter")
    page.wait_for_function("() => !document.getElementById('record').hidden")
    assert page.locator("#record .record-crumb").text_content() == "Offre en cours de tri"
    assert page.locator("#record-title").inner_text() == card.locator(".tcard-open").inner_text()
    assert errors == []


def test_tri_on_a_phone_keeps_its_actions_above_the_tab_bar(open_dashboard, job_keys):
    page, errors = _open_tri(open_dashboard, viewport=(390, 844))
    assert page.evaluate(OVERFLOW) <= 0
    bar = page.locator("#tri-bar").bounding_box()
    tabbar = page.locator("#tabbar").bounding_box()
    assert bar["y"] + bar["height"] <= tabbar["y"] + 1
    for button in page.locator("#tri-controls .tbtn").all():
        assert button.bounding_box()["height"] >= 44
    card = page.locator("#tri-stage .tcard:not(.is-next)").bounding_box()
    assert card["x"] >= 0 and card["x"] + card["width"] <= 390
    assert card["y"] + card["height"] <= bar["y"] + 1
    # the unknown experience of the stretch offer is said, not guessed
    page.locator("#tri-drop").click()
    page.wait_for_function(SECOND)
    assert page.locator("#tri-reasons-bar").is_visible()
    assert errors == []
