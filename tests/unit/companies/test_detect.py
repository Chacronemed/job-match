"""`job-match companies detect` (M28): every endpoint mocked with respx, no real request."""
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from job_match.adapters.http import HttpClient
from job_match.companies.detect import (
    CUSTOM,
    NOT_FOUND,
    VERIFIED,
    Detection,
    Detector,
    candidates_in,
    detect_all,
    platforms_in,
    slugs_for,
)
from job_match.companies.report import render_report, write_record
from job_match.config.loader import ConfigError, load_companies
from job_match.config.schema import TargetCompany

WD_AIRBUS = "https://ag.wd3.myworkdayjobs.com/wday/cxs/ag/Airbus/jobs"
SR = "https://api.smartrecruiters.com/v1/companies/{}/postings?limit=1"
GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"
LV = "https://api.lever.co/v0/postings/{}?mode=json"
AB = "https://api.ashbyhq.com/posting-api/job-board/{}"


@pytest.fixture
def detector():
    sleeps: list[float] = []
    d = Detector(http=HttpClient(max_retries=0),
                 page_http=HttpClient(max_retries=0, follow_redirects=True),
                 sleep=sleeps.append)
    d.sleeps = sleeps
    yield d
    d.close()


def _co(name, url=None, guess=None):
    return TargetCompany(name=name, careers_url=url, ats_guess=guess)


def _unmatched_is_404():
    respx.route().mock(return_value=httpx.Response(404))


# ---------------------------------------------------------------------- parsing

def test_slugs_fold_accents_and_drop_legal_words():
    assert slugs_for("Dassault Systèmes") == ["dassaultsystemes", "dassault-systemes"]
    assert slugs_for("Qonto") == ["qonto"]
    assert slugs_for("Groupe SNCF (Connect & Tech)") == ["sncf"]


def test_both_workday_url_forms_give_host_tenant_site():
    found = candidates_in(
        "https://ag.wd3.myworkdayjobs.com/Airbus x "
        "https://thales.wd3.myworkdayjobs.com/fr-FR/Careers/job/123 "
        "https://wd3.myworkdaysite.com/en-US/recruiting/kering/Kering", "url")
    assert [(c.ats, c.identifier) for c in found] == [
        ("workday", "ag.wd3.myworkdayjobs.com/ag/Airbus"),
        ("workday", "thales.wd3.myworkdayjobs.com/thales/Careers"),
        ("workday", "wd3.myworkdaysite.com/kering/Kering"),
    ]


def test_links_in_a_page_are_found_once_and_path_words_are_not_ids():
    html = """<a href="https://jobs.lever.co/mirakl/abc">x</a>
              <a href="https://jobs.lever.co/mirakl">x</a>
              <script src="https://boards.greenhouse.io/embed/job_board/js?for=mirakl"></script>
              <a href="https://jobs.smartrecruiters.com/Ubisoft2/7">x</a>
              <a href="https://jobs.ashbyhq.com/embed">x</a>"""
    found = [(c.ats, c.identifier) for c in candidates_in(html, "page")]
    assert found == [("smartrecruiters", "Ubisoft2"), ("greenhouse", "mirakl"),
                     ("lever", "mirakl")]


def test_platforms_without_a_public_board_are_recognized():
    assert platforms_in("https://bouyguestelecom-recrute.talent-soft.com/") == ["talentsoft"]
    assert platforms_in('<iframe src="https://x.taleo.net/careersection">') == ["taleo"]
    assert platforms_in("<p>nothing here</p>") == []


# ---------------------------------------------------------------------- probing

@respx.mock
def test_workday_from_the_url_is_verified_with_its_total(detector):
    route = respx.post(WD_AIRBUS).mock(return_value=httpx.Response(
        200, json={"total": 812, "jobPostings": [{"title": "x"}], "facets": []}))
    found = detector.detect(_co("Airbus", "https://ag.wd3.myworkdayjobs.com/Airbus", "workday"))
    assert (found.status, found.ats, found.identifier, found.postings, found.method) == (
        VERIFIED, "workday", "ag.wd3.myworkdayjobs.com/ag/Airbus", 812, "url")
    assert found.guess_confirmed is True
    body = route.calls.last.request.content
    assert b'"limit":1' in body.replace(b" ", b"")
    assert detector.requests == 1  # verified at step 1: no page, no slug


