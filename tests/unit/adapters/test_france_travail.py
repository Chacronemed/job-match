import json
import logging
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from job_match.adapters.jobs.france_travail import (
    MAX_RANGE_END,
    MAX_RANGE_START,
    PAGE_SIZE,
    SEARCH_URL,
    TOKEN_URL,
    FranceTravailSource,
    _build_params,
    _parse_content_range_total,
    _parse_dt,
)
from job_match.config.schema import Candidate, Filters, FTSearch, Profile, ScoringConfig, Skills
from job_match.domain.models import ContractType, WorkplaceType

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _profile(departments: list[str] | None = None, **ft_kwargs) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(
            rome_codes=["M1809"],
            keywords=["devops"],
            departments=departments if departments is not None else ["75"],
            **ft_kwargs,
        ),
        scoring=ScoringConfig(),
    )


def _source(profile=None, **kwargs) -> FranceTravailSource:
    """Create a source with high rate limit so tests don't sleep."""
    return FranceTravailSource(profile or _profile(), requests_per_second=1000.0, **kwargs)


@pytest.fixture(autouse=True)
def ft_env(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "test-id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "test-secret")


# ---------------------------------------------------------------------------
# to_job mapping
# ---------------------------------------------------------------------------


def test_to_job_maps_fields():
    source = _source()
    raw = _load("ft_search_p1.json")["resultats"][0]
    job = source.to_job(raw)

    assert job.source == "france_travail"
    assert job.source_job_id == "167DFDB"
    assert job.title == "Ingénieur DevOps H/F"
    assert job.company == "Acme SAS"
    assert job.location == "75 - Paris"
    assert job.contract_type == ContractType.CDI
    assert job.workplace_type == WorkplaceType.UNKNOWN
    assert job.published_at is not None
    assert job.published_at.tzinfo is not None  # timezone-aware
    assert "DevOps" in job.description
    assert "167DFDB" in job.url


def test_to_job_cdd_maps_correctly():
    source = _source()
    raw = _load("ft_search_p2.json")["resultats"][0]
    job = source.to_job(raw)
    assert job.contract_type == ContractType.CDD


def test_to_job_unknown_contract_type():
    source = _source()
    raw = {**_load("ft_search_p1.json")["resultats"][0], "typeContrat": "XYZ"}
    job = source.to_job(raw)
    assert job.contract_type == ContractType.UNKNOWN


def test_to_job_missing_optional_fields():
    source = _source()
    job = source.to_job({"id": "MIN001", "typeContrat": "CDI"})
    assert job.title == ""
    assert job.company == ""
    assert job.description == ""
    assert job.url == ""
    assert job.published_at is None


def test_to_job_missing_id_raises():
    source = _source()
    with pytest.raises(KeyError):
        source.to_job({"intitule": "No ID"})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_parse_content_range_total_happy():
    assert _parse_content_range_total("offres 0-149/500") == 500
    assert _parse_content_range_total("offres 2-2/3") == 3


def test_parse_content_range_total_empty():
    assert _parse_content_range_total("") is None
    assert _parse_content_range_total("bytes 0-499/1234") is None


def test_parse_dt_utc():
    dt = _parse_dt("2026-09-28T08:00:00.000+02:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.hour == 6  # 08:00 CEST = 06:00 UTC


def test_parse_dt_none():
    assert _parse_dt(None) is None
    assert _parse_dt("") is None


def test_parse_dt_invalid():
    assert _parse_dt("not-a-date") is None


# ---------------------------------------------------------------------------
# _build_params
# ---------------------------------------------------------------------------


def test_build_params_single_keyword():
    params = _build_params(_profile(), None, "75", keyword="devops")
    assert params == {"motsCles": "devops", "departement": "75"}
    assert "codeROME" not in params


def test_build_params_rome_only():
    params = _build_params(_profile(), None, "75", rome_code="M1809")
    assert params == {"codeROME": "M1809", "departement": "75"}
    assert "motsCles" not in params


def test_build_params_no_keyword_no_rome():
    params = _build_params(_profile(), None, "75")
    assert params == {"departement": "75"}


def test_build_params_keyword_and_rome_gives_keyword_only():
    # keyword takes precedence when both supplied (shouldn't happen in normal flow)
    params = _build_params(_profile(), None, "75", keyword="devops", rome_code="M1809")
    assert "motsCles" in params
    assert "codeROME" not in params


# ---------------------------------------------------------------------------
# token management
# ---------------------------------------------------------------------------


def test_token_cached():
    token_body = _load("ft_token.json")
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_body)
        )
        source = _source()
        t1 = source._ensure_token()
        t2 = source._ensure_token()

    assert t1 == t2 == "fake-token-abc"
    assert token_route.call_count == 1


