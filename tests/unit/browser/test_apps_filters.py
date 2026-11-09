"""Candidatures filters in a real browser: « À postuler » (default) · « Envoyées » ·
« Entretiens » · « Refus » · « Tout », each with the real count of the rows it shows, kept in
the hash across a reload; « Expirée » applications leave the lists with the archived ones
(badge, reason, no « Regénérer »); badge, reason and menu never overlap, both themes, 390 px."""

# offer 1 is closed: its « À candidater » application is « Expirée »
SETUP = """
(() => { const parse = JSON.parse; JSON.parse = function (t) {
  const v = parse.apply(this, arguments);
  if (v && Array.isArray(v.jobs) && v.jobs.length > 2 && !v.__jm) {
    v.__jm = true;
    v.jobs[1].closed = true;
  }
  return v; }; })();
"""
HAS_TABLE = "() => document.querySelector('#kb-table table.data.apps, #kb-table .kb-empty')"
EXPECTED = {"postuler": 1, "envoyees": 1, "entretiens": 1, "refus": 2, "tout": 5}


def _app(key, status, **fields):
    row = {"job_key": key, "status": status, "applied_at": None, "follow_up_at": None,
           "note": None, "cv_url": None, "updated_at": "2026-10-20T08:00:00Z",
           "sent_documents_version": None, "reactivated_at": None}
    row.update(fields)
    return row


def _api(keys):
    apps = [_app(keys[0], "to_apply"), _app(keys[1], "to_apply"),
            _app(keys[2], "applied", applied_at="2026-10-15"),
            _app("france_travail:GONE_I", "interview", applied_at="2026-10-10"),
            _app("france_travail:GONE_R1", "rejected"), _app("france_travail:GONE_R2", "rejected")]
    documents = [{"job_key": keys[1], "version": 1, "status": "failed", "language": "fr",
                  "error_code": "invented_number", "updated_at": "2026-10-20T09:00:00Z",
                  "files": False}]
    return {"applications": apps, "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": documents, "documents_budget": None}


def _open(open_dashboard, keys, hash_="#candidatures", **kw):
    page, errors = open_dashboard(_api(keys), init_script=SETUP, hash_=hash_, **kw)
    page.wait_for_selector("#apps-filter:not([hidden]) [data-filter]")
    return page, errors


def _segment(page, f):
    return page.locator(f'#apps-filter [data-filter="{f}"]')


def test_each_filter_counts_the_rows_it_shows_in_the_table_and_the_kanban(open_dashboard,
                                                                          job_keys):
    page, errors = _open(open_dashboard, job_keys)
    assert _segment(page, "postuler").get_attribute("aria-pressed") == "true"
    texts = [b.inner_text() for b in page.locator("#apps-filter [data-filter]").all()]
    assert texts == ["À postuler 1", "Envoyées 1", "Entretiens 1", "Refus 2", "Tout 5"]
    for view in ("table", "kanban"):
        page.click(f"#apps-view-{view}")
        for f, n in EXPECTED.items():
            _segment(page, f).click()
            assert _segment(page, f).get_attribute("aria-pressed") == "true"
            count = int(_segment(page, f).locator(".tab-count").inner_text())
            shown = (page.locator("#kb-table tbody tr") if view == "table"
                     else page.locator("#kb-board .kb-card"))
            assert count == n == shown.count(), (view, f)
            assert ("f=" + f in page.evaluate("location.hash")) == (f != "postuler")
    # the subtitle: what is left to do, not « N dossiers suivis »
    stats = page.locator("#apps-stats").inner_text()
    assert "1 à postuler" in stats and "0 relance due" in stats and "1 entretien" in stats
    assert "dossier" not in stats
    # the expired one counts nowhere: 5 on the board, not 6
    assert page.locator('.sidebar [data-count="candidatures"]').first.inner_text() == "5"
    assert errors == []


