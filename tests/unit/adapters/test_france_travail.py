import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from job_match.adapters.jobs.france_travail import (
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
