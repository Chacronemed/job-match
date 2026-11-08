"""IMPECCABLE_AUDIT.md P1 fixes in a real browser: the handled rows' scores pass AA in both
themes (O1), and Candidatures says the tracking is unavailable instead of counting zero (C1)."""

import json

import pytest

ROWS = "#jobs-body tr.row"
DARK = "try { localStorage.setItem('job-match-theme', 'dark') } catch (e) {}"
LIGHT = "try { localStorage.setItem('job-match-theme', 'light') } catch (e) {}"


def _app(key, status, applied=None):
    return {"job_key": key, "status": status, "applied_at": applied, "follow_up_at": None,
            "interview_at": None, "note": None, "cv_url": None,
            "updated_at": "2026-10-20T08:00:00Z", "sent_documents_version": None}


def _api(keys):
    return {"applications": [_app(keys[0], "to_apply"), _app(keys[1], "applied", "2026-10-19")],
            "decisions": [], "skill_overrides": [], "ai_verdicts": [], "ai_runs": [],
            "documents": [], "documents_budget": None}


@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_handled_rows_keep_aa_scores_in_both_themes(open_dashboard, job_keys, contrast, theme):
    page, errors = open_dashboard(_api(job_keys), hash_="#offres", init_script=theme)
    page.wait_for_selector(f"{ROWS}.is-handled")
    page.wait_for_function("() => !document.getElementById('record').hidden")
    page.wait_for_timeout(300)  # past any fade
    handled = contrast(page, f"{ROWS}.is-handled .score-n, {ROWS}.is-handled .score-tag")
    assert len(handled) >= 4
    low = [c for c in handled if c[1] < 4.5]
    assert low == []
    assert errors == []


def test_candidatures_without_the_tracking_say_unknown_never_zero(open_dashboard, job_keys):
    page, errors = open_dashboard(lambda: None, hash_="#candidatures",
                                  routes={("GET", "/api/applications"): (500, {}, "boom")})
    page.wait_for_function("() => window.JM.track.status === 'error'")
    stats = page.locator("#apps-stats").inner_text()
    assert "suivi indisponible" in stats and "0" not in stats
    assert not page.locator("#kb-board").is_visible()
    assert page.locator(".kb-empty:visible").count() == 0
    note = page.locator("#kb-off")
    assert note.is_visible() and "rien n’est effacé" in note.inner_text()
    assert "hébergé" not in note.inner_text()
    assert page.locator("#apps-due-chip").is_hidden()
    side = page.locator('.nav-item [data-count="candidatures"]').inner_text()
    assert side == "—"
    assert [e for e in errors if "500" not in e] == []


# ---------- Tri (IMPECCABLE_AUDIT T1, T5, T7 and §8 « Aujourd'hui ») ----------

TRI_READY = ("() => window.JM.track.status === 'ready'"
             " && document.querySelector('#tri-stage .tcard:not(.is-next)')")


def _empty_api():
    return {"applications": [], "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": [], "documents_budget": None}


def _echo(route, request):
    key = request.url.rsplit("/", 1)[1]
    status = "ignored" if '"ignored"' in (request.post_data or "") else "to_apply"
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"application": {"job_key": key, "status": status}}))


def _open_tri(open_dashboard, api, viewport=(1440, 900)):
    page, errors = open_dashboard(api, hash_="#tri", viewport=viewport)
    page.route("**/api/applications/*", _echo)
    page.decisions = []

    def decide(route, request):
        page.decisions.append(request.post_data)
        route.fulfill(status=200, content_type="application/json", body='{"decision": {"id": 1}}')
    page.route("**/api/decisions", decide)
    return page, errors


def test_the_end_of_the_tri_asks_the_last_reason_and_lists_today(open_dashboard, job_keys):
    page, errors = _open_tri(open_dashboard, _empty_api())
    page.wait_for_function(TRI_READY)
    for i in range(3):
        page.keyboard.press("ArrowLeft")
        page.wait_for_function(f"() => window.JM.tri.pos === {i + 1}")
    end = page.locator("#tri-end")
    page.wait_for_function("() => !document.getElementById('tri-end').hidden")
    assert end.locator("h2").inner_text() == "Tri terminé"
    # the last drop's reason, on the end screen, with the same keys 1–4
    assert "Dernière offre écartée" in end.locator(".tri-end-reasons").inner_text()
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/decisions")
                             and "too_senior" in (r.post_data or "")):
        page.keyboard.press("2")
    page.wait_for_function("() => !document.querySelector('#tri-end .tri-end-reasons')")
    # « Aujourd'hui »: four lines, real counts, each a link
    lines = end.locator(".today-list li")
    assert lines.count() == 4
    assert lines.nth(0).inner_text().split("\n")[0] == "0"
    assert lines.nth(0).locator("a").get_attribute("href") == "#tri"
    assert "offres déjà triées" in end.locator(".today-why").inner_text()
    # the end screen sits under the progress, not at the bottom of an empty stage
    top = end.bounding_box()["y"]
    assert top < 300
    assert errors == []