def test_token_refreshed_when_expired():
    token_body = _load("ft_token.json")
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_body)
        )
        source = _source()
        source._token = "old-token"
        source._token_expires_at = time.monotonic()  # within 60s margin → stale

        new_token = source._ensure_token()

    assert new_token == "fake-token-abc"
    assert token_route.call_count == 1


# ---------------------------------------------------------------------------
# fetch — per-keyword isolation
# ---------------------------------------------------------------------------


def test_fetch_single_keyword_sends_single_motscles():
    """motsCles must be the single keyword string, never joined."""
    p1 = _load("ft_search_p1.json")
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-1/2"})
        )
        source = _source()
        list(source.fetch())

    req_params = dict(search_route.calls[0].request.url.params)
    assert req_params.get("motsCles") == "devops"
    assert "codeROME" not in req_params


def test_fetch_one_call_per_keyword(monkeypatch):
    """2 keywords × 1 department = 2 API calls, each with its own motsCles."""
    p1 = _load("ft_search_p1.json")
    profile = _profile()
    profile.ft_search.keywords.append("sre")  # add second keyword

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-1/2"})
        )
        source = _source(profile)
        results = list(source.fetch())

    assert search_route.call_count == 2
    assert len(results) == 4  # 2 items × 2 calls
    keywords_sent = [dict(c.request.url.params).get("motsCles") for c in search_route.calls]
    assert "devops" in keywords_sent
    assert "sre" in keywords_sent
    assert source.api_calls_count == 2


def test_fetch_keyword_dept_combinations():
    """2 keywords × 2 departments = 4 API calls."""
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    profile = _profile(departments=["75", "92"])
    profile.ft_search.keywords.append("sre")

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(profile)
        list(source.fetch())

    assert search_route.call_count == 4
    assert source.api_calls_count == 4


def test_fetch_rome_only_mode():
    """use_rome_search=True: keywords search + ROME-only search."""
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    profile = _profile(use_rome_search=True)  # 1 keyword + 1 ROME code, 1 dept

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(profile)
        list(source.fetch())

    # 1 keyword call + 1 ROME call = 2 total
    assert search_route.call_count == 2
    params_list = [dict(c.request.url.params) for c in search_route.calls]
    assert any("motsCles" in p and "codeROME" not in p for p in params_list)
    assert any("codeROME" in p and "motsCles" not in p for p in params_list)


def test_fetch_no_keywords_yields_nothing():
    """Empty keywords list + use_rome_search=False → no API calls."""
    profile = Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(keywords=[], rome_codes=["M1809"], departments=["75"]),
        scoring=ScoringConfig(),
    )
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"resultats": []})
        )
        source = _source(profile)
        results = list(source.fetch())

    assert results == []
    assert search_route.call_count == 0


# ---------------------------------------------------------------------------
# fetch — pagination
# ---------------------------------------------------------------------------


def test_fetch_single_page():
    p1 = _load("ft_search_p1.json")
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(
                200, json=p1, headers={"Content-Range": "offres 0-1/2"}
            )
        )
        source = _source()
        results = list(source.fetch())

    assert len(results) == 2
    assert results[0]["id"] == "167DFDB"


def test_fetch_paginates():
    p1 = _load("ft_search_p1.json")
    p2 = _load("ft_search_p2.json")
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        search_route = respx.get(SEARCH_URL).mock(
            side_effect=[
                httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-1/3"}),
                httpx.Response(200, json=p2, headers={"Content-Range": "offres 2-2/3"}),
            ]
        )
        source = _source()
        results = list(source.fetch())

    assert len(results) == 3
    assert [r["id"] for r in results] == ["167DFDB", "167DFDC", "167DFDD"]
    assert search_route.call_count == 2
    # Second request should start after the 2 items fetched on page 1
    assert search_route.calls[1].request.headers["Range"] == "2-151"


