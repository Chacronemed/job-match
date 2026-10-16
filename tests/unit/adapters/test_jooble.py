"""Jooble adapter: no keyword x department fan-out, a hard call cap, and no key in logs."""
import json
import logging

import httpx
import pytest
import respx

from job_match.adapters.jobs.jooble import API_ROOT, JoobleSource
from job_match.config.schema import Candidate, Filters, FTSearch, Profile, ScoringConfig, Skills
from job_match.domain.models import ContractType, WorkplaceType

API_KEY = "test-jooble-key"
URL = f"{API_ROOT}/{API_KEY}"


def _profile(keywords: list[str] | None = None) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=2),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(keywords=keywords if keywords is not None else ["devops"]),
        scoring=ScoringConfig(),
    )


def _source(profile=None, regions=None, **kwargs) -> JoobleSource:
    """High rate limit so tests never sleep."""
    return JoobleSource(
        profile or _profile(),
        api_key=API_KEY,
        regions=regions if regions is not None else ["Île-de-France"],
        requests_per_second=1000.0,
        **kwargs,
    )


def _body(jobs: list[dict], total: int | None = None) -> dict:
    return {"totalCount": total if total is not None else len(jobs), "jobs": jobs}


def _item(job_id: str = "123", **overrides) -> dict:
    base = {
        "id": job_id,
        "title": "DevOps Engineer",
        "company": "Acme Corp",
        "location": "Nanterre",
        "snippet": "Kubernetes and Terraform, CDI.",
        "type": "CDI",
        "link": "https://jooble.org/jdp/123",
        "updated": "2026-10-15T00:00:00",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# to_job mapping
# ---------------------------------------------------------------------------

def test_to_job_maps_fields():
    source = _source()
    job = source.to_job({**_item(), "_jm_query": "devops"})

    assert job.source == "jooble"
    assert job.source_job_id == "123"
    assert job.title == "DevOps Engineer"
    assert job.company == "Acme Corp"
    assert job.location == "Nanterre"
    assert job.contract_type is ContractType.CDI
    assert job.workplace_type is WorkplaceType.UNKNOWN
    assert job.description == "Kubernetes and Terraform, CDI."
    assert job.url == "https://jooble.org/jdp/123"
    assert job.published_at is not None
    assert job.published_at.tzinfo is not None
    assert job.search_query == "devops"


def test_to_job_numeric_id_becomes_a_string():
    assert _source().to_job(_item(job_id=98765)).source_job_id == "98765"


def test_to_job_tolerates_missing_fields():
    job = _source().to_job({"id": "1"})
    assert job.title == ""
    assert job.company == ""
    assert job.contract_type is ContractType.UNKNOWN
    assert job.published_at is None


def test_to_job_unreadable_contract_stays_unknown():
    """Jooble's "type" is free text; "Full-time" is working time, not a contract."""
    job = _source().to_job(_item(type="Full-time", snippet="Great team"))
    assert job.contract_type is ContractType.UNKNOWN


def test_to_job_reads_contract_from_the_snippet_when_type_is_vague():
    job = _source().to_job(_item(type="Full-time", snippet="Poste en CDD de 6 mois"))
    assert job.contract_type is ContractType.CDD


# ---------------------------------------------------------------------------
# Fan-out: one combined query per region
# ---------------------------------------------------------------------------

@respx.mock
def test_one_call_per_region_whatever_the_keyword_count():
    """Jooble ORs the keywords (see scripts/jooble_probe.py), so one query holds them all."""
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body([_item()])))
    source = _source(
        _profile(["devops", "sre"]), regions=["Île-de-France", "Lyon", "Toulouse"]
    )

    items = list(source.fetch())

    assert route.call_count == 3  # 3 regions, not 2 keywords x 3 regions
    assert len(items) == 3
    assert source.api_calls_count == 3


@respx.mock
def test_request_body_carries_the_keyword_and_region():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body([])))
    list(_source(_profile(["sre"]), regions=["Lyon"]).fetch())

    assert route.called
    sent = json.loads(respx.calls.last.request.content)
    assert sent["keywords"] == "sre"
    assert sent["location"] == "Lyon"
    assert sent["page"] == "1"  # page 1 first; later pages only if the budget allows


@respx.mock
def test_every_keyword_goes_into_the_same_query():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body([])))
    list(_source(_profile(["devops", "sre", "kubernetes"]), regions=["Lyon"]).fetch())

    assert route.call_count == 1
    sent = json.loads(respx.calls.last.request.content)
    assert sent["keywords"] == "devops sre kubernetes"


