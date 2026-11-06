"""Statistiques in a real browser: every number comes from the snapshot and the tracking below,
computed by hand in the comments; the periods are cohorts of offers collected since
generated_at (2026-10-18 07:00 UTC) minus 30 / 90 days. Then the chart, both themes, the phone.
"""
import copy

import pytest

from job_match.config.schema import Settings
from job_match.dashboard.data import build_dashboard_data
from job_match.persistence.db import Database

# an arrow function: a bare expression would be eval'ed, which the page's CSP refuses
READY = "() => document.querySelector('#stats-body .stats-funnel') !== null"
# (key, source, company, collected day, unlisted skills); `listed` False = in `tracked`
LISTED = [
    ("france_travail:a1", "france_travail", "Acme", "2026-10-05", []),
    ("ats:a2", "ats", "Gamma", "2026-10-10", []),
    ("france_travail:a3", "france_travail", "Acme", "2026-10-15", []),
    ("france_travail:a4", "france_travail", "Beta", "2026-10-16", ["aws", "go"]),
    ("france_travail:a6", "france_travail", "Delta", "2026-10-17", []),
    ("france_travail:a7", "france_travail", "Delta", "2026-10-17", []),
    ("france_travail:a8", "france_travail", "Zeta", "2026-10-17", []),
    ("france_travail:a9", "france_travail", "Zeta", "2026-10-18", []),
]
TRACKED = [  # + closed
    ("ats:a5", "ats", "Gamma", "2026-08-20", ["aws"], True),   # 90 days only: expired
    ("ats:a10", "ats", "Acme", "2026-06-01", [], False),       # « Tout » only: archived
]


def _job(template, i, key, source, company, day, unlisted, closed=False):
    j = copy.deepcopy(template)
    j.update(id=1000 + i, key=key, group=None, source=source, company=company, closed=closed,
             collected_at=day + "T07:00:00+00:00", posted_at=day + "T07:00:00+00:00")
    j["why"] = {"skills": [], "unlisted": [{"name": n, "snippet": None} for n in unlisted],
                "lowered": [], "experience": None}
    return j


@pytest.fixture
def dashboard_data(seed_dashboard):
    with Database(path=":memory:") as db:
        seed = seed_dashboard(db)
        data = build_dashboard_data(db, Settings(), seed.now)
    tpl = data["jobs"][0]
    data["jobs"] = [_job(tpl, i, *row) for i, row in enumerate(LISTED)]
    data["tracked"] = [_job(tpl, 50 + i, *row) for i, row in enumerate(TRACKED)]
    return data, seed


def _app(key, status, applied=None, interview=None):
    return {"job_key": key, "status": status, "applied_at": applied, "follow_up_at": None,
            "interview_at": interview, "note": None, "cv_url": None,
            "updated_at": "2026-10-17T08:00:00Z", "sent_documents_version": None}


def _reply(key, day, kind, state="applied"):
    return {"message_id": f"<{key}-{kind}>", "received_at": day + "T10:00:00Z",
            "sender_domain": "x.test", "subject": "Re", "kind": kind, "confidence": 0.9,
            "interview_at": None, "proposed_key": key, "state": state, "applied_key": key,
            "applied_at": day + "T10:05:00Z", "ai_outcome": "ok"}


