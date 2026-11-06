"""Auto-archive (ADR 0028) in a real browser: an « À candidater » application kept 16 days
ago, or on an offer published 21 days ago, leaves the Kanban, the table and the sidebar count;
« Afficher les archivées » (in the hash) folds them under the view with a grey badge, the
reason and « Réactiver »; the record says why; both themes, phone width."""
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

NOW = datetime.now(UTC)


def _ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


# Offer 2 was published 21 days ago (the page inlines its data: the script sets it).
SETUP = """
(() => { const parse = JSON.parse; JSON.parse = function (t) {
  const v = parse.apply(this, arguments);
  if (v && Array.isArray(v.jobs) && v.jobs.length > 2 && !v.__jm) {
    v.__jm = true;
    v.jobs[2].published_at = "PUBLISHED_AT";
  }
  return v; }; })();
""".replace("PUBLISHED_AT", _ago(21))


SENT = "france_travail:SENT40"


def _app(key, status="to_apply", **fields):
    row = {"job_key": key, "status": status, "applied_at": None, "follow_up_at": None,
           "note": None, "cv_url": None, "updated_at": _ago(1), "sent_documents_version": None,
           "reactivated_at": None}
    row.update(fields)
    return row


def _decision(key, days_ago, label="good_fit"):
    return {"job_key": key, "label": label, "created_at": _ago(days_ago)}


def _api(keys):
    """keys[0]: kept 16 days ago (archived); keys[1]: kept 3 days ago (live); keys[2]: kept
    yesterday on an offer published 21 days ago (archived); SENT: sent 40 days ago, its offer no
    longer on the page (never archived)."""
    apps = [_app(keys[0]), _app(keys[1]), _app(keys[2]),
            _app(SENT, "applied", applied_at="2026-10-01")]
    decisions = [_decision(keys[0], 16), _decision(keys[1], 3), _decision(keys[2], 1),
                 _decision(SENT, 40)]
    documents = [{"job_key": keys[0], "version": 1, "status": "ready", "language": "fr",
                  "error_code": None, "updated_at": _ago(10), "files": False}]
    return {"applications": apps, "decisions": decisions, "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": documents, "documents_budget": None}


def _reactivate_route(key):
    body = json.dumps({"application": _app(key, reactivated_at=NOW.isoformat(),
                                           updated_at=NOW.isoformat())})
    headers = {"content-type": "application/json"}
    return {
        ("POST", f"/api/applications/{quote(key, safe='')}/reactivate"): (200, headers, body),
        # the ready document's links prefetch their bundle on hover (ADR 0019): answered
        ("GET", f"/api/documents/{quote(key, safe='')}/v1/content.json"): (200, headers, "{}"),
    }


def _open(open_dashboard, keys, **kw):
    page, errors = open_dashboard(_api(keys), init_script=SETUP, hash_="#candidatures", **kw)
    page.wait_for_function("document.querySelectorAll('#kb-board .kb-card').length > 0")
    return page, errors


def _count(page):
    return page.locator('.sidebar [data-count="candidatures"]').first.inner_text()


def test_archived_applications_leave_the_board_the_table_and_the_count(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, job_keys)
    col = page.locator('#kb-board .kb-col[data-status="to_apply"]')
    assert col.locator(".kb-card").count() == 1
    assert col.locator(f'.kb-card[data-key="{job_keys[1]}"]').count() == 1
    assert _count(page) == "2"  # the live one and the sent one
    assert "2 dossiers suivis" in page.locator("#apps-stats").inner_text()
    toggle = page.locator("#apps-show-archived")
    assert toggle.inner_text() == "Afficher les archivées (2)"
    assert toggle.get_attribute("aria-pressed") == "false"
    assert page.locator("#kb-archived").is_hidden()
    # the table: the archived rows are not among the rows, « Générer » does not count them
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    rows = [r.get_attribute("data-key") for r in page.locator("#kb-table tbody tr").all()]
    assert sorted(rows) == sorted([job_keys[1], SENT])
    assert page.locator("#apps-generate-missing").inner_text() == "Générer les manquants (2)"
    assert errors == []


