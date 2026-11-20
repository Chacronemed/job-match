"""Talentsoft boards (ADR 0029): the offers RSS feed, read through the `ats` source.

The feed fixture is made up (example.com, invented offers): no production data."""
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from job_match.adapters.jobs import talentsoft
from job_match.adapters.jobs.ats import AtsBoardSource, board_id, board_url
from job_match.adapters.jobs.base import OfferStatus
from job_match.config.schema import AtsBoard
from job_match.domain.models import ContractType, WorkplaceType
from job_match.normalization.location import french_location

FEED = (Path(__file__).parent.parent.parent / "fixtures" / "talentsoft_feed.xml").read_bytes()
TS = AtsBoard(company="Exemple Air", ats="talentsoft", slug="recrutement.example.com")
FEED_URL = "https://recrutement.example.com/handlers/offerRss.ashx?LCID=1036"
GH = AtsBoard(company="Dataiku", ats="greenhouse", slug="dataiku")


def _source(*boards: AtsBoard) -> AtsBoardSource:
    return AtsBoardSource(list(boards), requests_per_second=1000.0)


def _feed(status: int = 200, content: bytes = FEED) -> httpx.Response:
    return httpx.Response(status, content=content, headers={"Content-Type": "text/xml"})


def test_board_url_and_id_are_the_career_site_host():
    assert board_url(TS) == FEED_URL
    assert board_id(TS) == "recrutement.example.com"


def test_parse_feed_keeps_the_offers_with_an_id():
    items = talentsoft.parse_feed(FEED)
    assert [i["id"] for i in items] == ["4101", "4102"]  # the third has no idOffre
    first = items[0]
    assert first["published"] == "2026-11-20T15:36:36+00:00"
    assert first["categories"][1:] == ["CDI", "12 rue de l'Exemple 31100 TOULOUSE"]


def test_parse_feed_refuses_a_page_that_is_not_a_feed():
    with pytest.raises(ValueError):
        talentsoft.parse_feed(b"<html><body>Erreur</body></html>")


@respx.mock
def test_fetch_reads_the_feed_once_and_maps_each_offer():
    route = respx.get(FEED_URL).mock(return_value=_feed())
    src = _source(TS)
    jobs = [src.to_job(item) for item in src.fetch()]

    assert route.call_count == 1  # no detail call: the description is in the feed
    assert "rss" in route.calls[0].request.headers["Accept"]
    job = jobs[0]
    assert job.source == "ats"
    assert job.source_job_id == "talentsoft:recrutement.example.com:4101"
    assert job.title == "Ingénieur DevOps Cloud F/H"  # the "2026-4101 - " reference is dropped
    assert job.company == "Exemple Air"
    assert job.url.startswith("https://recrutement.example.com/Pages/Offre/detailoffre.aspx")
    assert job.location == "12 rue de l'Exemple 31100 TOULOUSE"
    assert french_location(job.location) is True  # the same location gate as any source
    assert job.contract_type is ContractType.CDI
    assert job.workplace_type is WorkplaceType.UNKNOWN  # the feed does not say
    assert "Terraform et Kubernetes" in job.description and "<b>" not in job.description
    assert job.published_at == datetime(2026, 11, 20, 15, 36, 36, tzinfo=UTC)
    assert jobs[1].contract_type is ContractType.STAGE
    assert src.query_stats[0].fetched == 2 and src.query_stats[0].area == "talentsoft"


@respx.mock
def test_since_skips_the_offers_published_before_it():
    respx.get(FEED_URL).mock(return_value=_feed())
    items = list(_source(TS).fetch(since=datetime(2026, 11, 20, tzinfo=UTC)))
    assert [i["id"] for i in items] == ["4101"]


@respx.mock
def test_an_offer_that_left_the_feed_is_unknown_never_closed():
    respx.get(FEED_URL).mock(return_value=_feed())
    src = _source(TS)
    list(src.fetch())
    assert src.check_offer("talentsoft:recrutement.example.com:4101") is OfferStatus.OPEN
    # The feed shows the 20 newest offers only: a missing id proves nothing.
    assert src.check_offer("talentsoft:recrutement.example.com:1") is OfferStatus.UNKNOWN


@respx.mock
def test_a_dead_or_broken_feed_is_skipped_and_the_other_boards_run(caplog):
    respx.get(FEED_URL).mock(return_value=_feed(content=b"<html>maintenance</html>"))
    gone = AtsBoard(company="Parti", ats="talentsoft", slug="recrutement.parti.example")
    respx.get("https://recrutement.parti.example/handlers/offerRss.ashx?LCID=1036").mock(
        return_value=httpx.Response(404))
    respx.get(board_url(GH)).mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": 7, "title": "SRE", "absolute_url": "https://x/7", "location": {"name": "Paris"},
         "content": "Kubernetes"}]}))
    src = _source(TS, gone, GH)
    with caplog.at_level(logging.WARNING):
        items = list(src.fetch())
    assert [i["id"] for i in items] == [7]
    assert "2/3 boards skipped" in caplog.text
    assert src.check_offer("talentsoft:recrutement.example.com:4101") is OfferStatus.UNKNOWN
    # The 404 is an answer (the site moved), the unreadable body a failure.
    assert src.request_stats == (3, 1)
