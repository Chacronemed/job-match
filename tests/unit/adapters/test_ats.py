"""ATS board adapter: one GET per board, three payload shapes, dead boards skipped."""
import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx

from job_match.adapters.jobs.ats import (
    BOARD_KEY,
    COMPANY_KEY,
    AtsBoardSource,
    board_url,
)
from job_match.adapters.jobs.base import OfferStatus, source_payload
from job_match.config.schema import AtsBoard
from job_match.domain.models import ContractType, WorkplaceType

GH = AtsBoard(company="Dataiku", ats="greenhouse", slug="dataiku")
LV = AtsBoard(company="Scaleway", ats="lever", slug="scaleway")
AB = AtsBoard(company="Alan", ats="ashby", slug="alan")


def _source(*boards: AtsBoard, **kwargs) -> AtsBoardSource:
    return AtsBoardSource(list(boards), requests_per_second=1000.0, **kwargs)


def _gh_job(job_id: int = 6236322004, **overrides) -> dict:
    base = {
        "id": job_id,
        "title": "Site Reliability Engineer",
        "absolute_url": f"https://job-boards.greenhouse.io/dataiku/jobs/{job_id}",
        "location": {"name": "France, Paris"},
        "first_published": "2026-10-27T12:11:11-04:00",
        "updated_at": "2026-11-02T10:32:19-05:00",
        # Greenhouse entity-encodes the markup itself.
        "content": ("&lt;p&gt;Kubernetes &amp;amp; Terraform.&lt;/p&gt;"
                    "&lt;ul&gt;&lt;li&gt;CDI&lt;/li&gt;&lt;/ul&gt;"),
        "departments": [{"id": 1, "name": "Engineering"}],
    }
    return {**base, **overrides}


def _lever_job(job_id: str = "4c52f6fd", **overrides) -> dict:
    base = {
        "id": job_id,
        "text": "DevOps Engineer",
        "hostedUrl": f"https://jobs.lever.co/scaleway/{job_id}",
        "categories": {
            "commitment": "CDI",
            "team": "Infrastructure",
            "location": "Paris",
            "allLocations": ["Paris", "Lille"],
        },
        "workplaceType": "hybrid",
        "createdAt": 1761566400000,  # 2025-10-27T12:00:00Z
        "descriptionPlain": "Join the sovereign cloud.",
        "lists": [{"text": "Stack", "content": "<li>Kubernetes</li><li>Ansible</li>"}],
        "additionalPlain": "We are an equal opportunity employer.",
    }
    return {**base, **overrides}