@respx.mock
def test_smartrecruiters_with_zero_postings_proves_nothing(detector):
    # An unknown SmartRecruiters company answers 200 with an empty list.
    respx.get(SR.format("Ubisoft2")).mock(
        return_value=httpx.Response(200, json={"totalFound": 0, "content": []}))
    respx.get("https://jobs.smartrecruiters.com/Ubisoft2").mock(return_value=httpx.Response(404))
    _unmatched_is_404()
    found = detector.detect(_co("Ubisoft", "https://jobs.smartrecruiters.com/Ubisoft2",
                                "smartrecruiters"))
    assert found.status == NOT_FOUND
    assert "url smartrecruiters:Ubisoft2 → 0 postings" in found.notes
    assert "page → HTTP 404" in found.notes


@respx.mock
def test_the_careers_page_redirect_and_links_lead_to_the_board(detector):
    respx.get("https://careers.3ds.com/jobs").mock(return_value=httpx.Response(
        301, headers={"Location": "https://careers.3ds.com/fr/jobs"}))
    respx.get("https://careers.3ds.com/fr/jobs").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"},
        text='<a href="https://jobs.smartrecruiters.com/DassaultSystemes/1">Postuler</a>'))
    respx.get(SR.format("DassaultSystemes")).mock(
        return_value=httpx.Response(200, json={"totalFound": 640, "content": [{}]}))
    found = detector.detect(_co("Dassault Systèmes", "https://careers.3ds.com/jobs",
                                "smartrecruiters"))
    assert (found.status, found.ats, found.identifier, found.method) == (
        VERIFIED, "smartrecruiters", "DassaultSystemes", "page")


@respx.mock
def test_a_wrong_lever_guess_falls_through_to_greenhouse_by_slug(detector):
    respx.get(LV.format("mirakl")).mock(return_value=httpx.Response(404))
    respx.get("https://jobs.lever.co/mirakl").mock(return_value=httpx.Response(404))
    respx.get(GH.format("mirakl")).mock(
        return_value=httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]}))
    _unmatched_is_404()
    found = detector.detect(_co("Mirakl", "https://jobs.lever.co/mirakl", "lever"))
    assert (found.status, found.ats, found.identifier, found.method) == (
        VERIFIED, "greenhouse", "mirakl", "slug")
    assert found.guess_confirmed is False
    # lever:mirakl was tried once (url), not again as a slug
    assert sum(1 for c in respx.calls if c.request.url.host == "api.lever.co") == 1


@respx.mock
def test_a_known_platform_page_is_custom(detector):
    respx.get("https://naval-group.talent-soft.com/").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"}, text="<p>Offres</p>"))
    _unmatched_is_404()
    found = detector.detect(_co("Naval Group", "https://naval-group.talent-soft.com/",
                                "talentsoft"))
    assert (found.status, found.platform) == (CUSTOM, "talentsoft")


@respx.mock
def test_an_own_site_without_ats_is_custom_and_an_unreachable_one_not_found(detector):
    respx.get("https://www.padok.fr/carrieres").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"}, text="<h1>Nos offres</h1>"))
    respx.get("https://careers.down.example/").mock(side_effect=httpx.ConnectError("x"))
    _unmatched_is_404()
    own = detector.detect(_co("Padok", "https://www.padok.fr/carrieres", "custom"))
    down = detector.detect(_co("Down", "https://careers.down.example/"))
    assert (own.status, own.platform) == (CUSTOM, None)
    assert down.status == NOT_FOUND and "page → ConnectError" in down.notes


@respx.mock
def test_requests_to_one_host_are_a_second_apart(detector):
    _unmatched_is_404()
    detector.detect(_co("Acme"))  # slugs only: greenhouse, lever, ashby, smartrecruiters
    detector.detect(_co("Beta"))
    assert detector.requests == 8
    assert len(detector.sleeps) == 4  # the second company waits once per host
    assert all(0 < s <= 1.0 for s in detector.sleeps)