API = {
    "applications": [
        _app("france_travail:a1", "interview", "2026-10-08", "2026-10-20T09:00:00Z"),
        _app("ats:a2", "rejected", "2026-10-14"),
        _app("france_travail:a3", "applied", "2026-10-15"),
        _app("france_travail:a4", "to_apply"),
        _app("ats:a5", "to_apply"),
        _app("france_travail:a6", "ignored"),
        _app("france_travail:a7", "ignored"),
        _app("france_travail:a8", "ignored"),
        _app("ats:a10", "applied", "2026-06-05"),
        _app("france_travail:GONE", "rejected", "2026-05-01"),  # no offer in the snapshot
    ],
    "decisions": [
        {"job_key": k, "label": label, "created_at": at} for k, label, at in [
            ("france_travail:a1", "good_fit", "2026-10-06T09:00:00Z"),
            ("ats:a2", "good_fit", "2026-10-10T10:00:00Z"),
            ("france_travail:a3", "good_fit", "2026-10-15T08:00:00Z"),
            ("france_travail:a4", "good_fit", "2026-10-16T08:00:00Z"),
            ("france_travail:a6", "too_senior", "2026-10-17T08:00:00Z"),
            ("france_travail:a7", "off_topic", "2026-10-17T08:00:00Z"),
        ]
    ],
    "skill_overrides": [], "ai_verdicts": [], "ai_runs": [], "documents": [],
    "inbox": {"to_confirm": [], "history": [
        _reply("france_travail:a1", "2026-10-12", "entretien"),
        _reply("ats:a2", "2026-10-16", "refus"),
        _reply("france_travail:a3", "2026-10-16", "accuse_reception"),  # not a reply
    ]},
}


def _open(open_dashboard, hash_="#statistiques", **kw):
    page, errors = open_dashboard(API, hash_, **kw)
    page.wait_for_function(READY)
    return page, errors


def _funnel(page):
    return page.eval_on_selector_all(
        "#stats-body .funnel-row",
        "rows => rows.map(r => [r.dataset.stage, r.querySelector('.funnel-n').textContent,"
        " r.querySelector('.funnel-rate').textContent])")


def _tile(page, key):
    return page.locator(f'[data-tile="{key}"] .stats-tile-value').inner_text()


def _table(page, name):
    return page.eval_on_selector(
        f'table[data-table="{name}"]',
        "t => Array.from(t.tBodies[0].rows).map(r => Array.from(r.cells).map(c => c.textContent))")


def test_thirty_days_funnel_rates_delays_and_breakdowns(open_dashboard):
    page, errors = _open(open_dashboard)
    assert _funnel(page) == [
        ["seen", "8", ""],
        ["kept", "4", "50 % des vues"],
        ["sent", "3", "75 % des gardées"],
        ["replies", "2", "67 % des envoyées"],     # a1 entretien, a2 refus; a3's ack is not one
        ["interviews", "1", "33 % des envoyées"],
        ["refusals", "1", "33 % des envoyées"],
    ]
    assert _tile(page, "keep-send") == "2 jours"     # (2 + 4 + 0) / 3
    assert _tile(page, "send-reply") == "3 jours"    # (4 + 2) / 2
    assert _tile(page, "expired") == "0"
    assert _tile(page, "archived") == "0"
    reasons = page.eval_on_selector_all(
        ".rank-reasons .rank-row",
        "rs => rs.map(r => r.querySelector('.rank-label').textContent + '='"
        " + r.querySelector('.rank-n').textContent)")
    assert reasons == ["Hors sujet=1", "Trop senior=1",  # ties keep the Tri order
                       "Compétence manquante=0", "Lieu=0",
                       "Sans raison donnée=1"]
    skills = page.locator(".rank-skills .rank-label").all_inner_texts()
    assert skills == ["aws", "go"]
    assert _table(page, "h-stats-sources") == [["france_travail", "7", "3", "2"],
                                               ["ats", "1", "1", "1"]]
    assert _table(page, "h-stats-companies")[0] == ["Acme", "2", "2", "2"]
    assert "depuis le 18 sept." in page.locator("#stats-sub").inner_text()
    assert errors == []


