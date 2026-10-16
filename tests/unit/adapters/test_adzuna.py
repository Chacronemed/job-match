"""Adzuna adapter: all keywords in one what_or query per region, hard call cap."""
import logging

import httpx
import pytest
import respx

from job_match.adapters.jobs.adzuna import SEARCH_URL, AdzunaSource
from job_match.config.schema import Candidate, Filters, FTSearch, Profile, ScoringConfig, Skills
from job_match.domain.models import ContractType, WorkplaceType

APP_ID = "test-app-id"
APP_KEY = "test-app-key"


def _profile(keywords: list[str] | None = None) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=2),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(keywords=keywords if keywords is not None else ["devops", "sre"]),
        scoring=ScoringConfig(),
    )


def _source(profile=None, regions=None, **kwargs) -> AdzunaSource:
    return AdzunaSource(
        profile or _profile(),
        app_id=APP_ID,
        app_key=APP_KEY,
        regions=regions if regions is not None else ["Île-de-France"],
        requests_per_second=1000.0,
        **kwargs,
    )


def _body(results: list[dict], count: int | None = None) -> dict:
    return {"count": count if count is not None else len(results), "results": results}


def _item(job_id: str = "4242", **overrides) -> dict:
    base = {
        "id": job_id,
        "title": "Site Reliability Engineer",
        "company": {"display_name": "Acme Corp"},
        "location": {"display_name": "Nanterre, Hauts-de-Seine", "area": ["France"]},
        "description": "Kubernetes, Terraform. Poste en CDI.",
        "contract_type": "permanent",
        "redirect_url": "https://www.adzuna.fr/details/4242",
        "created": "2026-10-15T09:00:00Z",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# to_job mapping
# ---------------------------------------------------------------------------

def test_to_job_maps_nested_fields():
    job = _source().to_job({**_item(), "_jm_query": "what_or"})

    assert job.source == "adzuna"
    assert job.source_job_id == "4242"
    assert job.title == "Site Reliability Engineer"
    assert job.company == "Acme Corp"          # nested under company.display_name
    assert job.location == "Nanterre, Hauts-de-Seine"
    assert job.contract_type is ContractType.CDI   # "permanent" -> CDI
    assert job.workplace_type is WorkplaceType.UNKNOWN
    assert job.url == "https://www.adzuna.fr/details/4242"
    assert job.published_at is not None
    assert job.published_at.tzinfo is not None
    assert job.search_query == "what_or"


def test_to_job_tolerates_missing_nested_objects():
    job = _source().to_job({"id": "1"})
    assert job.company == ""
    assert job.location == ""
    assert job.contract_type is ContractType.UNKNOWN


def test_to_job_contract_field_wins_over_the_description():
    job = _source().to_job(_item(contract_type="permanent", description="ancien CDD"))
    assert job.contract_type is ContractType.CDI


def test_to_job_bare_contract_label_stays_unknown():
    """Adzuna's "contract" means neither CDD nor freelance in France — don't guess."""
    job = _source().to_job(_item(contract_type="contract", description="Belle equipe"))
    assert job.contract_type is ContractType.UNKNOWN


# ---------------------------------------------------------------------------
# One query per region, keywords OR'd with what_or
# ---------------------------------------------------------------------------

@respx.mock
def test_all_keywords_fit_in_one_query_per_region():
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_body([_item()]))
    )
    source = _source(_profile(["devops", "sre", "cloud"]), regions=["Lyon", "Rennes"])

    items = list(source.fetch())

    assert route.call_count == 2  # 2 regions, NOT 3 keywords x 2 regions
    assert len(items) == 2
    assert source.api_calls_count == 2


@respx.mock
def test_what_or_carries_every_keyword():
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_body([])))
    list(_source(_profile(["devops", "sre"]), regions=["Lyon"]).fetch())

    params = respx.calls.last.request.url.params
    assert params["what_or"] == "devops sre"
    assert params["where"] == "Lyon"
    assert params["app_id"] == APP_ID
    assert params["app_key"] == APP_KEY


@respx.mock
def test_items_are_tagged_and_ids_without_a_value_skipped():
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_body([_item(), {"title": "no id"}]))
    )
    items = list(_source(regions=["Lyon"]).fetch())
    assert len(items) == 1
    assert items[0]["_jm_query"] == "what_or"
    assert items[0]["_jm_region"] == "Lyon"


@respx.mock
def test_max_results_caps_one_query():
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_body([_item(str(i)) for i in range(30)]))
    )
    assert len(list(_source(regions=["Lyon"], max_results=4).fetch())) == 4


# ---------------------------------------------------------------------------
# The quota cap
# ---------------------------------------------------------------------------

@respx.mock
def test_max_calls_per_run_is_a_hard_cap():
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_body([_item()]))
    )
    source = _source(regions=["A", "B", "C", "D"], max_calls_per_run=2)

    list(source.fetch())

    assert route.call_count == 2
    assert source.api_calls_count == 2


@respx.mock
def test_hitting_the_cap_logs_a_warning(caplog):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_body([])))
    with caplog.at_level(logging.WARNING):
        list(_source(regions=["A", "B"], max_calls_per_run=1).fetch())
    assert "call budget exhausted" in caplog.text


# ---------------------------------------------------------------------------
# Stats and failures
# ---------------------------------------------------------------------------

@respx.mock
def test_query_stats_record_region_and_availability():
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_body([_item()], count=99))
    )
    source = _source(regions=["Lyon"])
    list(source.fetch())
    assert [(s.query, s.area, s.fetched, s.available, s.source) for s in source.query_stats] == [
        ("what_or", "Lyon", 1, 99, "adzuna"),
    ]


@respx.mock
def test_query_stats_are_recorded_even_when_the_call_fails():
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(500, json={}))
    source = _source(regions=["Lyon"])
    with pytest.raises(httpx.HTTPStatusError):
        list(source.fetch())
    assert [(s.area, s.fetched) for s in source.query_stats] == [("Lyon", 0)]


@respx.mock
def test_credentials_never_appear_in_our_log_lines(caplog):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_body([_item()])))
    with caplog.at_level(logging.DEBUG):
        list(_source(regions=["Lyon"]).fetch())

    ours = " | ".join(
        r.getMessage() for r in caplog.records if r.name.startswith("job_match")
    )
    assert APP_ID not in ours
    assert APP_KEY not in ours
    assert "<key>" in ours
