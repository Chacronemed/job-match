"""The answer kit in the offer page (ADR 0023): each answer with « Copier », the salary in
`manuel` without a value nor a button but with the zone's benchmark, and « Candidature
envoyée » writing the status, the date and the follow-up date. Every value is made up."""

import json
from urllib.parse import quote


def _bundle(key, apply):
    content = {
        "job_key": key,
        "version": 1,
        "language": "fr",
        "prompt_version": "6",
        "offer": {
            "key": key,
            "title": "Ingénieur DevOps",
            "company": "Initech",
            "location": "Paris",
        },
        "profile": "Ingénieur DevOps. Disponible immédiatement.",
        "selected_bullets": [],
        "skill_groups": [],
        "headline_techs": [],
        "highlights": [],
        "letter": {
            "paragraphs": [{"sentences": [{"text": "Votre offre m’intéresse.", "sources": []}]}]
        },
        "answers": {
            "motivation": {
                "sentences": [{"text": "Ce poste prolonge mon alternance.", "sources": []}]
            },
            "why_company": {
                "sentences": [{"text": "Initech construit une plateforme cloud.", "sources": []}]
            },
        },
        "cv": {"experiences": [], "projects": []},
    }
    master = {
        "headline": "Ingénieur DevOps",
        "available_from": "2026-01-01",
        "mobility": "Mobile en France",
        "skill_groups": [],
        "education": [],
        "languages": [],
        "extras": [],
    }
    contact = {
        "first_name": "Jean",
        "last_name": "Test",
        "title": "DevOps",
        "email": "j@example.com",
        "phone": "",
        "linkedin": "",
        "github": "",
        "location": "Paris",
    }
    return {"content": content, "master": master, "contact": contact, "apply": apply}


def _api(key, status="to_apply"):
    app = {
        "job_key": key,
        "status": status,
        "applied_at": None,
        "follow_up_at": None,
        "note": None,
        "cv_url": None,
        "updated_at": "2026-11-04T08:00:00Z",
        "sent_documents_version": None,
    }
    doc = {
        "job_key": key,
        "version": 1,
        "status": "ready",
        "language": "fr",
        "error_code": None,
        "updated_at": "2026-11-04T09:00:00Z",
    }
    return {
        "applications": [app],
        "decisions": [],
        "skill_overrides": [],
        "ai_verdicts": [],
        "ai_runs": [],
        "documents": [doc],
        "documents_budget": None,
    }


APPLY = {
    "remuneration": {
        "mode": "manuel",
        "fourchette": None,
        "reperes": [{"zone": "Île-de-France", "match": ["paris"], "texte": "42–48 k€ brut annuel"}],
    },
    "preavis": "Aucun préavis",
    "mobilite": "",
    "reponses_fixes": [{"label": "Permis B", "match": ["permis"], "reponse": "Oui"}],
}
GRANT = """
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
    writeText: (t) => { window.__copied = t; return Promise.resolve(); } } });
"""


def _open(open_dashboard, key, apply=APPLY, status="to_apply"):
    path = f"/api/documents/{quote(key, safe='')}/v1/content.json"
    put = f"/api/applications/{quote(key, safe='')}"
    saved = []

    routes = {
        ("GET", path): (200, {"Content-Type": "application/json"}, json.dumps(_bundle(key, apply))),
        ("PUT", put): (200, {"Content-Type": "application/json"}, json.dumps({"application": {}})),
    }
    # The order is fixed, never raced: the record opens from the link first, then the tracking
    # answers (the slow order of a real network, the one CI hit) and the record gains its kit.
    page, errors = open_dashboard(
        _api(key, status),
        f"#offres?fiche={quote(key, safe='')}",
        init_script=GRANT,
        routes=routes,
        hold_api=True,
    )
    page.on(
        "request", lambda r: saved.append(json.loads(r.post_data)) if r.method == "PUT" else None
    )
    page.wait_for_selector("#record-title")
    assert page.locator(".kit").count() == 0
    page.release_api()
    page.wait_for_selector(f'.kit[data-kit="{key}"] .kit-list dd')
    return page, errors, saved


def test_each_answer_has_copy_and_the_salary_in_manuel_has_none(open_dashboard, job_keys):
    key = job_keys[0]
    page, errors, _ = _open(open_dashboard, key)
    kit = page.locator(f'.kit[data-kit="{key}"]')
    assert (
        kit.locator('[data-kit-key="motivation"] .kit-text').inner_text()
        == "Ce poste prolonge mon alternance."
    )
    assert (
        kit.locator('[data-kit-key="availability"] .kit-text').inner_text()
        == "Disponible immédiatement"
    )
    assert kit.locator('[data-kit-key="notice"] .kit-text').inner_text() == "Aucun préavis"
    salary = kit.locator('[data-kit-key="salary"]')
    assert salary.locator(".kit-copy").count() == 0
    assert salary.locator(".kit-text").count() == 0
    assert "Repère Île-de-France : 42–48 k€ brut annuel" in salary.inner_text()
    kit.get_by_role("button", name="Copier : Pourquoi cette entreprise").click()
    assert page.evaluate("window.__copied") == "Initech construit une plateforme cloud."
    kit.get_by_role("button", name="Copier : Permis B").click()
    assert page.evaluate("window.__copied") == "Oui"
    assert errors == []


def test_sent_button_marks_the_application_with_its_follow_up(open_dashboard, job_keys):
    key = job_keys[0]
    page, errors, saved = _open(open_dashboard, key)
    with page.expect_request(lambda r: r.method == "PUT"):
        page.locator(f'.kit[data-kit="{key}"] .kit-sent').click()
    body = saved[-1]
    assert body["status"] == "applied"
    assert body["applied_at"] and body["follow_up_at"] > body["applied_at"]
    assert errors == []


def test_no_sent_button_once_applied(open_dashboard, job_keys):
    key = job_keys[0]
    page, _, _ = _open(open_dashboard, key, status="applied")
    assert page.locator(f'.kit[data-kit="{key}"] .kit-sent').count() == 0