@respx.mock
def test_probe_limit_caps_one_company(detector):
    _unmatched_is_404()
    found = detector.detect(_co("Very Long Name"), max_probes=2)
    assert detector.requests == 2 and "probe limit reached" in found.notes


@respx.mock
def test_a_body_that_is_not_the_board_is_not_verified(detector):
    respx.get(AB.format("pigment")).mock(return_value=httpx.Response(200, text="<html>"))
    respx.get("https://jobs.ashbyhq.com/pigment").mock(return_value=httpx.Response(404))
    _unmatched_is_404()
    found = detector.detect(_co("Pigment", "https://jobs.ashbyhq.com/pigment", "ashby"))
    assert found.status == NOT_FOUND and "url ashby:pigment → not JSON" in found.notes


# ---------------------------------------------------------------------- report

@respx.mock
def test_report_groups_by_ats_and_record_is_yaml(detector, tmp_path):
    respx.post(WD_AIRBUS).mock(
        return_value=httpx.Response(200, json={"total": 3, "jobPostings": [{}]}))
    respx.get("https://www.padok.fr/carrieres").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"}, text="<h1>x</h1>"))
    _unmatched_is_404()
    results = detect_all([
        _co("Airbus", "https://ag.wd3.myworkdayjobs.com/Airbus", "workday"),
        _co("Padok", "https://www.padok.fr/carrieres", "custom"),
        _co("Nowhere"),
    ], detector)
    text = render_report(results, requests=detector.requests)
    assert "Vérifiées : **1** · custom : **1** · introuvables : **1**" in text
    assert "### Workday (1)" in text
    assert "`ag.wd3.myworkdayjobs.com/ag/Airbus` | 3 | url | ✓ |  |" in text
    assert "| Padok | site maison |" in text and "| Nowhere | — |" in text

    out = tmp_path / "detected.yaml"
    write_record(results, out, datetime(2026, 11, 5, tzinfo=UTC))
    record = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert record["companies"][0] == {
        "name": "Airbus", "status": "verified", "ats": "workday",
        "id": "ag.wd3.myworkdayjobs.com/ag/Airbus", "postings": 3, "method": "url",
        "ats_guess": "workday"}
    assert record["companies"][2] == {"name": "Nowhere", "status": "not_found"}


def test_a_partial_run_merges_into_the_record(tmp_path):
    out = tmp_path / "detected.yaml"
    when = datetime(2026, 11, 5, tzinfo=UTC)
    write_record([Detection("A", NOT_FOUND), Detection("B", NOT_FOUND),
                  Detection("Gone", NOT_FOUND)], out, when)
    write_record([Detection("B", VERIFIED, "lever", "b", 3, "url")], out, when,
                 merge_into=["A", "B", "C"])
    record = yaml.safe_load(out.read_text(encoding="utf-8"))
    # B replaced, A kept, Gone (left companies.yaml) dropped, C never checked: absent.
    assert [(e["name"], e["status"]) for e in record["companies"]] == [
        ("A", "not_found"), ("B", "verified")]


# ---------------------------------------------------------------------- config

def test_the_shipped_companies_file_loads():
    companies = load_companies(Path("config/companies.yaml"))
    assert len(companies) >= 100
    assert all(c.name and (c.careers_url or "").startswith("http") for c in companies)


def test_companies_file_validation(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("companies:\n- name: A\n  careers_url: javascript:x\n  ats_guess: Lever\n"
                 "- name: B\n", encoding="utf-8")
    a, b = load_companies(p)
    assert (a.careers_url, a.ats_guess) == (None, "lever") and b.careers_url is None
    p.write_text("companies:\n- careers_url: https://x\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_companies(p)
    assert load_companies(tmp_path / "missing.yaml") == []


def test_a_board_id_without_the_company_name_is_flagged():
    from job_match.companies.detect import Detection
    ok = Detection("Dassault Systèmes", VERIFIED, "smartrecruiters", "DassaultSystemes1")
    group = Detection("Padok", VERIFIED, "lever", "theodo")
    tenant = Detection("Airbus", VERIFIED, "workday", "ag.wd3.myworkdayjobs.com/ag/Airbus")
    assert ok.names_company and tenant.names_company and not group.names_company
    assert "⚠ id sans le nom" in render_report([group])
