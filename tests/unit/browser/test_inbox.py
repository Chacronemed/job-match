"""« Réponses à confirmer » in a real browser (ADR 0018): the block above the Kanban lists the
replies the Worker parked, Valider / Corriger / Ignorer call `PUT /api/inbox/:id` once each, the
item leaves the block and the returned application moves its card. 0 console errors at 1440
and 390, no horizontal scroll.
"""

import json

STATUSES = ["to_apply", "applied", "interview", "rejected"]
HAS_CARDS = "() => document.querySelectorAll('#kb-board .kb-card').length > 0"
H_SCROLL = "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"


def _apps(keys):
    apps = []
    for status, key in zip(STATUSES, list(keys[:3]) + ["france_travail:GONE1"]):
        apps.append(
            {
                "job_key": key,
                "status": status,
                "applied_at": "2026-10-20" if status != "to_apply" else None,
                "follow_up_at": None,
                "interview_at": None,
                "note": None,
                "cv_url": None,
                "updated_at": "2026-10-20T08:00:00Z",
                "sent_documents_version": None,
            }
        )
    return apps


def _item(message_id, kind, confidence, key, subject):
    return {
        "message_id": message_id,
        "received_at": "2026-11-02T09:00:00Z",
        "sender_domain": "acme.example",
        "subject": subject,
        "kind": kind,
        "confidence": confidence,
        "interview_at": None,
        "proposed_key": key,
        "state": "to_confirm",
        "applied_key": None,
        "applied_at": None,
        "ai_outcome": "ok",
    }


def _api(keys):
    inbox = {
        "to_confirm": [
            _item("msg-1", "entretien", 0.62, keys[1], "Entretien chez Acme"),
            _item("msg-2", "autre", 0.4, None, "Newsletter emploi"),
        ],
        "history": [
            {
                **_item("msg-0", "entretien", 0.95, keys[2], "Suite à votre candidature"),
                "state": "applied",
                "applied_key": keys[2],
                "applied_at": "2026-10-21T08:00:00Z",
            }
        ],
    }
    return {
        "applications": _apps(keys),
        "decisions": [],
        "skill_overrides": [],
        "ai_verdicts": [],
        "ai_runs": [],
        "documents": [],
        "documents_budget": None,
        "inbox": inbox,
    }


def _answer(item, application):
    return (
        200,
        {"content-type": "application/json"},
        json.dumps({"item": item, "application": application}),
    )


def _open(open_dashboard, keys, routes, **kw):
    page, errors = open_dashboard(_api(keys), routes=routes, **kw)
    page.wait_for_function(HAS_CARDS)
    return page, errors


def _cards(page, status):
    return page.locator(f'#kb-board .kb-col[data-status="{status}"] .kb-card').count()


def test_valider_applies_the_proposed_reply_and_moves_the_card(open_dashboard, job_keys):
    key = job_keys[1]  # the « Envoyée » application the model proposed
    done = {
        **_item("msg-1", "entretien", 0.62, key, "Entretien chez Acme"),
        "state": "applied",
        "applied_key": key,
        "applied_at": "2026-11-02T10:00:00Z",
    }
    app = {**_apps(job_keys)[1], "status": "interview", "interview_at": None}
    routes = {("PUT", "/api/inbox/msg-1"): _answer(done, app)}
    page, errors = _open(open_dashboard, job_keys, routes)
    block = page.locator("#kb-inbox")
    assert block.is_visible()
    assert "Réponses à confirmer (2)" in block.inner_text()
    items = block.locator(".inbox-item")
    assert items.count() == 2
    first = items.nth(0)
    assert "Entretien" in first.locator(".inbox-kind").inner_text()
    assert first.locator(".inbox-conf").inner_text() == "62 %"
    assert "acme.example" in first.locator(".inbox-meta").first.inner_text()
    # the second one (« Autre », no application): Valider only archives it, so it stays on
    second = items.nth(1)
    assert "Candidature inconnue" in second.locator(".inbox-meta").first.inner_text()
    assert not second.get_by_role("button", name="Valider").is_disabled()
    assert _cards(page, "applied") == 1 and _cards(page, "interview") == 1
    first.get_by_role("button", name="Valider").click()
    page.wait_for_function("() => document.querySelectorAll('#kb-inbox .inbox-item').length === 1")
    assert page.api_calls == [("GET", "/api/applications"), ("PUT", "/api/inbox/msg-1")]
    assert _cards(page, "applied") == 0 and _cards(page, "interview") == 2
    assert "Réponses à confirmer (1)" in block.inner_text()
    assert errors == []