def test_ninety_days_and_all_add_the_expired_the_archived_and_the_orphan(open_dashboard):
    page, errors = _open(open_dashboard)
    page.click('[data-period="90"]')
    assert page.evaluate("location.hash") == "#statistiques?p=90"
    assert _funnel(page)[:2] == [["seen", "9", ""], ["kept", "5", "56 % des vues"]]
    assert _tile(page, "expired") == "1"
    aws = page.locator(".rank-skills .rank-row").first
    assert aws.locator(".rank-n").inner_text() == "2"  # a4 and a5
    assert "1 gardée sans date de décision" in page.locator("#panel-statistiques").inner_text()
    page.click('[data-period="tout"]')
    stages = {s: n for s, n, _ in _funnel(page)}
    assert stages == {"seen": "11", "kept": "7", "sent": "5", "replies": "3",
                      "interviews": "1", "refusals": "2"}
    assert _tile(page, "archived") == "1"
    body = page.locator("#stats-body").inner_text()
    assert "1 candidature dont l’offre a quitté l’instantané" in body
    assert page.get_attribute('[data-period="tout"]', "aria-pressed") == "true"
    assert errors == []


def test_the_period_comes_back_from_the_hash(open_dashboard):
    page, errors = _open(open_dashboard, "#statistiques?p=90")
    assert page.get_attribute('[data-period="90"]', "aria-pressed") == "true"
    assert _funnel(page)[0][1] == "9"
    assert errors == []


def test_weekly_chart_places_each_event_on_its_week_with_a_tooltip(open_dashboard):
    page, errors = _open(open_dashboard)
    weeks = page.eval_on_selector_all(
        ".week-chart g.week",
        "gs => gs.map(g => [g.dataset.week, ...['kept','sent','replies'].map(s => {"
        " const b = g.querySelector('[data-series=' + s + ']'); return b ? +b.dataset.n : 0; })])")
    assert weeks == [["2026-09-14", 0, 0, 0], ["2026-09-21", 0, 0, 0], ["2026-09-28", 0, 0, 0],
                     ["2026-10-05", 2, 1, 0], ["2026-10-12", 2, 2, 2]]
    page.hover('.week-chart g.week[data-week="2026-10-12"] rect.hit')
    tip = page.locator(".chart-tip")
    assert tip.is_visible()
    assert "Gardées : 2" in tip.inner_text() and "Réponses : 2" in tip.inner_text()
    page.click(".stats-details summary")
    assert page.locator(".stats-details tbody tr").count() == 5
    assert errors == []


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_both_themes_paint_the_series_in_their_own_colours(open_dashboard, theme):
    page, errors = _open(open_dashboard)
    page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
    fills = page.evaluate("""() => ['kept','sent','replies'].map(s =>
        getComputedStyle(document.querySelector('.bar-' + s)).fill)""")
    assert len(set(fills)) == 3 and all(f.startswith("rgb(") for f in fills)
    bg = page.evaluate("getComputedStyle(document.querySelector('.stats-card')).backgroundColor")
    ink = page.evaluate("getComputedStyle(document.querySelector('.funnel-n')).color")
    assert bg != ink
    assert errors == []


def test_phone_has_no_horizontal_scroll_and_a_tab_to_the_view(open_dashboard):
    page, errors = _open(open_dashboard, viewport=(390, 844))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    tab = page.locator('#tabbar a[data-tab="statistiques"]')
    assert tab.is_visible()
    assert tab.get_attribute("aria-current") == "page"
    box = page.locator('[data-period="tout"]').bounding_box()
    assert box["height"] >= 44
    assert errors == []


def test_without_the_tracking_the_view_says_so_and_invents_nothing(open_dashboard):
    page, errors = open_dashboard(None, "#statistiques")  # `null`: the load fails
    page.wait_for_function("() => !document.getElementById('stats-off').hidden && "
                           "!/Chargement/.test(document.getElementById('stats-off').textContent)")
    assert page.locator("#stats-body .stats-funnel").count() == 0
    assert "suivi" in page.locator("#stats-off").inner_text()


def test_g_then_s_opens_the_view(open_dashboard):
    page, errors = open_dashboard(API, "#offres")
    page.locator("#jobs-body tr").first.wait_for()
    page.locator("body").press("g")
    page.locator("body").press("s")
    page.wait_for_function(READY)
    assert page.evaluate("location.hash").startswith("#statistiques")
    assert errors == []
