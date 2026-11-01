"""Candidatures in a real browser: the Kanban and the table with an application in every board
status, and 0 console errors (the M26 production bug: the board's status menu was shadowed by
the Offres status filter, and the view came up empty). Then the isolation: one broken card is
logged and replaced, the others show.
"""

STATUSES = ["to_apply", "applied", "interview", "rejected"]
SENTINEL = "1999-12-31"  # the follow_up_at the fault injection throws on
HAS_CARDS = "document.querySelectorAll('#kb-board .kb-card').length > 0"


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
        {"job_key": keys[0], "version": 2, "status": "ready", "language": "fr",
         "error_code": None, "updated_at": "2026-10-20T09:00:00Z", "files": True},
        {"job_key": keys[1], "version": 1, "status": "failed", "language": "fr",
         "error_code": "invented_number", "updated_at": "2026-10-20T09:00:00Z", "files": False},
    ]
    run = {"id": 1, "started_at": "2026-10-20T07:30:00Z", "finished_at": "2026-10-20T07:31:00Z",
           "outcome": "ok", "http_status": None, "provider": "anthropic",
           "counters": {"scored": 3, "cached": 1}}
    return {"applications": apps, "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [run], "documents": documents}


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
    assert "Relances dues (1)" in page.locator("#kb-due").inner_text()
    assert page.locator("#kb-board .kb-card", has_text="offre plus affichée").count() == 1
    assert page.locator("#kb-board .kb-card-broken").count() == 0
    assert errors == []


def test_table_shows_every_row_without_console_errors(open_dashboard, job_keys):
    page, errors = _open_candidatures(open_dashboard, _api(job_keys))
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    assert page.locator("#kb-board").is_hidden()
    assert page.locator("#kb-table tbody tr").count() == 4
    menus = page.locator("#kb-table select.kb-status")
    assert sorted(m.input_value() for m in menus.all()) == sorted(STATUSES)
    assert page.locator("#kb-table tbody tr", has_text="offre plus affichée").count() == 1
    assert page.locator("#kb-table th").count() == 8
    # the ready version: PDF + DOCX for the CV and the letter; the failed one: a badge per cell
    assert page.locator("#kb-table a[download]").count() == 4
    assert page.locator("#kb-table .doc-badge", has_text="Échec").count() == 2
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
    page.wait_for_function("!document.getElementById('ai-run-now').disabled")
    assert not page.locator("#docs-run-now").is_disabled()
    assert page.locator("#ai-runs-list .run-ai").count() == 1
    assert errors == []