def test_fetch_respects_max_results():
    p1 = _load("ft_search_p1.json")
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(
                200, json=p1, headers={"Content-Range": "offres 0-1/100"}
            )
        )
        source = _source(max_results=1)
        results = list(source.fetch())

    assert len(results) == 1


def test_fetch_token_only_fetched_once_across_pages():
    p1 = _load("ft_search_p1.json")
    p2 = _load("ft_search_p2.json")
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            side_effect=[
                httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-1/3"}),
                httpx.Response(200, json=p2, headers={"Content-Range": "offres 2-2/3"}),
            ]
        )
        source = _source()
        list(source.fetch())

    assert token_route.call_count == 1


# ---------------------------------------------------------------------------
# fetch — retry behaviour
# ---------------------------------------------------------------------------


def test_fetch_429_retry_after(monkeypatch):
    monkeypatch.setattr("job_match.adapters.http.time.sleep", lambda _: None)
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "0"}),
                httpx.Response(
                    200, json=p1, headers={"Content-Range": "offres 0-0/1"}
                ),
            ]
        )
        source = _source()
        results = list(source.fetch())

    assert len(results) == 1


def test_fetch_5xx_retries(monkeypatch):
    monkeypatch.setattr("job_match.adapters.http.time.sleep", lambda _: None)
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(
                    200, json=p1, headers={"Content-Range": "offres 0-0/1"}
                ),
            ]
        )
        source = _source()
        results = list(source.fetch())

    assert len(results) == 1


def test_fetch_timeout_retries(monkeypatch):
    monkeypatch.setattr("job_match.adapters.http.time.sleep", lambda _: None)
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}

    def raise_timeout(request):
        raise httpx.ReadTimeout("timeout")

    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            side_effect=[
                raise_timeout,
                httpx.Response(
                    200, json=p1, headers={"Content-Range": "offres 0-0/1"}
                ),
            ]
        )
        source = _source()
        results = list(source.fetch())

    assert len(results) == 1


# ---------------------------------------------------------------------------
# fetch — 204 handling
# ---------------------------------------------------------------------------


def test_fetch_204_no_content_returns_empty():
    """HTTP 204 (zero results) must yield nothing, not raise JSONDecodeError."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(204))
        source = _source()
        results = list(source.fetch())
    assert results == []


def test_fetch_204_multiple_departments_all_empty():
    """All departments returning 204 must yield nothing and not crash."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(204))
        source = _source(_profile(departments=["75", "92", "93"]))
        results = list(source.fetch())
    assert results == []


def test_fetch_malformed_json():
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=_load("ft_token.json"))
        )
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                content=b"not-json",
                headers={"Content-Type": "application/json", "Content-Range": "offres 0-0/1"},
            )
        )
        source = _source()
        with pytest.raises(Exception):
            list(source.fetch())


# ---------------------------------------------------------------------------
# throttle
# ---------------------------------------------------------------------------


def test_throttle_calls_sleep_between_requests():
    """With a slow rate limit, time.sleep must be called between requests."""
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    profile = _profile()
    profile.ft_search.keywords.append("sre")  # 2 keywords → 2 requests

    sleep_calls: list[float] = []
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        # Use a slow rate to guarantee sleep is needed
        source = FranceTravailSource(profile, requests_per_second=0.01)
        with patch(
            "job_match.adapters.jobs.france_travail.time.sleep",
            side_effect=lambda s: sleep_calls.append(s),
        ):
            # Force last_request_time to "just now" so second request sleeps
            source._last_request_time = time.monotonic()
            list(source.fetch())

    assert len(sleep_calls) >= 1
    assert all(s > 0 for s in sleep_calls)


def test_api_calls_count_tracks_requests():
    """api_calls_count must equal the number of HTTP requests made."""
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    profile = _profile(departments=["75", "92"])  # 1 keyword × 2 depts = 2 calls

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(profile)
        list(source.fetch())

    assert source.api_calls_count == 2