def test_the_filter_is_kept_in_the_hash_across_a_reload(open_dashboard, job_keys):
    page, errors = _open(open_dashboard, job_keys)
    page.click("#apps-view-table")
    _segment(page, "refus").click()
    assert page.evaluate("location.hash") == "#candidatures?f=refus&view=table"
    page.reload()
    page.wait_for_selector("#apps-filter:not([hidden]) [data-filter]")
    page.wait_for_function(HAS_TABLE)
    assert _segment(page, "refus").get_attribute("aria-pressed") == "true"
    assert page.locator("#kb-table tbody tr").count() == 2
    assert errors == []


def test_an_expired_application_is_hidden_by_default_and_shown_with_the_archived(open_dashboard,
                                                                                 job_keys):
    page, errors = _open(open_dashboard, job_keys, hash_="#candidatures?f=tout&view=table")
    page.wait_for_function(HAS_TABLE)
    assert page.locator(f'#kb-table tr[data-key="{job_keys[1]}"]').count() == 0
    assert page.locator(".status-badge.is-expired").count() == 0
    toggle = page.locator("#apps-show-archived")
    assert toggle.inner_text() == "Afficher les archivées (1)"
    toggle.click()
    row = page.locator(f'#kb-archived-box tr[data-key="{job_keys[1]}"]')
    assert row.locator(".status-badge.is-expired").inner_text() == "Expirée"
    assert row.locator(".kb-archived-reason").inner_text() == "offre expirée"
    # « Échec » on a closed offer: nothing to regenerate, it says why
    assert row.locator(".doc-badge", has_text="Échec").count() == 1
    assert row.locator("button", has_text="générer").count() == 0
    assert row.locator("button", has_text="Générer").count() == 0
    assert row.locator(".apps-expired-note").inner_text() == "Offre expirée"
    assert row.locator("button.apps-apply, button.apps-reactivate").count() == 0
    # the record says the same: no « Regénérer »
    row.locator(".apps-title button").click()
    page.wait_for_selector("#record-title")
    assert page.locator("#record .documents button", has_text="générer").count() == 0
    assert page.locator("#record .documents .apps-expired-note").inner_text() == "Offre expirée"
    assert errors == []


# Every pair of the cell's parts, and the cell against the next row: no intersection.
OVERLAPS = """(key) => {
  const row = document.querySelector(`#kb-archived-box tr[data-key="${key}"]`);
  const cell = row.querySelector('td.apps-status');
  const parts = [...cell.querySelectorAll('.status-badge, .kb-archived-reason, select')];
  const r = (n) => n.getBoundingClientRect();
  const hit = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5
    && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const out = [];
  parts.forEach((a, i) => parts.slice(i + 1).forEach((b) => {
    if (hit(r(a), r(b))) out.push(a.className + ' x ' + b.className);
  }));
  const c = r(cell);
  parts.forEach((p) => {
    const b = r(p);
    if (b.top < c.top - 0.5 || b.bottom > c.bottom + 0.5) out.push(p.className + ' outside');
  });
  return {parts: parts.length, out};
}"""


def test_badge_reason_and_menu_never_overlap_in_both_themes_and_at_390(open_dashboard,
                                                                         job_keys):
    for viewport in ((1440, 900), (390, 844)):
        page, errors = _open(open_dashboard, job_keys, hash_="#candidatures?view=table&archived=1",
                             viewport=viewport)
        page.wait_for_selector("#kb-archived-box .status-badge.is-expired")
        for _ in range(2):  # light, then dark
            res = page.evaluate(OVERLAPS, job_keys[1])
            assert res["parts"] == 3 and res["out"] == [], (viewport, res)
            badge = page.locator("#kb-archived-box .status-badge.is-expired")
            colors = badge.evaluate(
                "n => { const s = getComputedStyle(n); return [s.color, s.backgroundColor]; }")
            assert colors[0] != colors[1], colors
            assert page.evaluate("document.documentElement.scrollWidth") <= viewport[0]
            filt = page.locator("#apps-filter").bounding_box()
            assert filt["x"] >= 0 and filt["x"] + filt["width"] <= viewport[0]
            page.locator("#theme-toggle").click()
            page.wait_for_timeout(50)
        assert errors == []