@respx.mock
def test_items_are_tagged_with_the_query_and_region():
    respx.post(URL).mock(return_value=httpx.Response(200, json=_body([_item()])))
    items = list(_source(_profile(["devops"]), regions=["Lyon"]).fetch())
    assert items[0]["_jm_query"] == "devops"
    assert items[0]["_jm_region"] == "Lyon"


@respx.mock
def test_items_without_an_id_are_skipped():
    """No stable id means nothing to upsert or dedup on."""
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_body([_item(), {"title": "no id"}]))
    )
    assert len(list(_source().fetch())) == 1


@respx.mock
def test_max_results_caps_one_query():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_body([_item(str(i)) for i in range(20)]))
    )
    items = list(_source(regions=["Lyon"], max_results=5).fetch())
    assert len(items) == 5


@respx.mock
def test_empty_region_list_still_runs_one_country_wide_query():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body([_item()])))
    list(_source(regions=[]).fetch())
    assert route.call_count == 1
    assert json.loads(respx.calls.last.request.content)["location"] == ""


# ---------------------------------------------------------------------------
# The quota cap
# ---------------------------------------------------------------------------

@respx.mock
def test_max_calls_per_run_is_a_hard_cap():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body([_item()])))
    source = _source(
        _profile(["devops", "sre", "cloud"]),
        regions=["Île-de-France", "Lyon", "Toulouse"],
        max_calls_per_run=2,
    )

    items = list(source.fetch())

    assert route.call_count == 2  # 3 regions requested, 2 calls allowed
    assert len(items) == 2
    assert source.api_calls_count == 2


@respx.mock
def test_hitting_the_cap_logs_a_warning(caplog):
    respx.post(URL).mock(return_value=httpx.Response(200, json=_body([])))
    source = _source(_profile(["a", "b"]), regions=["Lyon", "Nice"], max_calls_per_run=1)
    with caplog.at_level(logging.WARNING):
        list(source.fetch())
    assert "call budget exhausted" in caplog.text


@respx.mock
def test_calls_used_is_logged_when_the_run_completes(caplog):
    respx.post(URL).mock(return_value=httpx.Response(200, json=_body([])))
    with caplog.at_level(logging.INFO):
        list(_source(regions=["Lyon"], max_calls_per_run=15).fetch())
    assert "jooble: 1/15 calls used" in caplog.text


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@respx.mock
def test_query_stats_record_region_and_availability():
    respx.post(URL).mock(return_value=httpx.Response(200, json=_body([_item()], total=42)))
    source = _source(_profile(["devops"]), regions=["Lyon", "Rennes"])
    list(source.fetch())

    assert [(s.query, s.area, s.fetched, s.available, s.source) for s in source.query_stats] == [
        ("devops", "Lyon", 1, 42, "jooble"),
        ("devops", "Rennes", 1, 42, "jooble"),
    ]


@respx.mock
def test_query_stats_are_recorded_even_when_the_call_fails():
    respx.post(URL).mock(return_value=httpx.Response(500, json={}))
    source = _source(regions=["Lyon"])
    with pytest.raises(httpx.HTTPStatusError):
        list(source.fetch())
    assert [(s.area, s.fetched) for s in source.query_stats] == [("Lyon", 0)]


@respx.mock
def test_unreadable_total_count_is_none_not_zero():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"totalCount": "many", "jobs": [_item()]})
    )
    source = _source(regions=["Lyon"])
    list(source.fetch())
    assert source.query_stats[0].available is None


@respx.mock
def test_empty_response_body_is_not_an_error():
    respx.post(URL).mock(return_value=httpx.Response(200, json={}))
    assert list(_source(regions=["Lyon"]).fetch()) == []


# ---------------------------------------------------------------------------
# The API key is a path segment — it must never be logged
# ---------------------------------------------------------------------------

@respx.mock
def test_the_adapter_logs_the_url_redacted(caplog):
    """Our own log lines carry `<key>`, never the key.

    httpx logs the real URL itself, which is why `cli.py` keeps that logger above INFO
    (see test_quiet_http_logs_hides_the_request_url). This test covers our half.
    """
    respx.post(URL).mock(return_value=httpx.Response(200, json=_body([_item()])))
    with caplog.at_level(logging.DEBUG):
        list(_source(regions=["Lyon"]).fetch())

    ours = " | ".join(
        r.getMessage() for r in caplog.records if r.name.startswith("job_match")
    )
    assert API_KEY not in ours
    assert "<key>" in ours  # the redacted form is what we print


