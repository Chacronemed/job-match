"""Workday and SmartRecruiters boards: French postings only, capped listing, one detail
call per posting, 1 request/s per host."""
import json
import logging
from datetime import UTC, datetime

import httpx
import respx

from job_match.adapters.jobs.ats import (
    BOARD_KEY,
    COMPANY_KEY,
    DETAIL_KEY,
    AtsBoardSource,
    board_id,
    board_url,
)
from job_match.adapters.jobs.base import OfferStatus
from job_match.config.schema import AtsBoard
from job_match.domain.models import ContractType, WorkplaceType

WD = AtsBoard(company="Thales", ats="workday", slug="thales.wd3.myworkdayjobs.com/thales/Careers")
SR = AtsBoard(company="Devoteam", ats="smartrecruiters", slug="Devoteam")
WD_BASE = "https://thales.wd3.myworkdayjobs.com/wday/cxs/thales/Careers"
SR_BASE = "https://api.smartrecruiters.com/v1/companies/Devoteam/postings"
FRANCE_ID = "54c5b6971ffb4bf0b116fe7651ec789a"


def _source(*boards: AtsBoard, **kwargs) -> AtsBoardSource:
    return AtsBoardSource(list(boards), requests_per_second=1000.0, **kwargs)


# ---------------------------------------------------------------------- Workday fixtures

def _facets(france: bool = True) -> list[dict]:
    countries = [{"descriptor": "Spain", "id": "es-id", "count": 3}]
    if france:
        countries.append({"descriptor": "France", "id": FRANCE_ID, "count": 2})
    return [
        {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "IT", "id": "x"}]},
        {"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locationCountry", "descriptor": "Country", "values": countries},
            {"facetParameter": "locations", "descriptor": "Locations",
             "values": [{"descriptor": "Tremblay-en-France", "id": "loc"}]},
        ]},
    ]


def _wd_posting(req: str) -> dict:
    return {"title": f"Ingénieur DevOps {req}", "locationsText": "Brest",
            "externalPath": f"/job/Brest/Ingenieur-DevOps_{req}", "bulletFields": [req]}


def _wd_detail(req: str, **overrides) -> dict:
    info = {
        "title": f"Ingénieur DevOps {req} - CDI", "location": "Brest",
        "additionalLocations": ["Vélizy"], "country": {"descriptor": "France", "id": FRANCE_ID},
        "jobDescription": "<p>Kubernetes &amp; Ansible</p>", "startDate": "2026-11-05",
        "remoteType": "Hybrid", "timeType": "Full time", "jobReqId": req,
        "externalUrl": f"https://thales.wd3.myworkdayjobs.com/Careers/job/Brest/x_{req}",
    }
    return {"jobPostingInfo": {**info, **overrides}}