def test_the_filter_shows_the_folded_section_with_badge_and_reason(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, job_keys)
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    page.click("#apps-show-archived")
    page.wait_for_selector("#kb-archived-box")
    assert "archived=1" in page.evaluate("location.hash")
    assert page.locator("#apps-show-archived").get_attribute("aria-pressed") == "true"
    assert page.locator("#apps-show-archived").inner_text() == "Masquer les archivées (2)"
    box = page.locator("#kb-archived-box")
    assert box.locator("summary .tab-count").inner_text() == "2"
    archived = box.locator("tbody tr")
    # oldest first: the offer published 21 days ago, then the one kept 16 days ago
    assert [r.get_attribute("data-key") for r in archived.all()] == [job_keys[2], job_keys[0]]
    kept = archived.nth(1)
    assert kept.locator(".status-badge.is-archived").inner_text() == "Archivée"
    assert kept.locator(".kb-archived-reason").inner_text() == "gardée il y a 16 jours"
    assert archived.first.locator(".kb-archived-reason").inner_text() == "publiée il y a 21 jours"
    # the existing documents stay downloadable; nothing to generate, nothing to apply to
    assert kept.locator(".doc-cell a").count() >= 1
    assert box.locator("button.apps-apply").count() == 0
    assert box.locator("button.apps-reactivate").count() == 2
    assert page.locator("#kb-archived-box").get_attribute("open") is not None  # opened on click
    # a reload with the hash keeps the filter and the table view
    page.goto(page.url)
    page.wait_for_selector("#kb-archived-box")
    assert page.locator("#apps-show-archived").get_attribute("aria-pressed") == "true"
    page.click("#apps-show-archived")
    assert "archived" not in page.evaluate("location.hash")
    assert page.locator("#kb-archived").is_hidden()
    assert errors == []


def test_reactiver_puts_the_application_back_and_the_record_says_why(open_dashboard, job_keys):
    key = job_keys[0]
    page, errors = _open(open_dashboard, job_keys, routes=_reactivate_route(key))
    page.click("#apps-show-archived")
    page.wait_for_selector("#kb-archived-box")
    # the record of an archived application: the badge with the reason, « Réactiver » in the foot
    page.locator(f'#kb-archived-box tr[data-key="{key}"] .apps-title button').click()
    page.wait_for_selector("#record-title")
    badge = page.locator("#record .status-badge.is-archived")
    assert badge.inner_text() == "Archivée · gardée il y a 16 jours"
    assert page.locator("#record .record-foot button", has_text="Réactiver").count() == 1
    assert page.locator("#record .record-foot button", has_text="Candidature envoyée").count() == 0
    page.locator(f'#kb-archived-box tr[data-key="{key}"] button.apps-reactivate').click()
    page.wait_for_function(
        "() => document.querySelectorAll('#kb-archived-box tbody tr').length === 1")
    posts = [c for c in page.api_calls if c[0] == "POST"]
    assert posts == [("POST", f"/api/applications/{quote(key, safe='')}/reactivate")]
    assert "Réactivée" in page.locator("#toast").inner_text()
    col = page.locator('#kb-board .kb-col[data-status="to_apply"]')
    assert col.locator(f'.kb-card[data-key="{key}"]').count() == 1
    assert _count(page) == "3"
    assert page.locator("#apps-show-archived").inner_text() == "Masquer les archivées (1)"
    assert page.locator("#record .status-badge.is-archived").count() == 0
    assert errors == []


def test_badge_reads_in_both_themes_and_at_phone_width(open_dashboard, job_keys):
    for viewport in ((1440, 900), (390, 844)):
        page, errors = _open(open_dashboard, job_keys, viewport=viewport)
        page.click("#apps-show-archived")
        page.wait_for_selector("#kb-archived-box .status-badge.is-archived")
        for _ in range(2):
            badge = page.locator("#kb-archived-box .status-badge.is-archived").first
            colors = badge.evaluate(
                "n => { const s = getComputedStyle(n); return [s.color, s.backgroundColor]; }")
            assert colors[0] != colors[1] and colors[1] != "rgba(0, 0, 0, 0)", colors
            assert badge.is_visible()
            box = page.locator("#kb-archived-box").bounding_box()
            assert box["width"] <= viewport[0]
            assert page.evaluate("document.documentElement.scrollWidth") <= viewport[0]
            react = page.locator("#kb-archived-box button.apps-reactivate").first
            assert react.bounding_box()["height"] >= 28
            page.locator("#theme-toggle").click()
            page.wait_for_timeout(50)
        assert errors == []