def _ashby_job(job_id: str = "40f9c790", **overrides) -> dict:
    base = {
        "id": job_id,
        "title": "Platform Engineer",
        "jobUrl": f"https://jobs.ashbyhq.com/alan/{job_id}",
        "location": "Paris, France",
        "address": {"postalAddress": {"addressLocality": "Paris", "addressCountry": "France"}},
        "secondaryLocations": [{"location": "Lyon, France"}],
        "publishedAt": "2026-09-09T13:17:05.420+00:00",
        "employmentType": "FullTime",
        "workplaceType": None,
        "isRemote": True,
        "isListed": True,
        "descriptionPlain": "Terraform on AWS. Poste en CDI.",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# to_job mapping, one case per ATS
# ---------------------------------------------------------------------------

def test_greenhouse_mapping_decodes_entity_encoded_html():
    raw = {**_gh_job(), BOARD_KEY: "greenhouse:dataiku", COMPANY_KEY: "Dataiku"}
    job = _source(GH).to_job(raw)
    assert job.source == "ats"
    assert job.source_job_id == "greenhouse:dataiku:6236322004"
    assert job.company == "Dataiku"
    assert job.title == "Site Reliability Engineer"
    assert job.location == "France, Paris"
    assert job.url == "https://job-boards.greenhouse.io/dataiku/jobs/6236322004"
    assert job.description == "Kubernetes & Terraform.\nCDI"
    assert "<" not in job.description
    assert job.contract_type is ContractType.CDI
    assert job.workplace_type is WorkplaceType.UNKNOWN
    assert job.published_at == datetime(2026, 10, 27, 16, 11, 11, tzinfo=UTC)
    assert job.search_query == "dataiku"


def test_lever_mapping_folds_lists_and_reads_epoch_ms():
    raw = {**_lever_job(), BOARD_KEY: "lever:scaleway", COMPANY_KEY: "Scaleway"}
    job = _source(LV).to_job(raw)
    assert job.source_job_id == "lever:scaleway:4c52f6fd"
    assert job.title == "DevOps Engineer"
    assert job.location == "Paris, Lille"
    assert job.workplace_type is WorkplaceType.HYBRID
    assert job.contract_type is ContractType.CDI  # from categories.commitment
    assert job.description.splitlines() == [
        "Join the sovereign cloud.", "Stack", "Kubernetes", "Ansible",
        "We are an equal opportunity employer.",
    ]
    assert job.published_at == datetime(2025, 10, 27, 12, 0, tzinfo=UTC)


def test_ashby_mapping_merges_locations_and_isremote_fallback():
    raw = {**_ashby_job(), BOARD_KEY: "ashby:alan", COMPANY_KEY: "Alan"}
    job = _source(AB).to_job(raw)
    assert job.source_job_id == "ashby:alan:40f9c790"
    assert job.location == "Paris, France, Lyon, France"  # address adds nothing new
    assert job.workplace_type is WorkplaceType.REMOTE
    assert job.contract_type is ContractType.CDI  # "Poste en CDI" in the text, FullTime ignored
    assert job.published_at == datetime(2026, 9, 9, 13, 17, 5, 420000, tzinfo=UTC)


def test_ashby_intern_employment_type_is_a_contract_hint():
    raw = {**_ashby_job(employmentType="Intern", descriptionPlain="x"),
           BOARD_KEY: "ashby:alan", COMPANY_KEY: "Alan"}
    assert _source(AB).to_job(raw).contract_type is ContractType.STAGE


def test_company_comes_from_config_not_from_the_source():
    raw = {**_gh_job(company_name="DATAIKU SAS"), BOARD_KEY: "greenhouse:dataiku",
           COMPANY_KEY: "Dataiku"}
    assert _source(GH).to_job(raw).company == "Dataiku"


def test_annotations_are_dropped_from_the_stored_payload():
    raw = {**_lever_job(), BOARD_KEY: "lever:scaleway", COMPANY_KEY: "Scaleway"}
    assert BOARD_KEY not in source_payload(raw)
    assert COMPANY_KEY not in source_payload(raw)


# ---------------------------------------------------------------------------
# fetch: one call per board, each ATS shape, errors isolated
# ---------------------------------------------------------------------------

@respx.mock
def test_fetch_reads_each_board_once_and_annotates_items():
    gh = respx.get(board_url(GH)).mock(return_value=httpx.Response(200, json={"jobs": [_gh_job()]}))
    lv = respx.get(board_url(LV)).mock(return_value=httpx.Response(200, json=[_lever_job()]))
    ab = respx.get(board_url(AB)).mock(
        return_value=httpx.Response(200, json={"apiVersion": "1", "jobs": [_ashby_job()]})
    )
    src = _source(GH, LV, AB)
    items = list(src.fetch())
    assert [i[BOARD_KEY] for i in items] == ["greenhouse:dataiku", "lever:scaleway", "ashby:alan"]
    assert [i[COMPANY_KEY] for i in items] == ["Dataiku", "Scaleway", "Alan"]
    assert gh.call_count == lv.call_count == ab.call_count == 1
    assert src.api_calls_count == 3
    assert "content=true" in str(gh.calls[0].request.url)
    stats = src.query_stats
    assert [(s.query, s.area, s.fetched, s.available, s.source) for s in stats] == [
        ("dataiku", "greenhouse", 1, 1, "ats"),
        ("scaleway", "lever", 1, 1, "ats"),
        ("alan", "ashby", 1, 1, "ats"),
    ]
    jobs = [src.to_job(i) for i in items]
    assert {j.source for j in jobs} == {"ats"}


@respx.mock
def test_a_404_board_is_skipped_and_the_others_still_run(caplog):
    respx.get(board_url(GH)).mock(return_value=httpx.Response(404, text="Not Found"))
    respx.get(board_url(LV)).mock(return_value=httpx.Response(200, json=[_lever_job()]))
    src = _source(GH, LV)
    with caplog.at_level(logging.WARNING):
        items = list(src.fetch())
    assert [i["id"] for i in items] == ["4c52f6fd"]
    assert "greenhouse/dataiku answers 404" in caplog.text
    assert "1/2 boards skipped" in caplog.text
    assert src.query_stats[0].available is None  # unknown, not zero


@respx.mock
def test_network_errors_and_bad_payloads_never_raise(caplog):
    respx.get(board_url(GH)).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(board_url(LV)).mock(return_value=httpx.Response(200, json={"error": "nope"}))
    respx.get(board_url(AB)).mock(return_value=httpx.Response(500, text="oops"))
    src = _source(GH, LV, AB)
    with caplog.at_level(logging.WARNING):
        assert list(src.fetch()) == []
    assert "3/3 boards skipped" in caplog.text


@respx.mock
def test_items_without_an_id_and_unlisted_ashby_jobs_are_dropped():
    respx.get(board_url(AB)).mock(return_value=httpx.Response(200, json={"jobs": [
        _ashby_job("keep"),
        _ashby_job("hidden", isListed=False),
        {"title": "no id"},
    ]}))
    assert [i["id"] for i in _source(AB).fetch()] == ["keep"]


@respx.mock
def test_max_results_caps_each_board_not_the_run():
    respx.get(board_url(GH)).mock(return_value=httpx.Response(
        200, json={"jobs": [_gh_job(1), _gh_job(2), _gh_job(3)]}))
    respx.get(board_url(LV)).mock(return_value=httpx.Response(
        200, json=[_lever_job("a"), _lever_job("b")]))
    items = list(_source(GH, LV, max_results=2).fetch())
    assert [i["id"] for i in items] == [1, 2, "a", "b"]


@respx.mock
def test_since_filters_on_the_posting_date_when_known():
    respx.get(board_url(LV)).mock(return_value=httpx.Response(200, json=[
        _lever_job("old", createdAt=1000),
        _lever_job("new"),
        _lever_job("undated", createdAt=None),
    ]))
    items = list(_source(LV).fetch(since=datetime(2025, 1, 1, tzinfo=UTC)))
    assert [i["id"] for i in items] == ["new", "undated"]


def test_no_board_configured_yields_nothing(caplog):
    with caplog.at_level(logging.WARNING):
        assert list(_source().fetch()) == []
    assert "no board configured" in caplog.text


def test_lever_crawl_delay_is_respected_by_default():
    assert AtsBoardSource([LV])._min_interval == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# check_offer: the board fetched this run answers for every offer of it
# ---------------------------------------------------------------------------

@respx.mock
def test_check_offer_reuses_the_board_read_by_fetch():
    route = respx.get(board_url(LV)).mock(return_value=httpx.Response(200, json=[_lever_job("a")]))
    src = _source(LV)
    list(src.fetch())
    assert src.check_offer("lever:scaleway:a") is OfferStatus.OPEN
    assert src.check_offer("lever:scaleway:gone") is OfferStatus.CLOSED
    assert route.call_count == 1


@respx.mock
def test_check_offer_reads_the_board_once_when_fetch_did_not_run():
    route = respx.get(board_url(GH)).mock(
        return_value=httpx.Response(200, json={"jobs": [_gh_job(7)]}))
    src = _source(GH)
    assert src.check_offer("greenhouse:dataiku:7") is OfferStatus.OPEN
    assert src.check_offer("greenhouse:dataiku:8") is OfferStatus.CLOSED
    assert route.call_count == 1


@respx.mock
def test_check_offer_is_unknown_for_dead_or_unconfigured_boards():
    respx.get(board_url(GH)).mock(return_value=httpx.Response(503))
    src = _source(GH)
    assert src.check_offer("greenhouse:dataiku:7") is OfferStatus.UNKNOWN
    assert src.check_offer("lever:elsewhere:7") is OfferStatus.UNKNOWN
    assert src.check_offer("garbage") is OfferStatus.UNKNOWN
