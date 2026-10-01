import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from job_match.adapters.jobs.france_travail import (
    SEARCH_URL,
    TOKEN_URL,
    FranceTravailSource,
    _parse_content_range_total,
    _parse_dt,
)
from job_match.config.schema import Candidate, Filters, FTSearch, Profile, ScoringConfig, Skills
from job_match.domain.models import ContractType, WorkplaceType

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _profile(departments: list[str] | None = None) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(
            rome_codes=["M1809"],
            keywords=["devops"],
            departments=departments if departments is not None else ["75"],
        ),
        scoring=ScoringConfig(),
    )


@pytest.fixture(autouse=True)
def ft_env(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "test-id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "test-secret")


# ---------------------------------------------------------------------------
# to_job mapping
# ---------------------------------------------------------------------------


def test_to_job_maps_fields():
    source = FranceTravailSource(_profile())
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
    source = FranceTravailSource(_profile())
    raw = _load("ft_search_p2.json")["resultats"][0]
    job = source.to_job(raw)
    assert job.contract_type == ContractType.CDD


def test_to_job_unknown_contract_type():
    source = FranceTravailSource(_profile())
    raw = {**_load("ft_search_p1.json")["resultats"][0], "typeContrat": "XYZ"}
    job = source.to_job(raw)
    assert job.contract_type == ContractType.UNKNOWN


def test_to_job_missing_optional_fields():
    source = FranceTravailSource(_profile())
    job = source.to_job({"id": "MIN001", "typeContrat": "CDI"})
    assert job.title == ""
    assert job.company == ""
    assert job.description == ""
    assert job.url == ""
    assert job.published_at is None


def test_to_job_missing_id_raises():
    source = FranceTravailSource(_profile())
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
# token management
# ---------------------------------------------------------------------------


def test_token_cached():
    token_body = _load("ft_token.json")
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_body)
        )
        source = FranceTravailSource(_profile())
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
        source = FranceTravailSource(_profile())
        source._token = "old-token"
        source._token_expires_at = time.monotonic()  # within 60s margin → stale

        new_token = source._ensure_token()

    assert new_token == "fake-token-abc"
    assert token_route.call_count == 1


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
        source = FranceTravailSource(_profile())
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
        source = FranceTravailSource(_profile())
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
        source = FranceTravailSource(_profile(), max_results=1)
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
        source = FranceTravailSource(_profile())
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
        source = FranceTravailSource(_profile())
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
        source = FranceTravailSource(_profile())
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
        source = FranceTravailSource(_profile())
        results = list(source.fetch())

    assert len(results) == 1


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
        source = FranceTravailSource(_profile())
        with pytest.raises(Exception):
            list(source.fetch())