def test_an_empty_tri_says_why_and_the_counts_of_the_day(open_dashboard, job_keys):
    apps = [_app(k, "ignored") for k in job_keys]
    api = dict(_empty_api(), applications=apps)
    page, errors = _open_tri(open_dashboard, api)
    page.wait_for_function("() => !document.getElementById('tri-end').hidden")
    end = page.locator("#tri-end")
    assert end.locator("h2").inner_text() == "Rien à trier"
    assert end.locator(".tri-end-reasons").count() == 0
    assert "3 offres déjà triées" in end.locator(".today-why").inner_text()
    assert errors == []


def test_without_the_tracking_today_says_unknown(open_dashboard, job_keys):
    page, errors = open_dashboard(lambda: None, hash_="#tri",
                                  routes={("GET", "/api/applications"): (500, {}, "boom")})
    page.wait_for_function("() => window.JM.track.status === 'error'")
    # the Tri keeps the cards (read only) and the banner says why; no second note
    assert page.locator("#tri-off").is_hidden()
    assert page.locator("#track-banner").is_visible()


def test_a_long_title_is_clamped_on_the_tri_card(open_dashboard, job_keys):
    long_title = ("Ingénieur·e DevOps / SRE plateforme cloud-native Kubernetes multi-région "
                  "(Terraform, ArgoCD, Prometheus, GitLab CI) — équipe Infrastructure & "
                  "Fiabilité, poste basé à Saint-Quentin-en-Yvelines, hybride 2 j/semaine")
    page, errors = _open_tri(open_dashboard, _empty_api(), viewport=(390, 844))
    page.wait_for_function(TRI_READY)
    page.evaluate("t => { document.querySelector("
                  "'#tri-stage .tcard:not(.is-next) .tcard-open').textContent = t; }", long_title)
    box = page.locator("#tri-stage .tcard:not(.is-next) .tcard-open").bounding_box()
    line = page.evaluate("parseFloat(getComputedStyle(document.querySelector("
                         "'#tri-stage .tcard:not(.is-next) .tcard-open')).lineHeight)")
    assert box["height"] <= line * 3 + 2
    assert errors == []


# ---------- Offres (IMPECCABLE_AUDIT O2, O3, O4, O6, O7, O8, O11, O12) ----------

def test_offres_has_one_primary_and_says_the_drop(open_dashboard, job_keys):
    page, errors = open_dashboard(_empty_api(), hash_="#offres")
    page.wait_for_selector(ROWS)
    page.wait_for_function("() => !document.getElementById('record').hidden")
    visible_primaries = page.locator(
        "#panel-offres .button.primary:visible, #record .button.primary:visible")
    assert visible_primaries.count() == 1
    assert "primary" not in page.locator("#offres-to-tri").get_attribute("class")
    drop = page.locator("#record .record-foot .record-drop")
    assert drop.inner_text().strip() == "Écarter"
    # monograms come from letters only: « Beta <b>Corp</b> » reads BC
    beta = page.locator(f"{ROWS}", has_text="Ingénieur DevOps").first
    assert beta.locator(".logo").inner_text() == "BC"
    assert errors == []


def test_offres_on_a_phone_sorts_with_a_select_and_44px_targets(open_dashboard, job_keys):
    page, errors = open_dashboard(_empty_api(), hash_="#offres", viewport=(390, 844))
    page.wait_for_selector(ROWS)
    assert page.locator("#jobs-table thead").is_hidden()
    sort = page.locator("#f-sort-m")
    assert sort.is_visible() and sort.input_value() == "score-desc"
    for sel in ("#panel-offres .searchbox", "#f-sort-m", "#offres-to-tri"):
        assert page.locator(sel).bounding_box()["height"] >= 44, sel
    sort.select_option("company-asc")
    page.wait_for_function("() => location.hash.includes('company')")
    companies = page.locator(f"{ROWS} .row-meta").all_inner_texts()
    assert companies == sorted(companies, key=str.lower)
    assert errors == []


# ---------- Statistiques (IMPECCABLE_AUDIT S1) ----------

def test_few_dated_events_show_a_table_not_full_height_bars(open_dashboard, job_keys):
    page, errors = open_dashboard(_api(job_keys), hash_="#statistiques")
    page.wait_for_function("() => document.querySelector('#stats-body .stats-funnel') !== null")
    weeks = page.locator("#h-stats-weeks").locator("xpath=ancestor::section[1]")
    assert weeks.locator("svg.week-chart").count() == 0
    assert "le graphe apparaît à partir de 5" in weeks.inner_text()
    assert weeks.locator("table.stats-table tbody tr").count() >= 1
    assert errors == []