def _mock_workday(postings: list[dict], total: int | None = None, france: bool = True):
    """First call (limit 1, no facet) → facets; the filtered calls → pages of 20."""
    total = len(postings) if total is None else total

    def jobs(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if not body["appliedFacets"]:
            return httpx.Response(200, json={"total": 5000, "facets": _facets(france),
                                             "jobPostings": [_wd_posting("WORLD")]})
        assert body["appliedFacets"] == {"locationCountry": [FRANCE_ID]}
        assert body["limit"] == 20
        off = body["offset"]
        # Workday only counts on the first page; later pages say 0.
        return httpx.Response(200, json={"total": total if off == 0 else 0,
                                         "jobPostings": postings[off:off + 20]})

    route = respx.post(WD_BASE + "/jobs").mock(side_effect=jobs)
    detail = respx.get(url__startswith=WD_BASE + "/job/").mock(
        side_effect=lambda r: httpx.Response(
            200, json=_wd_detail(str(r.url).rsplit("_", 1)[-1])))
    return route, detail


@respx.mock
def test_workday_lists_french_postings_only_and_reads_each_detail():
    route, detail = _mock_workday([_wd_posting("R1"), _wd_posting("R2")])
    src = _source(WD)
    items = list(src.fetch())
    assert [i["id"] for i in items] == ["R1", "R2"]
    assert route.call_count == 2 and detail.call_count == 2  # facets + 1 page, 2 details
    assert all(i[BOARD_KEY] == "workday:thales.Careers" and i[COMPANY_KEY] == "Thales"
               for i in items)
    stat = src.query_stats[0]
    assert (stat.query, stat.area, stat.fetched, stat.available) == (
        "thales.Careers", "workday", 2, 2)


@respx.mock
def test_workday_mapping():
    _mock_workday([_wd_posting("R0347114-1")])
    src = _source(WD)
    job = src.to_job(next(src.fetch()))
    assert job.source_job_id == "workday:thales.Careers:R0347114-1"
    assert job.title == "Ingénieur DevOps R0347114-1 - CDI"
    assert job.location == "Brest, Vélizy, France"  # the country is added for the gate
    assert job.workplace_type is WorkplaceType.HYBRID
    assert job.contract_type is ContractType.CDI
    assert job.description == "Kubernetes & Ansible"
    assert job.url.startswith("https://thales.wd3.myworkdayjobs.com/Careers/job/")
    assert job.published_at == datetime(2026, 11, 5, tzinfo=UTC)
    assert job.search_query == "thales.Careers"


@respx.mock
def test_workday_pagination_stops_at_the_cap_and_the_listing_is_then_incomplete():
    postings = [_wd_posting(f"R{i}") for i in range(130)]
    route, detail = _mock_workday(postings)
    board = AtsBoard(company="Thales", ats="workday", slug=WD.slug, max_postings=45)
    src = _source(board)
    items = list(src.fetch())
    assert len(items) == 45 and detail.call_count == 45
    assert route.call_count == 1 + 3  # facets, then pages at offsets 0, 20, 40
    assert src.check_offer("workday:thales.Careers:R0") is OfferStatus.OPEN
    # Not listed because of the cap, not because it closed.
    assert src.check_offer("workday:thales.Careers:R100") is OfferStatus.UNKNOWN


@respx.mock
def test_workday_complete_listing_closes_a_missing_id():
    _mock_workday([_wd_posting("R1")])
    src = _source(WD)
    list(src.fetch())
    assert src.check_offer("workday:thales.Careers:R9") is OfferStatus.CLOSED


@respx.mock
def test_workday_without_france_in_the_country_facet_has_no_posting():
    route, detail = _mock_workday([_wd_posting("R1")], france=False)
    src = _source(WD)
    assert list(src.fetch()) == []
    assert route.call_count == 1 and detail.call_count == 0
    assert src.query_stats[0].available == 0


@respx.mock
def test_workday_without_a_country_facet_is_skipped(caplog):
    respx.post(WD_BASE + "/jobs").mock(return_value=httpx.Response(
        200, json={"total": 3, "facets": [], "jobPostings": []}))
    src = _source(WD)
    with caplog.at_level(logging.WARNING):
        assert list(src.fetch()) == []
    assert "no country facet" in caplog.text
    assert src.check_offer("workday:thales.Careers:R1") is OfferStatus.UNKNOWN


@respx.mock
def test_workday_422_and_failed_details_are_skipped_not_raised(caplog):
    respx.get(WD_BASE + "/job/Brest/Ingenieur-DevOps_R1").mock(  # before the catch-all
        return_value=httpx.Response(404))
    _mock_workday([_wd_posting("R1"), _wd_posting("R2")])
    bad = AtsBoard(company="Safran", ats="workday",
                   slug="safran.wd3.myworkdayjobs.com/safran/Wrong")
    respx.post("https://safran.wd3.myworkdayjobs.com/wday/cxs/safran/Wrong/jobs").mock(
        return_value=httpx.Response(422))
    with caplog.at_level(logging.WARNING):
        items = list(_source(bad, WD).fetch())
    assert [i["id"] for i in items] == ["R2"]
    assert "1/2 boards skipped" in caplog.text


def test_board_id_and_url_for_workday():
    assert board_id(WD) == "thales.Careers"
    assert board_url(WD) == WD_BASE + "/jobs"


# ---------------------------------------------------------------------- SmartRecruiters

def _sr_posting(pid: str, **overrides) -> dict:
    base = {"id": pid, "name": f"DevOps {pid}", "releasedDate": "2026-11-05T09:42:53.873Z",
            "company": {"identifier": "Devoteam", "name": "Devoteam"},
            "location": {"city": "Lyon", "country": "fr", "remote": False, "hybrid": True,
                         "fullLocation": "Lyon, Auvergne-Rhône-Alpes, France"},
            "typeOfEmployment": {"id": "permanent", "label": "Full-time"}}
    return {**base, **overrides}


def _sr_detail(pid: str) -> dict:
    return {**_sr_posting(pid),
            "postingUrl": f"https://jobs.smartrecruiters.com/Devoteam/{pid}-devops",
            "jobAd": {"sections": {
                "companyDescription": {"title": "Entreprise", "text": "<p>Devoteam</p>"},
                "jobDescription": {"title": "Poste", "text": "<p>Terraform sur AWS</p>"},
                "qualifications": {"title": "Profil", "text": "<ul><li>Kubernetes</li></ul>"},
            }}}


def _mock_sr(postings: list[dict]):
    def listing(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["country"] == "fr" and params["limit"] == "100"
        off = int(params["offset"])
        return httpx.Response(200, json={"totalFound": len(postings),
                                         "content": postings[off:off + 100]})

    route = respx.get(SR_BASE).mock(side_effect=listing)
    detail = respx.get(url__regex=SR_BASE + r"/\d+$").mock(
        side_effect=lambda r: httpx.Response(200, json=_sr_detail(str(r.url).rsplit("/", 1)[-1])))
    return route, detail


@respx.mock
def test_smartrecruiters_lists_france_and_maps_the_detail():
    route, detail = _mock_sr([_sr_posting("744000159821589")])
    src = _source(SR)
    items = list(src.fetch())
    assert route.call_count == 1 and detail.call_count == 1
    job = src.to_job(items[0])
    assert job.source_job_id == "smartrecruiters:Devoteam:744000159821589"
    assert job.title == "DevOps 744000159821589"
    assert job.location == "Lyon, Auvergne-Rhône-Alpes, France"
    assert job.workplace_type is WorkplaceType.HYBRID
    assert job.contract_type is ContractType.CDI  # typeOfEmployment.id "permanent"
    assert job.description.splitlines() == ["Terraform sur AWS", "Kubernetes", "Devoteam"]
    assert job.url == "https://jobs.smartrecruiters.com/Devoteam/744000159821589-devops"
    assert job.published_at == datetime(2026, 11, 5, 9, 42, 53, 873000, tzinfo=UTC)
    assert DETAIL_KEY in items[0]


@respx.mock
def test_smartrecruiters_pages_up_to_the_cap():
    postings = [_sr_posting(str(1000 + i)) for i in range(250)]
    route, detail = _mock_sr(postings)
    board = AtsBoard(company="Devoteam", ats="smartrecruiters", slug="Devoteam",
                     max_postings=150)
    src = _source(board)
    assert len(list(src.fetch())) == 150
    assert route.call_count == 2 and detail.call_count == 150
    assert src.query_stats[0].available == 250
    assert src.check_offer("smartrecruiters:Devoteam:1249") is OfferStatus.UNKNOWN


@respx.mock
def test_smartrecruiters_since_skips_old_postings_before_the_detail_call():
    route, detail = _mock_sr([_sr_posting("1", releasedDate="2020-01-01T00:00:00Z"),
                              _sr_posting("2")])
    items = list(_source(SR).fetch(since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [i["id"] for i in items] == ["2"] and detail.call_count == 1


@respx.mock
def test_max_results_also_caps_the_paged_listing():
    _route, detail = _mock_sr([_sr_posting(str(i)) for i in range(1, 10)])
    assert len(list(_source(SR, max_results=3).fetch())) == 3
    assert detail.call_count == 3


# ---------------------------------------------------------------------- throttling

@respx.mock
def test_one_request_per_second_per_host_not_across_hosts():
    _mock_workday([_wd_posting("R1")])
    _mock_sr([_sr_posting("1")])
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    src = AtsBoardSource([WD, SR], requests_per_second=1.0, sleep=sleep,
                         clock=lambda: now[0])
    list(src.fetch())
    # Workday: facets, page, detail → 2 waits; SmartRecruiters (another host): its first
    # call does not wait, its detail does.
    assert waits == [1.0, 1.0, 1.0]