def test_corriger_picks_the_application_and_the_kind_then_puts_once(open_dashboard, job_keys):
    target = job_keys[2]  # another application than the proposed one
    done = {
        **_item("msg-1", "refus", 0.62, job_keys[1], "Entretien chez Acme"),
        "state": "corrected",
        "applied_key": target,
        "applied_at": "2026-11-02T10:00:00Z",
    }
    app = {**_apps(job_keys)[2], "status": "rejected"}
    sent = {}

    def api():
        return _api(job_keys)

    page, errors = open_dashboard(
        api, routes={("PUT", "/api/inbox/msg-1"): _answer(done, app)}, viewport=(390, 844)
    )
    page.wait_for_function(HAS_CARDS)
    page.on("request", lambda r: sent.update(body=r.post_data) if r.method == "PUT" else None)
    first = page.locator("#kb-inbox .inbox-item").nth(0)
    first.get_by_role("button", name="Corriger").click()
    form = first.locator(".inbox-correct")
    assert form.is_visible()
    assert (
        form.locator("select[name=application_key]").input_value() == job_keys[1]
    )  # the proposal, preselected
    form.locator("select[name=application_key]").select_option(target)
    form.locator("select[name=kind]").select_option("refus")
    form.get_by_role("button", name="Enregistrer").click()
    page.wait_for_function("() => document.querySelectorAll('#kb-inbox .inbox-item').length === 1")
    assert json.loads(sent["body"]) == {
        "action": "correct",
        "application_key": target,
        "kind": "refus",
        "interview_at": None,
    }
    assert page.api_calls == [("GET", "/api/applications"), ("PUT", "/api/inbox/msg-1")]
    assert _cards(page, "interview") == 0 and _cards(page, "rejected") == 2
    assert not page.evaluate(H_SCROLL)
    assert errors == []


def test_ignorer_archives_and_the_record_lists_the_history(open_dashboard, job_keys):
    done = {
        **_item("msg-2", "autre", 0.4, None, "Newsletter emploi"),
        "state": "ignored",
        "applied_at": "2026-11-02T10:00:00Z",
    }
    page, errors = _open(
        open_dashboard, job_keys, {("PUT", "/api/inbox/msg-2"): _answer(done, None)}
    )
    page.locator("#kb-inbox .inbox-item").nth(1).get_by_role("button", name="Ignorer").click()
    page.wait_for_function("() => document.querySelectorAll('#kb-inbox .inbox-item').length === 1")
    assert page.api_calls[-1] == ("PUT", "/api/inbox/msg-2")
    # the record panel of the interview offer shows the applied reply from the history
    page.click("#apps-view-table")
    page.wait_for_selector("#kb-table table.data.apps")
    row = page.locator(f'#kb-table tbody tr[data-key="{job_keys[2]}"]')
    row.locator("td.apps-title button").click()
    page.wait_for_selector("#record .inbox-history")
    history = page.locator("#record .inbox-history li")
    assert history.count() == 1
    assert "Suite à votre candidature" in history.first.inner_text()
    assert "Entretien" in history.first.locator(".inbox-kind").inner_text()
    assert "Appliquée" in history.first.locator(".inbox-state").inner_text()
    assert (
        page.locator("#record input[name=interview_at]").count() == 1
    )  # « Entretien le » in Suivi
    assert errors == []
