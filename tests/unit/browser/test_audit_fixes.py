"""IMPECCABLE_AUDIT.md P1 fixes in a real browser: the handled rows' scores pass AA in both
themes (O1), and Candidatures says the tracking is unavailable instead of counting zero (C1)."""

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
