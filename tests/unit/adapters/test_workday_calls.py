"""Workday called as little as possible (ADR 0020, amendment 2026-11-20, part 2): a search by
keyword instead of the whole listing, a detail call only for a posting worth one, a cap of
calls per tenant and run, one read a week per tenant, and a security check that stops the
tenant at once. Plus SmartRecruiters searched by keyword. A fake server, no network."""
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import httpx
import respx

from job_match.adapters.jobs import workday
from job_match.adapters.jobs.ats import COMPANY_KEY, AtsBoardSource
from job_match.adapters.jobs.base import OfferStatus
from job_match.adapters.jobs.factory import paged_title_filter
from job_match.config.loader import load_settings
from job_match.config.schema import AtsBoard, WorkdayConfig

FRANCE_ID = "54c5b6971ffb4bf0b116fe7651ec789a"
KEYWORDS = ("devops", "cloud", "sre", "platform")
THALES = AtsBoard(company="Thales", ats="workday",
                  slug="thales.wd3.myworkdayjobs.com/thales/Careers")
AIRBUS = AtsBoard(company="Airbus", ats="workday", slug="ag.wd3.myworkdayjobs.com/ag/Airbus")
MONDAY = date(2026, 11, 23)
SECURITY_CHECK = httpx.Response(  # what Workday's edge answers since 2026-11-16
    429, headers={"Content-Type": "text/html; charset=UTF-8"},
    content=b"<html><body>Security Check - Enable JavaScript and cookies</body></html>")


def _posting(req: str, title: str, days: int = 3) -> dict:
    posted = {0: "Posted Today", 1: "Posted Yesterday"}.get(
        days, "Posted 30+ Days Ago" if days > 30 else f"Posted {days} Days Ago")
    return {"title": title, "locationsText": "Toulouse", "postedOn": posted,
            "externalPath": f"/job/Toulouse/{title.replace(' ', '-')}_{req}"}