# ---------------------------------------------------------------------------
# Pagination: a page is a call
# ---------------------------------------------------------------------------

def _page(ids: list[str], total: int) -> httpx.Response:
    return httpx.Response(200, json=_body([_item(i) for i in ids], total=total))


@respx.mock
def test_a_full_page_is_followed_by_the_next_one():
    route = respx.post(URL).mock(side_effect=[
        _page([f"a{i}" for i in range(50)], 101),
        _page([f"b{i}" for i in range(50)], 101),
        _page(["c0"], 101),
    ])
    source = _source(regions=["Lyon"], max_calls_per_run=5)

    items = list(source.fetch())

    assert route.call_count == 3
    assert len(items) == 101
    assert [json.loads(c.request.content)["page"] for c in respx.calls] == ["1", "2", "3"]
    assert source.api_calls_count == 3  # pages count as calls


@respx.mock
def test_a_short_page_ends_the_region():
    route = respx.post(URL).mock(return_value=_page([f"a{i}" for i in range(10)], 999))
    list(_source(regions=["Lyon"], max_calls_per_run=5).fetch())
    assert route.call_count == 1  # fewer items than asked for: there is no page 2


@respx.mock
def test_pagination_stops_at_total_count():
    route = respx.post(URL).mock(return_value=_page([f"a{i}" for i in range(50)], 50))
    list(_source(regions=["Lyon"], max_calls_per_run=5).fetch())
    assert route.call_count == 1  # page 1 held everything Jooble claims to have


@respx.mock
def test_pagination_never_starves_a_region_of_its_first_page():
    """15 calls / 7 regions = 2 pages each: no region is skipped to paginate another."""
    route = respx.post(URL).mock(return_value=_page([f"a{i}" for i in range(50)], 5000))
    source = _source(regions=[f"r{i}" for i in range(7)], max_calls_per_run=15)
    assert source.pages_per_region == 2

    list(source.fetch())

    assert route.call_count == 14
    assert len({json.loads(c.request.content)["location"] for c in respx.calls}) == 7


@respx.mock
def test_without_a_limit_a_region_can_pass_one_page():
    """No max_results: the call budget is the only ceiling."""
    respx.post(URL).mock(side_effect=[
        _page([f"a{i}" for i in range(50)], 80),
        _page([f"b{i}" for i in range(30)], 80),
    ])
    assert len(list(_source(regions=["Lyon"], max_calls_per_run=4).fetch())) == 80


@respx.mock
def test_max_results_shrinks_the_page_and_caps_the_region():
    route = respx.post(URL).mock(return_value=_page([f"a{i}" for i in range(5)], 500))
    items = list(_source(regions=["Lyon"], max_results=5, max_calls_per_run=9).fetch())

    assert len(items) == 5
    assert json.loads(respx.calls.last.request.content)["ResultOnPage"] == "5"
    assert route.call_count == 1


@respx.mock
def test_the_pages_used_are_logged_per_region(caplog):
    respx.post(URL).mock(side_effect=[
        _page([f"a{i}" for i in range(50)], 60),
        _page(["b0"], 60),
    ])
    with caplog.at_level(logging.INFO):
        list(_source(regions=["Lyon"], max_calls_per_run=4).fetch())

    assert "area=Lyon pages=2 fetched=51" in caplog.text
    assert "jooble: 2/4 calls used" in caplog.text


# ---------------------------------------------------------------------------
# National scope: one query for the whole country, paginated
# ---------------------------------------------------------------------------

@respx.mock
def test_a_national_query_spends_the_whole_budget_on_pages():
    """`location_scope: france` arrives as regions=[""] (see the source factory)."""
    route = respx.post(URL).mock(return_value=_page([f"a{i}" for i in range(50)], 5000))
    source = _source(regions=[""], max_calls_per_run=4)
    assert source.pages_per_region == 4

    items = list(source.fetch())

    assert route.call_count == 4
    assert len(items) == 200
    locations = {json.loads(c.request.content)["location"] for c in respx.calls}
    assert locations == {""}  # no place filter at all: the whole French index
    assert [json.loads(c.request.content)["page"] for c in respx.calls] == ["1", "2", "3", "4"]
    assert [s.area for s in source.query_stats] == ["all"]