def test_items_are_tagged_with_the_query_that_returned_them():
    p1 = _load("ft_search_p1.json")
    profile = _profile()
    profile.ft_search.keywords.append("sre")
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-1/2"})
        )
        source = _source(profile)
        jobs = [source.to_job(raw) for raw in source.fetch()]

    assert [j.search_query for j in jobs] == ["devops", "devops", "sre", "sre"]


def test_to_job_without_query_tag_has_no_search_query():
    raw = _load("ft_search_p1.json")["resultats"][0]
    raw.pop("_jm_query", None)
    assert _source().to_job(raw).search_query is None


# ---------------------------------------------------------------------------
# fan-out — every keyword x department query must run
# ---------------------------------------------------------------------------


def test_every_department_is_queried():
    """One request per department, each carrying its own `departement` param."""
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    depts = ["75", "92", "93", "69", "31"]

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(_profile(departments=depts))
        list(source.fetch())

    queried = [dict(c.request.url.params).get("departement") for c in search_route.calls]
    assert queried == depts
    assert [s.area for s in source.query_stats] == depts


def test_per_query_cap_does_not_starve_later_departments():
    """Regression: max_results caps each query, never the fan-out.

    A global cap let the first department consume the whole budget, so every
    later (keyword, department) query was abandoned unqueried.
    """
    page = _load("ft_search_p1.json")  # 2 results, Content-Range says 100 exist
    depts = ["75", "92", "93"]

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        search_route = respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(
                200, json=page, headers={"Content-Range": "offres 0-1/100"}
            )
        )
        source = _source(_profile(departments=depts), max_results=1)
        results = list(source.fetch())

    assert search_route.call_count == 3  # one per department, despite max_results=1
    assert len(results) == 3  # one offer per department
    assert sorted(dict(c.request.url.params)["departement"] for c in search_route.calls) == depts


def test_query_stats_record_keyword_department_and_fetched():
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}
    profile = _profile(departments=["75", "92"])
    profile.ft_search.keywords.append("sre")

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(profile)
        list(source.fetch())

    assert [(s.query, s.area, s.fetched, s.available) for s in source.query_stats] == [
        ("devops", "75", 1, 1),
        ("devops", "92", 1, 1),
        ("sre", "75", 1, 1),
        ("sre", "92", 1, 1),
    ]


