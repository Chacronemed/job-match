"""How many Workday calls a week, before and after (ADR 0020, amendment 2026-11-21).

A simulation on a fixture: the eleven boards of config/ats_boards.yaml with the number of
French postings each announced on 2026-11-20, every posting generated from a pool of made-up
titles (tests/fixtures/workday_simulation.json). The same fake server answers both policies:

- **before**: the whole French listing every day, capped at 100 postings a board, one
  detail call per posting (what ran until 2026-11-20, when Workday answered);
- **after**: the committed settings: a search per keyword, a detail call only for a title
  worth one and not stored yet, 15 calls a tenant and run at most, one read a week.

The numbers asserted here are the ones docs/diagnostics/2026-11-21-workday-calls.md quotes.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import respx

from job_match.adapters.jobs.ats import BOARD_KEY, AtsBoardSource
from job_match.adapters.jobs.factory import paged_title_filter
from job_match.config.loader import load_ats_boards, load_settings
from job_match.config.schema import AtsBoard, WorkdayConfig

FIXTURE = json.loads(
    (Path(__file__).parent.parent.parent / "fixtures" / "workday_simulation.json")
    .read_text(encoding="utf-8"))
SETTINGS = load_settings(Path("config/settings.yaml"))
FRANCE_ID = "54c5b6971ffb4bf0b116fe7651ec789a"
START = date(2026, 11, 23)


class Tenant:
    """A Workday site holding `count` French postings; it only counts what it is asked."""

    def __init__(self, board: AtsBoard, count: int, titles: list[str]) -> None:
        host, tenant, site = board.slug.split("/", 2)
        base = f"https://{host}/wday/cxs/{tenant}/{site}"
        self.calls = 0
        self.postings = [
            {"title": titles[i % len(titles)], "locationsText": "Paris",
             "postedOn": f"Posted {i % 29 + 1} Days Ago", "externalPath": f"/job/Paris/x_R{i}"}
            for i in range(count)]
        respx.post(base + "/jobs").mock(side_effect=self._jobs)
        respx.get(url__startswith=base + "/job/").mock(side_effect=self._detail)

    def _jobs(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        body = json.loads(request.content)
        if not body["appliedFacets"]:
            return httpx.Response(200, json={"total": 9999, "facets": [
                {"facetParameter": "locationCountry",
                 "values": [{"descriptor": "France", "id": FRANCE_ID}]}]})
        words = body["searchText"].lower().split()
        hits = [p for p in self.postings if all(w in p["title"].lower() for w in words)]
        off = body["offset"]
        return httpx.Response(200, json={"total": len(hits) if off == 0 else 0,
                                         "jobPostings": hits[off:off + body["limit"]]})

    def _detail(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, json={"jobPostingInfo": {
            "title": "x", "location": "Paris", "country": {"descriptor": "France"},
            "jobDescription": "<p>x</p>", "externalUrl": "https://example.test/x"}})


def _boards() -> list[AtsBoard]:
    return [AtsBoard(company=t["company"], ats="workday", slug=t["slug"])
            for t in FIXTURE["tenants"]]


def _week(policy: dict, known: set[str], start: date) -> dict[str, int]:
    """Calls per company over seven daily runs starting on `start`. `known` plays the
    database: what a run read is stored for the next ones."""
    boards = _boards()
    tenants = {b.company: Tenant(b, t["french_postings"], FIXTURE["titles"])
               for b, t in zip(boards, FIXTURE["tenants"], strict=True)}
    for day in range(7):
        src = AtsBoardSource(boards, requests_per_second=1000.0, sleep=lambda _s: None,
                             today=start + timedelta(days=day), **policy)
        src.set_known_ids(known)
        for item in src.fetch():
            known.add(f"{item[BOARD_KEY]}:{item['id']}")
    return {name: tenant.calls for name, tenant in tenants.items()}


def test_the_fixture_is_the_eleven_configured_workday_boards():
    configured = {b.slug for b in load_ats_boards(Path("config/ats_boards.yaml"))
                  if b.ats == "workday"}
    assert {t["slug"] for t in FIXTURE["tenants"]} == configured and len(configured) == 11


@respx.mock
def test_workday_calls_a_week_before_and_after():
    quiet = {"request_delay_seconds": 0, "backoff_seconds": 0}
    before = _week({"workday": WorkdayConfig(**quiet, max_calls_per_run=0, frequency_days=1,
                                             skip_known=False)}, set(), START)
    respx.reset()
    cfg = SETTINGS.sources.workday
    after_policy = {
        "workday": WorkdayConfig(**quiet, max_calls_per_run=cfg.max_calls_per_run,
                                 frequency_days=cfg.frequency_days, skip_known=cfg.skip_known),
        "keywords": SETTINGS.sources.ats_search.search_keywords,
        "title_filter": paged_title_filter(SETTINGS),
    }
    known: set[str] = set()
    week1 = _week(after_policy, known, START)
    respx.reset()
    week2 = _week(after_policy, known, START + timedelta(days=7))

    # Before: 1 facets call + the listing pages + one detail per posting, every day.
    assert before["Thales"] == 7 * (1 + 5 + 100)
    assert before["Kyndryl"] == 7 * (1 + 1 + 9)
    assert sum(before.values()) == 5733
    # After: one read a week, 1 facets + 4 searches + at most 10 details.
    assert max(week1.values()) == 15 and week1["Kyndryl"] == 1 + 4 + 4
    assert sum(week1.values()) == 145
    # The week after, what is stored is not read again: the cap goes to other postings on
    # the big boards, and a small board costs its five search calls only.
    assert week2["Kyndryl"] == 5 and sum(week2.values()) == 125
    assert sum(week1.values()) / sum(before.values()) < 0.03  # 97 % fewer calls
