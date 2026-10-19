"""M20: `FranceTravailSource.check_offer` — one throttled detail call, three answers."""
import json
from pathlib import Path

import httpx
import pytest
import respx

from job_match.adapters.jobs.base import OfferStatus
from job_match.adapters.jobs.france_travail import DETAIL_URL, TOKEN_URL, FranceTravailSource
from job_match.config.schema import Candidate, Filters, FTSearch, Profile, Skills

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
OFFER_ID = "214LHTD"
OFFER_URL = DETAIL_URL.format(id=OFFER_ID)


def _token() -> dict:
    return json.loads((FIXTURES / "ft_token.json").read_text(encoding="utf-8"))


def _source(**kwargs) -> FranceTravailSource:
    profile = Profile(candidate=Candidate(experience_years=5), skills=Skills(),
                      filters=Filters(), ft_search=FTSearch(keywords=["devops"]))
    kwargs.setdefault("requests_per_second", 1000.0)
    return FranceTravailSource(profile, **kwargs)


@pytest.fixture(autouse=True)
def ft_env(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "test-id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("job_match.adapters.http.time.sleep", lambda _: None)


def _mock_detail(*responses):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_token()))
    return respx.get(OFFER_URL).mock(side_effect=list(responses))


@respx.mock
def test_200_is_open():
    route = _mock_detail(httpx.Response(200, json={"id": OFFER_ID, "intitule": "DevOps"}))
    source = _source()
    assert source.check_offer(OFFER_ID) is OfferStatus.OPEN
    assert route.call_count == 1
    assert source.api_calls_count == 1
    assert route.calls[0].request.headers["Authorization"].startswith("Bearer ")


@respx.mock
def test_204_empty_body_is_closed():
    """Measured 2026-10-19: a withdrawn offer answers 204 No Content."""
    _mock_detail(httpx.Response(204))
    assert _source().check_offer(OFFER_ID) is OfferStatus.CLOSED


@respx.mock
def test_404_is_closed():
    _mock_detail(httpx.Response(404))
    assert _source().check_offer(OFFER_ID) is OfferStatus.CLOSED


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403])
def test_refused_request_is_unknown(status):
    _mock_detail(httpx.Response(status))
    source = _source()
    assert source.check_offer(OFFER_ID) is OfferStatus.UNKNOWN
    assert source.api_calls_count == 1


@respx.mock
def test_5xx_after_retries_is_unknown():
    route = _mock_detail(*[httpx.Response(503)] * 4)  # HttpClient: 3 retries
    assert _source().check_offer(OFFER_ID) is OfferStatus.UNKNOWN
    assert route.call_count == 4


@respx.mock
def test_transport_error_is_unknown_not_closed():
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    _mock_detail(boom)
    source = _source()
    assert source.check_offer(OFFER_ID) is OfferStatus.UNKNOWN
    assert source.api_calls_count == 1


@respx.mock
def test_timeout_is_unknown():
    def slow(request):
        raise httpx.ReadTimeout("timeout", request=request)

    _mock_detail(*[slow] * 4)
    assert _source().check_offer(OFFER_ID) is OfferStatus.UNKNOWN


@respx.mock
def test_token_is_fetched_once_and_a_token_failure_propagates():
    token_route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_token()))
    respx.get(OFFER_URL).mock(return_value=httpx.Response(204))
    source = _source()
    source.check_offer(OFFER_ID)
    source.check_offer(OFFER_ID)
    assert token_route.call_count == 1
    assert source.api_calls_count == 2

    token_route.mock(return_value=httpx.Response(401, json={"error": "invalid_client"}))
    with pytest.raises(httpx.HTTPStatusError):
        _source().check_offer(OFFER_ID)


@respx.mock
def test_check_is_throttled_like_the_search(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(
        "job_match.adapters.jobs.france_travail.time.sleep", lambda s: slept.append(s)
    )
    _mock_detail(httpx.Response(204), httpx.Response(204))
    source = _source(requests_per_second=2.0)
    source.check_offer(OFFER_ID)
    source.check_offer(OFFER_ID)
    assert slept and all(0 < s <= 0.5 for s in slept)


@respx.mock
def test_the_url_carries_the_offer_id_and_no_query():
    route = _mock_detail(httpx.Response(204))
    _source().check_offer(OFFER_ID)
    url = str(route.calls[0].request.url)
    assert url.endswith("/offres/" + OFFER_ID) and "?" not in url