def test_empty_query_is_still_recorded_in_stats():
    """A department returning 204 must still appear, with fetched=0."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(204))
        source = _source(_profile(departments=["75", "92"]))
        list(source.fetch())

    assert [(s.area, s.fetched) for s in source.query_stats] == [("75", 0), ("92", 0)]


def _query_log_lines(caplog, level: str) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelname == level and r.getMessage().startswith("query ")
    ]


def test_one_info_log_per_query_without_the_keyword(caplog):
    """INFO stays aggregate: the keyword comes from the private profile."""
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(_profile(departments=["75", "92"]))
        with caplog.at_level("INFO", logger="job_match.adapters.jobs.france_travail"):
            list(source.fetch())

    lines = _query_log_lines(caplog, "INFO")
    assert lines == [
        "query dept=75 fetched=1 available=1",
        "query dept=92 fetched=1 available=1",
    ]
    # No keyword, and no job title, company or id.
    assert not any(
        "devops" in line or "Ingénieur DevOps" in line or "167DFDB" in line for line in lines
    )


def test_keyword_is_logged_at_debug(caplog):
    p1 = {"resultats": [_load("ft_search_p1.json")["resultats"][0]]}

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_load("ft_token.json")))
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=p1, headers={"Content-Range": "offres 0-0/1"})
        )
        source = _source(_profile(departments=["75"]))
        with caplog.at_level("DEBUG", logger="job_match.adapters.jobs.france_travail"):
            list(source.fetch())

    assert _query_log_lines(caplog, "DEBUG") == [
        "query keyword=devops dept=75 fetched=1 available=1"
    ]


# ---------------------------------------------------------------------------
# National scope: no departement param, paginated inside the API window
# ---------------------------------------------------------------------------

def _national(keywords: list[str] | None = None) -> Profile:
    """`location_scope: france` arrives here as an empty department list."""
    return Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(keywords=keywords or ["devops"], departments=[]),
        scoring=ScoringConfig(),
    )


def _token_route():
    return respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_load("ft_token.json"))
    )


def _offers(count: int, start: int, total: int) -> httpx.Response:
    """A page of synthetic offers with the Content-Range header the API sends."""
    return httpx.Response(
        200,
        json={"resultats": [{"id": f"FT{start + i}"} for i in range(count)]},
        headers={"Content-Range": f"offres {start}-{start + count - 1}/{total}"},
    )


def _window_pages(total: int) -> list[httpx.Response]:
    """Full pages until the API window (1149) is drained, as the real endpoint behaves."""
    pages = []
    start = 0
    while start <= MAX_RANGE_START:
        count = min(PAGE_SIZE, MAX_RANGE_END + 1 - start)
        pages.append(_offers(count, start, total))
        start += count
    return pages


def test_a_national_scope_sends_no_departement_param():
    with respx.mock:
        _token_route()
        route = respx.get(SEARCH_URL).mock(return_value=_offers(2, 0, 2))
        list(_source(_national()).fetch())

    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert "departement" not in params
    assert params["motsCles"] == "devops"


def test_a_national_scope_runs_one_query_per_keyword():
    with respx.mock:
        _token_route()
        route = respx.get(SEARCH_URL).mock(return_value=_offers(1, 0, 1))
        items = list(_source(_national(["devops", "sre", "kubernetes"])).fetch())

    assert route.call_count == 3  # one nationwide query each, no department fan-out
    assert len(items) == 3
    assert [c.request.url.params["motsCles"] for c in route.calls] == [
        "devops", "sre", "kubernetes",
    ]


def test_paging_stops_at_the_api_window_and_clamps_the_last_range():
    with respx.mock:
        _token_route()
        route = respx.get(SEARCH_URL).mock(side_effect=_window_pages(total=5000))
        items = list(_source(_national()).fetch())

    ranges = [c.request.headers["Range"] for c in route.calls]
    assert ranges[0] == "0-149"
    assert ranges == [f"{n}-{n + PAGE_SIZE - 1}" for n in range(0, 1050, PAGE_SIZE)]
    # start <= 1000 and end <= 1149: 7 pages, then no page is addressable any more
    assert all(int(r.split("-")[0]) <= MAX_RANGE_START for r in ranges)
    assert all(int(r.split("-")[1]) <= MAX_RANGE_END for r in ranges)
    assert len(items) == 1050


def test_truncation_by_the_window_is_logged(caplog):
    with respx.mock:
        _token_route()
        respx.get(SEARCH_URL).mock(side_effect=_window_pages(total=5000))
        with caplog.at_level(logging.WARNING):
            list(_source(_national()).fetch())

    assert "truncated by the API window" in caplog.text
    assert "5000" in caplog.text


def test_a_query_inside_the_window_logs_no_truncation(caplog):
    with respx.mock:
        _token_route()
        respx.get(SEARCH_URL).mock(return_value=_offers(2, 0, 2))
        with caplog.at_level(logging.WARNING):
            list(_source(_national()).fetch())

    assert "truncated" not in caplog.text


def test_a_limited_query_does_not_claim_truncation(caplog):
    """`--limit 50` is our own cap, not the API's window."""
    with respx.mock:
        _token_route()
        respx.get(SEARCH_URL).mock(return_value=_offers(150, 0, 5000))
        with caplog.at_level(logging.WARNING):
            items = list(_source(_national(), max_results=50).fetch())

    assert len(items) == 50
    assert "truncated" not in caplog.text


def test_a_refused_range_ends_the_query_without_killing_the_run(caplog):
    with respx.mock:
        _token_route()
        route = respx.get(SEARCH_URL).mock(side_effect=[
            _offers(150, 0, 5000),
            httpx.Response(400, json={"message": "range invalide"}),
            _offers(1, 0, 1),
        ])
        with caplog.at_level(logging.WARNING):
            items = list(_source(_national(["devops", "sre"])).fetch())

    assert route.call_count == 3
    assert len(items) == 151  # 150 kept from the first keyword, 1 from the second
    assert "refused (HTTP 400)" in caplog.text


def test_the_national_query_area_is_reported_as_all():
    with respx.mock:
        _token_route()
        respx.get(SEARCH_URL).mock(return_value=_offers(2, 0, 2))
        source = _source(_national())
        list(source.fetch())

    assert [s.area for s in source.query_stats] == ["all"]