class FakeTenant:
    """One Workday site: the facets call, the filtered search, the probe on one
    requisition id, the posting detail. Every request is recorded."""

    def __init__(self, board: AtsBoard, postings: list[dict], country_facet: bool = True):
        host, tenant, site = board.slug.split("/", 2)
        self.base = f"https://{host}/wday/cxs/{tenant}/{site}"
        self.postings = postings
        self.country_facet = country_facet
        self.searches: list[dict] = []   # every POST body, in order
        self.details: list[str] = []     # every posting id read in full
        self.answers: list[httpx.Response] = []  # scripted answers, served first
        self.jobs = respx.post(self.base + "/jobs").mock(side_effect=self._jobs)
        self.detail = respx.get(url__startswith=self.base + "/job/").mock(
            side_effect=self._detail)

    @property
    def calls(self) -> int:
        return self.jobs.call_count + self.detail.call_count

    def _facets(self) -> list[dict]:
        if self.country_facet:
            group = {"facetParameter": "locationCountry", "values": [
                {"descriptor": "Spain", "id": "es"}, {"descriptor": "France", "id": FRANCE_ID}]}
        else:
            group = {"facetParameter": "locations", "values": [
                {"descriptor": "Paris", "id": "par"}, {"descriptor": "Milan", "id": "mil"}]}
        return [{"facetParameter": "locationMainGroup", "values": [group]}]

    def _jobs(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.searches.append(body)
        if self.answers:
            return self.answers.pop(0)
        text = body["searchText"].lower()
        if not body["appliedFacets"]:
            if not text:
                return httpx.Response(200, json={"total": 9999, "facets": self._facets()})
            hits = [p for p in self.postings
                    if p["externalPath"].endswith("_" + body["searchText"])]
            return httpx.Response(200, json={"total": len(hits), "jobPostings": hits})
        hits = [p for p in self.postings if all(w in p["title"].lower() for w in text.split())]
        off = body["offset"]
        return httpx.Response(200, json={"total": len(hits) if off == 0 else 0,
                                         "jobPostings": hits[off:off + body["limit"]]})

    def _detail(self, request: httpx.Request) -> httpx.Response:
        if self.answers:
            return self.answers.pop(0)
        req = str(request.url).rsplit("_", 1)[-1]
        self.details.append(req)
        title = next(p["title"] for p in self.postings if p["externalPath"].endswith("_" + req))
        return httpx.Response(200, json={"jobPostingInfo": {
            "title": title, "location": "Toulouse", "country": {"descriptor": "France"},
            "jobDescription": "<p>Kubernetes, Terraform</p>", "startDate": "2026-11-18",
            "externalUrl": f"https://example.test/job/{req}"}})


class Waits:
    def __init__(self) -> None:
        self.now, self.waits = 0.0, []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def _source(*boards: AtsBoard, today: date = MONDAY, keywords=KEYWORDS, waits: Waits | None = None,
            title_filter=None, **workday_cfg) -> AtsBoardSource:
    cfg = {"request_delay_seconds": 0, "backoff_seconds": 5, "frequency_days": 1,
           "max_calls_per_run": 15, **workday_cfg}
    waits = waits or Waits()
    return AtsBoardSource(list(boards), requests_per_second=1000.0, sleep=waits.sleep,
                          clock=waits.clock, workday=WorkdayConfig(**cfg),
                          keywords=keywords, title_filter=title_filter, today=today)


def _is_ours(title: str) -> bool:
    return any(w in title.lower() for w in ("devops", "sre", "platform", "cloud engineer"))


# ---------------------------------------------------------------------- filtered search

@respx.mock
def test_one_search_per_keyword_with_the_france_facet_instead_of_the_whole_listing():
    postings = [_posting("R1", "Ingénieur DevOps"), _posting("R2", "DevOps Cloud Engineer"),
                _posting("R3", "Cloud Engineer"), _posting("R4", "Acheteur Cloud"),
                *[_posting(f"X{i}", "Ingénieur mécanique") for i in range(300)]]
    tenant = FakeTenant(THALES, postings)

    items = list(_source(THALES, title_filter=_is_ours).fetch())

    assert [(b["searchText"], b["limit"], b["offset"]) for b in tenant.searches] == [
        ("", 1, 0), ("devops", 20, 0), ("cloud", 20, 0), ("sre", 20, 0), ("platform", 20, 0)]
    assert all(b["appliedFacets"] == {"locationCountry": [FRANCE_ID]}
               for b in tenant.searches[1:])
    # R2 answers two keywords and is read once; R4 is listed but its title is not ours.
    assert sorted(tenant.details) == ["R1", "R2", "R3"]
    assert sorted(i["id"] for i in items) == ["R1", "R2", "R3"]
    assert tenant.calls == 1 + 4 + 3  # the listing took 1 + 5 pages + 100 details


@respx.mock
def test_a_board_without_a_country_facet_is_searched_on_its_french_locations():
    tenant = FakeTenant(THALES, [_posting("R1", "Ingénieur DevOps")], country_facet=False)
    list(_source(THALES, keywords=("devops",)).fetch())
    assert tenant.searches[1]["appliedFacets"] == {"locations": ["par"]}


@respx.mock
def test_without_keywords_the_whole_french_board_is_listed_as_before():
    tenant = FakeTenant(THALES, [_posting(f"R{i}", "Ingénieur DevOps") for i in range(45)])
    items = list(_source(THALES, keywords=(), max_calls_per_run=0).fetch())
    assert [b["offset"] for b in tenant.searches[1:]] == [0, 20, 40]
    assert len(items) == 45 and tenant.calls == 1 + 3 + 45


# ---------------------------------------------------------------------- detail calls

@respx.mock
def test_a_posting_already_stored_gets_no_detail_call_and_is_still_known_open():
    tenant = FakeTenant(THALES, [_posting("R1", "Ingénieur DevOps"),
                                 _posting("R2", "Ingénieur DevOps Senior")])
    src = _source(THALES, keywords=("devops",))
    src.set_known_ids({"workday:thales.Careers:R1", "greenhouse:dataiku:7"})

    items = list(src.fetch())

    assert tenant.details == ["R2"] and [i["id"] for i in items] == ["R2"]
    assert src.check_offer("workday:thales.Careers:R1") is OfferStatus.OPEN  # listed today
    assert src.listed_by_board == {"workday:thales.Careers": 2}  # not an empty board


@respx.mock
def test_the_freshest_postings_get_the_detail_calls_the_cap_leaves():
    postings = [_posting("OLD", "Ingénieur DevOps", days=40),
                _posting("WEEK", "Ingénieur DevOps", days=6),
                _posting("TODAY", "Ingénieur DevOps", days=0),
                _posting("YDAY", "Ingénieur DevOps", days=1)]
    tenant = FakeTenant(THALES, postings)
    src = _source(THALES, max_calls_per_run=7)  # 1 facets + 4 keywords + 2 details

    items = list(src.fetch())

    assert tenant.details == ["TODAY", "YDAY"] and len(items) == 2
    assert tenant.calls == 7  # never an eighth request
    assert src.board_statuses == [{
        "board": "workday:thales.Careers", "company": "Thales", "status": "capped",
        "calls": 7, "listed": 4, "fetched": 2, "due_in": 0}]
    # A stored offer the search did not list cannot be probed any more: not asked, and
    # not an error either.
    assert src.check_offer("workday:thales.Careers:GONE") is OfferStatus.NOT_ASKED
    assert tenant.calls == 7


@respx.mock
def test_retries_and_closure_probes_count_in_the_cap():
    tenant = FakeTenant(THALES, [_posting("R1", "Ingénieur DevOps")])
    tenant.answers = [httpx.Response(503), httpx.Response(503)]  # facets: third try answers
    waits = Waits()
    src = _source(THALES, keywords=("devops",), waits=waits, max_calls_per_run=6, max_retries=2)

    list(src.fetch())  # 3 (facets, twice retried) + 1 search + 1 detail
    assert waits.waits == [5.0, 10.0] and tenant.calls == 5
    assert src.check_offer("workday:thales.Careers:R9") is OfferStatus.CLOSED  # 6th: a probe
    assert src.check_offer("workday:thales.Careers:R8") is OfferStatus.NOT_ASKED  # cap
    assert tenant.calls == 6 and src.board_statuses[0]["calls"] == 6
    assert src.board_statuses[0]["status"] == "capped"


# ---------------------------------------------------------------------- security check

@respx.mock
def test_a_security_check_stops_the_tenant_at_once_without_a_retry(caplog):
    blocked = FakeTenant(THALES, [_posting("R1", "Ingénieur DevOps")])
    blocked.answers = [SECURITY_CHECK]
    other = FakeTenant(AIRBUS, [_posting("A1", "Ingénieur DevOps")])
    waits = Waits()
    src = _source(THALES, AIRBUS, keywords=("devops",), waits=waits, max_retries=2)

    with caplog.at_level(logging.WARNING):
        items = list(src.fetch())

    assert blocked.calls == 1 and waits.waits == []  # one request, no retry, no wait
    assert "HTTP 429 (security check page): anti-robot protection, not retried" in caplog.text
    assert [(i[COMPANY_KEY], i["id"]) for i in items] == [("Airbus", "A1")]  # the run goes on
    statuses = {b["company"]: b["status"] for b in src.board_statuses}
    assert statuses == {"Thales": "blocked", "Airbus": "ok"}
    # Counted once by its status: no board at 0 for the outage guard, no closure error.
    assert "workday:thales.Careers" not in src.listed_by_board
    assert [q.query for q in src.query_stats] == ["ag.Airbus"]
    assert src.check_offer("workday:thales.Careers:R1") is OfferStatus.NOT_ASKED
    assert blocked.calls == 1 and other.calls == 3
    assert src.request_stats == (4, 1)


@respx.mock
def test_a_security_check_in_the_middle_keeps_what_was_read_and_asks_nothing_more():
    tenant = FakeTenant(THALES, [_posting(f"R{i}", "Ingénieur DevOps", days=i) for i in range(5)])
    src = _source(THALES, keywords=("devops",))
    seen: list[str] = []
    for item in src.fetch():
        seen.append(item["id"])
        if len(seen) == 2:
            tenant.answers = [SECURITY_CHECK]  # the third detail is refused

    assert seen == ["R0", "R1"]
    assert tenant.calls == 1 + 1 + 3  # the last two details were never asked
    assert src.board_statuses[0] == {
        "board": "workday:thales.Careers", "company": "Thales", "status": "blocked",
        "calls": 5, "listed": 5, "fetched": 2, "due_in": 0}


@respx.mock
def test_the_same_page_served_with_a_403_is_a_security_check_too():
    tenant = FakeTenant(THALES, [])
    tenant.answers = [httpx.Response(403, headers={"Content-Type": "text/html"},
                                     content=b"<html>Attention Required!</html>")]
    src = _source(THALES)
    assert list(src.fetch()) == [] and tenant.calls == 1
    assert src.board_statuses[0]["status"] == "blocked"


# ---------------------------------------------------------------------- frequency

def _eleven_boards() -> list[AtsBoard]:
    return [AtsBoard(company=f"C{i}", ats="workday",
                     slug=f"c{i}.wd3.myworkdayjobs.com/c{i}/Jobs") for i in range(11)]


@respx.mock
def test_each_tenant_is_read_once_a_week_and_the_tenants_are_spread_over_the_days():
    boards = _eleven_boards()
    tenants = {b.company: FakeTenant(b, [_posting("R1", "Ingénieur DevOps")]) for b in boards}
    read_on: dict[str, list[int]] = {b.company: [] for b in boards}
    per_day: list[int] = []
    for day in range(14):
        src = _source(*boards, today=MONDAY + timedelta(days=day), keywords=("devops",),
                      frequency_days=7)
        before = {name: t.calls for name, t in tenants.items()}
        list(src.fetch())
        read = [name for name, t in tenants.items() if t.calls > before[name]]
        for name in read:
            read_on[name].append(day)
        per_day.append(len(read))
        # A board that is not read makes no call at all and says when it is next.
        skipped = [b for b in src.board_statuses if b["status"] == "skipped"]
        assert len(skipped) == 11 - len(read) and all(1 <= b["due_in"] <= 6 for b in skipped)

    assert all(len(days) == 2 and days[1] - days[0] == 7 for days in read_on.values())
    assert max(per_day) == 2 and min(per_day) == 1  # 11 boards over 7 days


@respx.mock
def test_a_skipped_tenant_is_neither_an_error_nor_an_empty_board():
    boards = _eleven_boards()[:2]
    tenants = [FakeTenant(b, [_posting("R1", "Ingénieur DevOps")]) for b in boards]
    day = next(MONDAY + timedelta(days=d) for d in range(7)
               if workday.due_in_days(0, 7, MONDAY + timedelta(days=d)) == 0)
    src = _source(*boards, today=day, keywords=("devops",), frequency_days=7)

    list(src.fetch())

    assert tenants[0].calls == 3 and tenants[1].calls == 0
    assert src.listed_by_board == {"workday:c0.Jobs": 1}  # c1 is absent, not at 0
    assert [q.query for q in src.query_stats] == ["c0.Jobs"]
    assert src.check_offer("workday:c1.Jobs:R1") is OfferStatus.NOT_ASKED
    assert tenants[1].calls == 0
    assert src.board_statuses[1] == {
        "board": "workday:c1.Jobs", "company": "C1", "status": "skipped", "calls": 0,
        "listed": 0, "fetched": 0, "due_in": 1}


@respx.mock
def test_a_board_may_carry_its_own_frequency():
    daily = AtsBoard(company="Daily", ats="workday", frequency_days=1,
                     slug="daily.wd3.myworkdayjobs.com/daily/Jobs")
    tenant = FakeTenant(daily, [])
    for day in range(3):
        list(_source(daily, today=MONDAY + timedelta(days=day), frequency_days=7).fetch())
    assert tenant.calls == 3 * (1 + len(KEYWORDS))


def test_due_in_days_is_stateless_and_every_run_when_the_frequency_is_one():
    assert [workday.due_in_days(3, 1, MONDAY + timedelta(days=d)) for d in range(3)] == [0, 0, 0]
    week = [workday.due_in_days(3, 7, MONDAY + timedelta(days=d)) for d in range(7)]
    assert sorted(week) == [0, 1, 2, 3, 4, 5, 6] and week.count(0) == 1


def test_posted_days_reads_what_workday_writes():
    assert [workday.posted_days(t) for t in (
        "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago",
        "", None)] == [0, 1, 3, 31, workday.UNKNOWN_AGE, workday.UNKNOWN_AGE]


# ---------------------------------------------------------------------- title filter

def test_the_committed_title_filter_keeps_the_core_and_near_families():
    worth = paged_title_filter(load_settings(Path("config/settings.yaml")))
    assert worth("Ingénieur DevOps (H/F)") and worth("Site Reliability Engineer")
    assert worth("Administrateur systèmes Linux")  # near
    assert not worth("Développeur Java Cloud")     # a developer role wearing our keyword
    assert not worth("Ingénieur commercial Cloud")  # a sales role next to a core term
    assert not worth("Chargé de recrutement") and not worth("Comptable")


def test_committed_settings_search_the_paged_ats_and_cap_workday():
    s = load_settings(Path("config/settings.yaml")).sources
    assert s.ats_search.search_keywords == KEYWORDS
    assert s.ats_search.title_prefilter == ("workday",)  # SmartRecruiters reads every title
    assert (s.workday.max_calls_per_run, s.workday.frequency_days, s.workday.skip_known) == (
        15, 7, True)


# ---------------------------------------------------------------------- SmartRecruiters

SR = AtsBoard(company="Sopra Steria", ats="smartrecruiters", slug="SopraSteria1",
              max_postings=250)
SR_BASE = "https://api.smartrecruiters.com/v1/companies/SopraSteria1/postings"


@respx.mock
def test_smartrecruiters_is_searched_by_keyword_in_france_and_paged():
    titles = ["Ingénieur DevOps", "Chef de projet Cloud", "Développeur Java Cloud"]
    postings = [{"id": str(1000 + i), "name": titles[i % 3],
                 "releasedDate": "2026-11-18T09:00:00.000Z",
                 "location": {"city": "Lyon", "country": "fr", "fullLocation": "Lyon, France"}}
                for i in range(230)]
    asked: list[dict] = []

    def listing(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        asked.append(params)
        off = int(params["offset"])
        return httpx.Response(200, json={"totalFound": len(postings),
                                         "content": postings[off:off + int(params["limit"])]})

    respx.get(SR_BASE).mock(side_effect=listing)
    detail = respx.get(url__regex=SR_BASE + r"/\d+$").mock(side_effect=lambda r: httpx.Response(
        200, json={"name": "Ingénieur DevOps", "postingUrl": "https://x.test/p",
                   "location": {"fullLocation": "Lyon, France"},
                   "jobAd": {"sections": {"jobDescription": {"text": "<p>Kubernetes</p>"}}}}))
    worth = paged_title_filter(load_settings(Path("config/settings.yaml")))

    items = list(_source(SR, title_filter=worth).fetch())

    assert [(p["country"], p["q"], p["limit"], p["offset"]) for p in asked] == [
        ("fr", "devops cloud sre platform", "100", "0"),
        ("fr", "devops cloud sre platform", "100", "100"),
        ("fr", "devops cloud sre platform", "100", "200")]
    # 230 postings listed in 3 calls; one detail call per « Ingénieur DevOps » only.
    assert detail.call_count == len(items) == 77

    # The committed settings keep the title filter for Workday: here every posting is read.
    detail.reset()
    src = AtsBoardSource([SR], requests_per_second=1000.0, sleep=lambda _s: None,
                         keywords=KEYWORDS, title_filter=worth, title_filter_ats=("workday",))
    assert len(list(src.fetch())) == detail.call_count == 230


@respx.mock
def test_smartrecruiters_without_keywords_sends_no_q():
    route = respx.get(SR_BASE).mock(return_value=httpx.Response(
        200, json={"totalFound": 0, "content": []}))
    list(_source(SR, keywords=()).fetch())
    assert "q" not in dict(route.calls[0].request.url.params)
