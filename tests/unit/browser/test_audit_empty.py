"""IMPECCABLE_AUDIT O4 / O6 with a snapshot that lists no offer: the empty states say why from
the latest collection run (the seed's run marks France Travail down), never « rien collecté »."""

import pytest

from job_match.config.schema import Settings
from job_match.dashboard.data import build_dashboard_data
from job_match.persistence.db import Database


@pytest.fixture
def dashboard_data(seed_dashboard):
    with Database(path=":memory:") as db:
        seed = seed_dashboard(db)
        data = build_dashboard_data(db, Settings(), seed.now)
    data["jobs"] = []
    data["tracked"] = []
    return data, seed


def _api():
    return {"applications": [], "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": [], "documents_budget": None}


def test_offres_with_no_offer_says_why_from_the_last_run(open_dashboard):
    page, errors = open_dashboard(_api(), hash_="#offres")
    page.wait_for_selector("#jobs-empty:not([hidden])")
    text = page.locator("#jobs-empty-text").inner_text()
    assert "rien collecté" not in text and "France Travail" in text
    page.wait_for_function("() => window.JM.track.status === 'ready'")
    assert page.locator("#offres-to-tri").is_hidden()
    assert page.locator("#detail-empty-hint").is_hidden()
    assert errors == []


def test_an_empty_tri_names_the_source_down(open_dashboard):
    page, errors = open_dashboard(_api(), hash_="#tri")
    page.wait_for_function("() => !document.getElementById('tri-end').hidden"
                           " && window.JM.track.status === 'ready'")
    end = page.locator("#tri-end")
    assert end.locator("h2").inner_text() == "Rien à trier"
    assert "Source indisponible à la dernière collecte : France Travail" in end.inner_text()
    assert errors == []
