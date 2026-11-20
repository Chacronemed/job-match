"""Company career boards through their ATS's public JSON endpoint (ADR 0020).

Greenhouse, Lever and Ashby expose each customer's job board as an unauthenticated JSON
document meant for exactly this: embedding the board elsewhere. One GET per company returns
the whole board with every description inlined, so a run costs one call per configured
board, nothing per keyword, and the postings come straight from the employer (no agency
repost, no board lag).

    greenhouse  GET https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true
                → {"jobs": [{id, title, absolute_url, location.name, content (HTML),
                             first_published, updated_at, departments[]}]}
    lever       GET https://api.lever.co/v0/postings/<slug>
                → [{id, text, hostedUrl, categories{location, allLocations[], commitment,
                    team}, workplaceType, descriptionPlain, lists[{text, content}],
                    additionalPlain, createdAt (epoch ms), country}]
    ashby       GET https://api.ashbyhq.com/posting-api/job-board/<slug>
                → {"jobs": [{id, title, jobUrl, location, address.postalAddress,
                             secondaryLocations[], descriptionPlain, employmentType,
                             workplaceType, isRemote, publishedAt, isListed}]}

The big groups' two ATS (ADR 0020 amendment, M28) list without descriptions and page
their listing, so they cost more: a filtered, capped listing, then one detail call per
posting kept. Both are asked for French postings only, so a 2 000-posting worldwide board
costs what its French part costs:

    workday          POST https://<host>/wday/cxs/<tenant>/<site>/jobs
                     {"appliedFacets": {<country facet>: [<France id>]}, "limit": 20,
                      "offset": n, "searchText": ""}
                     → {total, facets[], jobPostings[{title, externalPath, locationsText}]}
                     GET  https://<host>/wday/cxs/<tenant>/<site><externalPath>
                     → {jobPostingInfo{title, jobDescription (HTML), location,
                        additionalLocations[], country.descriptor, startDate, remoteType,
                        externalUrl}}
    smartrecruiters  GET https://api.smartrecruiters.com/v1/companies/<id>/postings
                         ?country=fr&limit=100&offset=n
                     → {totalFound, content[{id, name, releasedDate, location{...}}]}
                     GET https://api.smartrecruiters.com/v1/companies/<id>/postings/<pid>
                     → {name, postingUrl, location{fullLocation, remote, hybrid},
                        typeOfEmployment.id, releasedDate, jobAd.sections{...}.text}

The France facet is found in the first listing's facets (a facet whose parameter names a
country, value "France"), never hard-coded: its id is the same on every tenant seen so far,
the parameter name is not. A Workday board without a country facet is skipped (it cannot be
filtered); one whose country facet has no France value has no French posting.
A listing stops at `max_postings` (100 by default, per board): the newest first.

One more board type is not JSON: a Talentsoft career site publishes an RSS feed of its 20
newest offers, descriptions included (talentsoft.py, ADR 0029). One GET per board, no
detail call; the listing is never complete, so a missing id is UNKNOWN, never CLOSED.

    talentsoft       GET https://<host>/handlers/offerRss.ashx?LCID=1036   (slug = <host>)

The Greenhouse / Lever / Ashby shapes follow the provider modules of career-ops
(https://github.com/career-ops-hq/career-ops, `providers/greenhouse.mjs`, `lever.mjs`,
`ashby.mjs`; MIT License, Copyright (c) 2026 Santiago Fernández de Valderrama), read for
their field mapping and re-implemented here in Python: `absolute_url` / `hostedUrl` /
`jobUrl` as the posting URL, `first_published` / `createdAt` / `publishedAt` as the posting
date, Lever's `lists` folded into the description, Ashby's `isRemote` as a fallback for
`workplaceType`. No code is copied. The Workday and SmartRecruiters mappings were written
from the live payloads (2026-11-05).

Terms: public JSON only, no HTML page is fetched, one request per second per host (Lever's
robots.txt asks for `Crawl-delay: 1`), the project's User-Agent. A board that answers 404
(the company left the ATS, or the slug changed) or any network error is logged and skipped;
the other boards still run, and a run with every board down yields nothing instead of
failing. A posting whose detail call fails is skipped. The gates, dedup and scoring
downstream are the same as for any other source.

Workday is paced apart and called sparingly (`sources.ats.workday` in settings.yaml,
`WorkdayConfig`, workday.py): every tenant sits behind the same edge, so all of them share
one queue, read one tenant after the other, with `request_delay_seconds` between two calls
whatever the tenant. Since 2026-11-16 that edge answers the project's client with an HTML
« Security Check » page (HTTP 429, no `Retry-After`): an anti-robot protection, never
worked around. The source only makes fewer calls (amendment 2026-11-21):

- with `sources.ats.search_keywords`, a board is searched, not listed: Workday one
  `searchText` call per keyword with the France facet (one page of 20), SmartRecruiters one
  `q` with every keyword and `country=fr`;
- a detail call only for a posting worth one: its title passes the title filter and, on
  Workday, it is not stored yet (`set_known_ids`), the freshest first;
- `max_calls_per_run` requests per Workday tenant and run at most, retries and closure
  probes included; a tenant read every `frequency_days` days, spread over the days;
- a security check stops the tenant at once for the run, without a retry; a plain 429, a
  5xx or a timeout is still retried here, not in `HttpClient` (`Retry-After` when there is
  one, else a backoff doubling from `backoff_seconds`).

`board_statuses` says what happened to each Workday board (ok / capped / skipped / blocked /
error) for the run summary; a board that was skipped or blocked answers NOT_ASKED to the
closure check: nothing is closed, and it is not an error.

`source_job_id` is `<ats>:<board id>:<id>` so `check_offer` can find the board again: an
id missing from a complete listing that answered 200 is CLOSED, a board that could not be
read is UNKNOWN. A listing cut at `max_postings` proves nothing for an id it did not list,
so that one posting is asked directly: SmartRecruiters' detail call (404 = CLOSED), a
Workday search on the requisition id (an answer without it = CLOSED).
The board id is the slug, except Workday's `<host>/<tenant>/<site>`, which becomes
`<tenant>.<site>` (the tracking key allows no `/`).
"""
import logging
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import httpx

from job_match.adapters.http import HttpClient, retry_after_seconds
from job_match.adapters.jobs import talentsoft
from job_match.adapters.jobs import workday as wd
from job_match.adapters.jobs.base import OfferStatus, QueryStat, RawItem, RequestStats
from job_match.config.schema import AtsBoard, WorkdayConfig
from job_match.domain.models import Job, WorkplaceType
from job_match.normalization.contract import parse_contract_type
from job_match.normalization.text import html_to_text

logger = logging.getLogger(__name__)

SOURCE_NAME = "ats"
BOARD_KEY = "_jm_board"  # adapter-private: "<ats>:<board id>" the item came from
COMPANY_KEY = "_jm_company"  # the configured display name, not the source's
DETAIL_KEY = "_jm_detail"  # Workday / SmartRecruiters: the posting's detail payload

ENDPOINTS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    "workday": "https://{host}/wday/cxs/{tenant}/{site}/jobs",
    "talentsoft": talentsoft.FEED_URL,
}
PAGED_ATS = ("workday", "smartrecruiters")
DEFAULT_MAX_POSTINGS = 100  # per paged board and run: the newest French postings
WORKDAY_PAGE = wd.PAGE
SMARTRECRUITERS_PAGE = 100
SMARTRECRUITERS_COUNTRY = "fr"
WORKDAY_DOMAIN = wd.DOMAIN

_WORKPLACE: dict[str, WorkplaceType] = {
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
    "onsite": WorkplaceType.ONSITE,
    "on-site": WorkplaceType.ONSITE,
    "on site": WorkplaceType.ONSITE,
    "unspecified": WorkplaceType.UNKNOWN,
}

# Ashby's `employmentType` values that name a contract type; the rest ("FullTime",
# "PartTime") are working time, not a contract, and fall through to the text parser.
_ASHBY_EMPLOYMENT: dict[str, str] = {"intern": "internship", "temporary": "temporary"}


def board_id(board: AtsBoard) -> str:
    """The board's part of `source_job_id`: the slug, `<tenant>.<site>` for Workday."""
    if board.ats == "workday":
        _host, tenant, site = board.slug.split("/", 2)
        return f"{tenant}.{site}"
    return board.slug


def board_url(board: AtsBoard) -> str:
    if board.ats == "workday":
        host, tenant, site = board.slug.split("/", 2)
        return ENDPOINTS["workday"].format(host=host, tenant=tenant, site=site)
    if board.ats == "talentsoft":
        return ENDPOINTS["talentsoft"].format(host=board.slug)
    return ENDPOINTS[board.ats].format(slug=board.slug)


class _Listing(NamedTuple):
    jobs: list[dict]
    available: int | None  # what the board says it has (French only for the paged ATS)
    complete: bool         # every posting listed: a missing id means closed


@dataclass
class _Tenant:
    """One Workday board this run: what the run summary says of it."""

    company: str
    board: str             # "<tenant>.<site>"
    due_in: int = 0        # days until its next read; 0 = today
    status: str = wd.OK
    calls: int = 0         # requests sent to the tenant, retries and closure probes included
    listed: int = 0        # postings its searches returned
    fetched: int = 0       # postings read in full (one detail call each)

    def as_dict(self) -> dict:
        return {"board": f"workday:{self.board}", "company": self.company,
                "status": self.status, "calls": self.calls, "listed": self.listed,
                "fetched": self.fetched, "due_in": self.due_in}


class AtsBoardSource:
    name = SOURCE_NAME
    reports_by_company = True  # the run summary counts fetched / eligible per board company

    def __init__(
        self,
        boards: list[AtsBoard],
        http: HttpClient | None = None,
        max_results: int | None = None,
        requests_per_second: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        workday: WorkdayConfig | None = None,
        keywords: Sequence[str] = (),
        title_filter: Callable[[str], bool] | None = None,
        today: date | None = None,
    ) -> None:
        """`keywords`: what the paged ATS are searched for instead of listing everything
        (Workday one call per keyword, SmartRecruiters one `q`); empty lists the whole
        French board. `title_filter`: a paged posting whose title it refuses gets no detail
        call. `today` places each Workday tenant in its frequency (UTC date by default)."""
        self._boards = list(boards)
        self._http = http or HttpClient()
        # Workday retries are decided here (Retry-After, longer backoff, per-tenant
        # give-up), so its client must not retry underneath.
        self._workday = workday or WorkdayConfig()
        self._workday_http = HttpClient(max_retries=0)
        self._workday_failures: dict[str, int] = {}  # host → failed calls in a row
        self._workday_stopped: dict[str, str] = {}   # host → why it is left alone this run
        self._keywords = tuple(k.strip() for k in keywords if k and k.strip())
        self._title_filter = title_filter
        self._known: frozenset[str] = frozenset()  # source_job_ids already stored
        self._listed: dict[str, int] = {}  # "<ats>:<board id>" → postings listed this run
        day = today or datetime.now(UTC).date()
        self._tenants: dict[str, _Tenant] = {}  # Workday host → its state this run
        for index, board in enumerate(b for b in self._boards if b.ats == "workday"):
            every = board.frequency_days or self._workday.frequency_days
            self._tenants.setdefault(board.slug.split("/", 1)[0], _Tenant(
                board.company, board_id(board), wd.due_in_days(index, every, day)))
        self._max_results = max_results
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}  # host → monotonic time of its last call
        self._api_calls = 0
        self._attempted = 0
        self._failed = 0
        self._query_stats: list[QueryStat] = []
        # "<ats>:<board id>" → (ids listed, listing complete), or None when unreadable.
        self._board_ids: dict[str, tuple[set[str], bool] | None] = {}

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

    @property
    def query_stats(self) -> tuple[QueryStat, ...]:
        """One entry per board, in execution order: query=board id, area=ATS name."""
        return tuple(self._query_stats)

    @property
    def request_stats(self) -> RequestStats:
        """Requests made and failed this run, every board and detail call included (ADR
        0026). A 404 is an answer (the board or the posting is gone), not a failure."""
        return RequestStats(self._attempted, self._failed)

    @property
    def listed_by_board(self) -> dict[str, int]:
        """"<ats>:<board id>" → postings the board listed this run, before any filter: what
        the outage guard compares from one run to the next. A board that was not read
        (unreachable, not its day, blocked) is absent, not 0."""
        return dict(self._listed)

    @property
    def board_statuses(self) -> list[dict]:
        """One entry per Workday board, in config order: `{board, company, status, calls,
        listed, fetched, due_in}`, status one of ok / capped / skipped / blocked / error."""
        return [tenant.as_dict() for tenant in self._tenants.values()]

    def set_known_ids(self, source_job_ids: Iterable[str]) -> None:
        """The `source_job_id`s already stored: a Workday posting among them gets no detail
        call (its listing still says it is open). Called by the pipeline before `fetch`."""
        self._known = frozenset(source_job_ids)

    # ------------------------------------------------------------------ HTTP

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        interval = self._min_interval
        if host.endswith(WORKDAY_DOMAIN):  # one queue for every tenant
            host, interval = WORKDAY_DOMAIN, self._workday.request_delay_seconds
        last = self._last_request.get(host)
        if last is not None:
            wait = interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def _call(self, method: str, url: str, label: str, *,
              decode: Callable[[httpx.Response], Any] | None = None,
              **kwargs: Any) -> tuple[int | None, Any]:
        """(HTTP status, decoded body): (None, None) on a network error, (404, None) for a
        404, (status, None) for any other error status. Logged, never raised. `decode`
        reads a body that is not JSON (Talentsoft's feed)."""
        if (urlsplit(url).hostname or "").endswith(WORKDAY_DOMAIN):
            return self._call_workday(method, url, label, **kwargs)
        self._attempted += 1
        try:
            self._throttle(url)
            headers = {"Accept": "application/json" if decode is None
                       else "application/rss+xml, application/xml;q=0.9"}
            if method == "POST":
                resp = self._http.post(url, headers=headers, **kwargs)
            else:
                resp = self._http.get(url, headers=headers, **kwargs)
            self._api_calls += 1
            if resp.status_code == 404:
                logger.warning("%s: %s answers 404 (gone?)", self.name, label)
                return 404, None
            resp.raise_for_status()
            return resp.status_code, (resp.json() if decode is None else decode(resp))
        except Exception as exc:
            self._failed += 1
            logger.warning("%s: %s unreachable: %s", self.name, label, type(exc).__name__)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return status, None

    def _call_workday(self, method: str, url: str, label: str,
                      **kwargs: Any) -> tuple[int | None, Any]:
        """`_call` for a Workday tenant: paced on the shared queue, every request counted
        against the tenant's cap, a security check stopping it at once (no retry), a plain
        429 / 5xx / timeout retried with `Retry-After` or the configured backoff. A stopped
        tenant answers (None, None) without a request."""
        cfg = self._workday
        host = urlsplit(url).hostname or ""
        tenant = self._tenants.setdefault(host, _Tenant(host, host))
        if host in self._workday_stopped:
            return None, None
        if self._workday_capped(host, tenant):
            return None, None
        self._attempted += 1
        headers = {"Accept": "application/json"}
        status: int | None = None
        reason = "no answer"
        give_up: str | None = None
        for attempt in range(cfg.max_retries + 1):
            if attempt and self._workday_capped(host, tenant):
                break
            self._throttle(url)
            tenant.calls += 1
            asked: float | None = None
            try:
                if method == "POST":
                    resp = self._workday_http.post(url, headers=headers, **kwargs)
                else:
                    resp = self._workday_http.get(url, headers=headers, **kwargs)
            except httpx.HTTPStatusError as exc:  # 429 / 5xx: HttpClient(max_retries=0) raises
                status = exc.response.status_code
                reason = wd.failure_reason(exc.response)
                if wd.is_security_check(exc.response):
                    return self._workday_blocked(host, tenant, label, status, reason)
                asked = retry_after_seconds(exc.response)
            except Exception as exc:  # timeout, connection reset, DNS
                status, reason = None, type(exc).__name__
            else:
                self._api_calls += 1
                if wd.is_security_check(resp):  # the same page served with a 403
                    return self._workday_blocked(host, tenant, label, resp.status_code,
                                                 wd.failure_reason(resp))
                self._workday_failures[host] = 0
                if resp.status_code == 404:
                    logger.warning("%s: %s answers 404 (gone?)", self.name, label)
                    return 404, None
                try:
                    resp.raise_for_status()  # 422: wrong site name, not worth a retry
                    return resp.status_code, resp.json()
                except Exception as exc:
                    self._failed += 1
                    logger.warning("%s: %s unreachable: %s", self.name, label,
                                   type(exc).__name__)
                    return resp.status_code, None
            if asked is not None and asked > cfg.retry_after_max_seconds:
                give_up = f"Retry-After {asked:.0f}s is beyond {cfg.retry_after_max_seconds:.0f}s"
                break
            if attempt == cfg.max_retries:
                break
            wait = asked if asked is not None else min(
                cfg.backoff_seconds * 2**attempt, cfg.backoff_max_seconds)
            logger.warning("%s: %s: %s on attempt %d/%d, waiting %.1fs%s",
                           self.name, label, reason, attempt + 1, cfg.max_retries + 1, wait,
                           " (Retry-After)" if asked is not None else "")
            self._sleep(wait)
        self._failed += 1
        failures = self._workday_failures.get(host, 0) + 1
        self._workday_failures[host] = failures
        logger.warning("%s: %s unreachable: %s", self.name, label, reason)
        if give_up is None and failures >= cfg.max_consecutive_failures:
            give_up = f"{failures} calls failed in a row (last: {reason})"
        if give_up is not None:
            self._workday_stop(host, tenant, wd.ERROR, give_up)
        return status, None

    def _workday_stop(self, host: str, tenant: _Tenant, status: str, why: str) -> None:
        """No further call to this tenant this run. A blocked tenant stays blocked."""
        if host in self._workday_stopped:
            return
        self._workday_stopped[host] = why
        if tenant.status != wd.BLOCKED:
            tenant.status = status
        logger.warning("%s: workday tenant %s left alone for the rest of this run: %s",
                       self.name, host, why)

    def _workday_capped(self, host: str, tenant: _Tenant) -> bool:
        """True (and the tenant stopped) once its calls reach the cap; 0 = no cap."""
        cap = self._workday.max_calls_per_run
        if not cap or tenant.calls < cap:
            return False
        self._workday_stop(host, tenant, wd.CAPPED, f"call cap reached ({cap} calls)")
        return True

    def _workday_blocked(self, host: str, tenant: _Tenant, label: str, status: int,
                         reason: str) -> tuple[int | None, Any]:
        """The edge served its security check: an anti-robot answer. One warning, the
        tenant stopped at once, no retry (insisting is what the protection is against)."""
        self._failed += 1
        logger.warning("%s: %s refused: %s", self.name, label, reason)
        self._workday_stop(host, tenant, wd.BLOCKED,
                           f"{reason}: anti-robot protection, not retried")
        return status, None

    def _workday_is_stopped(self, board: AtsBoard) -> bool:
        return board.ats == "workday" and board.slug.split("/", 1)[0] in self._workday_stopped

    def _tenant(self, board: AtsBoard) -> _Tenant | None:
        if board.ats != "workday":
            return None
        return self._tenants.get(board.slug.split("/", 1)[0])

    def _json(self, method: str, url: str, label: str, **kwargs: Any) -> Any:
        """The decoded body, or None when the call failed (logged, never raised)."""
        return self._call(method, url, label, **kwargs)[1]

    # ------------------------------------------------------------------ listings

    def _list_board(self, board: AtsBoard) -> _Listing | None:
        if board.ats == "workday":
            return self._list_workday(board)
        if board.ats == "smartrecruiters":
            return self._list_smartrecruiters(board)
        if board.ats == "talentsoft":
            return self._list_talentsoft(board)
        label = f"{board.ats}/{board.slug}"
        body = self._json("GET", board_url(board), label)
        if body is None:
            return None
        jobs = body if isinstance(body, list) else (body or {}).get("jobs")
        if not isinstance(jobs, list):
            logger.warning("%s: %s: unexpected payload shape, skipped", self.name, label)
            return None
        jobs = [j for j in jobs if isinstance(j, dict) and j.get("id") is not None]
        return _Listing(jobs, len(jobs), True)

    def _cap(self, board: AtsBoard) -> int:
        cap = board.max_postings or DEFAULT_MAX_POSTINGS
        return min(cap, self._max_results) if self._max_results is not None else cap

    def _list_workday(self, board: AtsBoard) -> _Listing | None:
        label = f"workday/{board_id(board)}"
        url = board_url(board)
        query = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        first = self._json("POST", url, label, json=query)
        if not isinstance(first, dict):
            return None
        facet = wd.france_facet(first.get("facets"))
        if facet is None:
            logger.warning("%s: %s has no country facet, skipped (cannot keep France only)",
                           self.name, label)
            return None
        param, values = facet
        if not values:
            return _Listing([], 0, True)  # a facet without a French value: no French posting
        if self._keywords:
            return self._search_workday(board, {param: values})
        cap = self._cap(board)
        jobs: list[dict] = []
        total: int | None = None
        offset = 0
        while len(jobs) < cap:
            body = self._json("POST", url, label, json={
                "appliedFacets": {param: values}, "limit": WORKDAY_PAGE,
                "offset": offset, "searchText": "",
            })
            if not isinstance(body, dict):
                if not jobs:
                    return None
                break  # keep what the earlier pages gave; the listing is not complete
            if total is None:  # Workday only counts on the first page
                total = body.get("total") if isinstance(body.get("total"), int) else None
            page = [p for p in body.get("jobPostings") or []
                    if isinstance(p, dict) and p.get("externalPath")]
            for posting in page:
                posting["id"] = wd.posting_id(str(posting["externalPath"]))
            jobs.extend(page)
            offset += WORKDAY_PAGE
            if not page or (total is not None and offset >= total):
                break
        jobs = jobs[:cap]
        complete = total is not None and len(jobs) >= total
        return _Listing(jobs, total, complete)

    def _search_workday(self, board: AtsBoard, france: dict[str, list[str]]) -> _Listing | None:
        """One search per keyword, France only, one page each: Workday reads several words
        as AND, so the keywords cannot share a call. The postings come back by relevance;
        they are handed over the freshest first, since the detail calls are counted."""
        label = f"workday/{board_id(board)} search"
        url = board_url(board)
        found: dict[str, dict] = {}
        answered = False
        for keyword in self._keywords:
            body = self._json("POST", url, label, json={
                "appliedFacets": france, "limit": WORKDAY_PAGE, "offset": 0,
                "searchText": keyword,
            })
            if not isinstance(body, dict):
                if self._workday_is_stopped(board):
                    break
                continue
            answered = True
            for posting in body.get("jobPostings") or []:
                if isinstance(posting, dict) and posting.get("externalPath"):
                    posting["id"] = wd.posting_id(str(posting["externalPath"]))
                    found.setdefault(posting["id"], posting)
        if not answered:
            return None
        jobs = sorted(found.values(), key=lambda p: wd.posted_days(p.get("postedOn")))
        return _Listing(jobs[:self._cap(board)], len(jobs), False)

    def _list_smartrecruiters(self, board: AtsBoard) -> _Listing | None:
        label = f"smartrecruiters/{board.slug}"
        url = board_url(board)
        cap = self._cap(board)
        jobs: list[dict] = []
        total: int | None = None
        offset = 0
        while len(jobs) < cap:
            params: dict[str, Any] = {
                "country": SMARTRECRUITERS_COUNTRY, "limit": SMARTRECRUITERS_PAGE,
                "offset": offset,
            }
            if self._keywords:  # full text, several words read as OR (measured 2026-11-20)
                params["q"] = " ".join(self._keywords)
            body = self._json("GET", url, label, params=params)
            if not isinstance(body, dict) or not isinstance(body.get("content"), list):
                if not jobs:
                    if body is not None:
                        logger.warning("%s: %s: unexpected payload shape, skipped",
                                       self.name, label)
                    return None
                break
            if isinstance(body.get("totalFound"), int):
                total = body["totalFound"]
            page = [p for p in body["content"] if isinstance(p, dict) and p.get("id")]
            jobs.extend(page)
            offset += SMARTRECRUITERS_PAGE
            if not page or (total is not None and offset >= total):
                break
        jobs = jobs[:cap]
        complete = total is not None and len(jobs) >= total
        return _Listing(jobs, total, complete)

    def _list_talentsoft(self, board: AtsBoard) -> _Listing | None:
        """The feed's offers. Never complete: it only shows the newest ones."""
        _status, jobs = self._call(
            "GET", board_url(board), f"talentsoft/{board.slug}",
            decode=lambda resp: talentsoft.parse_feed(resp.content))
        if jobs is None:
            return None
        return _Listing(jobs, len(jobs), False)

    def _detail(self, board: AtsBoard, item: dict) -> dict | None:
        """The detail payload of one Workday / SmartRecruiters posting, or None."""
        if board.ats == "workday":
            host, tenant, site = board.slug.split("/", 2)
            url = f"https://{host}/wday/cxs/{tenant}/{site}{item['externalPath']}"
            body = self._json("GET", url, f"workday/{board_id(board)} posting")
            info = body.get("jobPostingInfo") if isinstance(body, dict) else None
            return info if isinstance(info, dict) else None
        url = f"{board_url(board)}/{item['id']}"
        body = self._json("GET", url, f"smartrecruiters/{board.slug} posting")
        return body if isinstance(body, dict) else None

    # ------------------------------------------------------------------ fetching

    def fetch(self, since: datetime | None = None) -> Iterator[RawItem]:
        if not self._boards:
            logger.warning("%s: no board configured (config/ats_boards.yaml)", self.name)
            return
        unreachable = 0
        for board in self._boards:
            key = f"{board.ats}:{board_id(board)}"
            tenant = self._tenant(board)
            if tenant is not None and tenant.due_in > 0:
                tenant.status = wd.SKIPPED  # not its day: no call, no stat, no error
                logger.info("%s: workday/%s not read today (next read in %d day(s))",
                            self.name, board_id(board), tenant.due_in)
                continue
            listing = self._list_board(board)
            if listing is None:
                unreachable += 1
                self._board_ids[key] = None
                if tenant is not None and tenant.status == wd.OK:
                    tenant.status = wd.ERROR
                if tenant is None or tenant.status != wd.BLOCKED:
                    # A refused tenant is reported by its status, not as a board at 0.
                    self._query_stats.append(
                        QueryStat(board_id(board), board.ats, 0, None, self.name))
                continue
            self._board_ids[key] = ({str(j["id"]) for j in listing.jobs}, listing.complete)
            self._listed[key] = len(listing.jobs)
            fetched = skipped = filtered = known = 0
            for item in listing.jobs:
                if board.ats == "ashby" and item.get("isListed") is False:
                    continue
                if since is not None:
                    published = _published_at(board.ats, item)
                    if published is not None and published < since:
                        continue
                if board.ats in PAGED_ATS:
                    # A detail call only for a posting worth one: its title first, then
                    # (Workday, whose calls are counted) whether it is stored already.
                    title = str(item.get("title") or item.get("name") or "")
                    if self._title_filter is not None and not self._title_filter(title):
                        filtered += 1
                        continue
                    if (board.ats == "workday" and self._workday.skip_known
                            and f"{key}:{item['id']}" in self._known):
                        known += 1
                        continue
                    if self._workday_is_stopped(board):
                        skipped += 1  # left alone for this run: no further call
                        continue
                    detail = self._detail(board, item)
                    if detail is None:
                        skipped += 1
                        continue
                    item[DETAIL_KEY] = detail
                item[BOARD_KEY] = key
                item[COMPANY_KEY] = board.company
                yield item
                fetched += 1
                if self._max_results is not None and fetched >= self._max_results:
                    break
            if tenant is not None:
                tenant.listed, tenant.fetched = len(listing.jobs), fetched
            self._query_stats.append(
                QueryStat(board_id(board), board.ats, fetched, listing.available, self.name)
            )
            logger.info("%s: %s/%s fetched=%d available=%s%s%s%s",
                        self.name, board.ats, board_id(board), fetched, listing.available,
                        f" title_filtered={filtered}" if filtered else "",
                        f" already_stored={known}" if known else "",
                        f" detail_failed={skipped}" if skipped else "")
        if unreachable:
            logger.warning("%s: %d/%d boards skipped as unreachable",
                           self.name, unreachable, len(self._boards))

    # ------------------------------------------------------------------ mapping

    def to_job(self, raw: RawItem) -> Job:
        ats, bid = str(raw[BOARD_KEY]).split(":", 1)
        company = str(raw.get(COMPANY_KEY) or raw.get("company_name") or bid)
        mapper = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby,
                  "workday": _workday, "smartrecruiters": _smartrecruiters,
                  "talentsoft": _talentsoft}[ats]
        title, url, location, workplace, contract_hint, description = mapper(raw)
        return Job(
            source=self.name,
            source_job_id=f"{ats}:{bid}:{raw['id']}",
            title=title,
            company=company,
            location=location,
            workplace_type=workplace,
            contract_type=parse_contract_type(contract_hint, title, description),
            description=description,
            url=url,
            published_at=_published_at(ats, raw),
            collected_at=datetime.now(UTC),
            search_query=bid,
        )

    # ------------------------------------------------------------------ closure

    def check_offer(self, source_job_id: str) -> OfferStatus:
        """Still listed on its board? One board read per run, shared by every offer of it."""
        try:
            ats, bid, job_id = source_job_id.split(":", 2)
        except ValueError:
            return OfferStatus.UNKNOWN
        key = f"{ats}:{bid}"
        board = next((b for b in self._boards if f"{b.ats}:{board_id(b)}" == key), None)
        tenant = self._tenant(board) if board is not None else None
        if tenant is not None and (
                tenant.due_in > 0 or tenant.status in (wd.SKIPPED, wd.BLOCKED)):
            return OfferStatus.NOT_ASKED  # not its day, or refused today: nothing to learn
        if key not in self._board_ids:
            if board is None:
                return OfferStatus.UNKNOWN  # no longer configured: nothing to ask
            listing = self._list_board(board)
            self._board_ids[key] = (
                None if listing is None
                else ({str(j["id"]) for j in listing.jobs}, listing.complete)
            )
        seen = self._board_ids[key]
        if seen is None:
            return OfferStatus.UNKNOWN
        ids, complete = seen
        if job_id in ids:
            return OfferStatus.OPEN
        if complete:
            return OfferStatus.CLOSED
        status = self._probe(board, job_id)
        if (status is OfferStatus.UNKNOWN and tenant is not None
                and tenant.status in (wd.CAPPED, wd.BLOCKED)):
            return OfferStatus.NOT_ASKED  # the cap or the security check, not an error
        return status

    def _probe(self, board: AtsBoard, job_id: str) -> OfferStatus:
        """A capped listing did not list the id: ask the board about that one posting.

        SmartRecruiters: its detail call, 404 (or `active: false`) is CLOSED. Workday: a
        search on the requisition id over the whole board (no facet); an answer without
        that id is CLOSED. Any failed call is UNKNOWN."""
        if board.ats == "smartrecruiters":
            status, body = self._call("GET", f"{board_url(board)}/{job_id}",
                                      f"smartrecruiters/{board.slug} posting")
            if status == 404:
                return OfferStatus.CLOSED
            if not isinstance(body, dict):
                return OfferStatus.UNKNOWN
            return OfferStatus.CLOSED if body.get("active") is False else OfferStatus.OPEN
        if board.ats == "workday":
            body = self._json("POST", board_url(board), f"workday/{board_id(board)} search",
                              json={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": 0,
                                    "searchText": job_id})
            if not isinstance(body, dict) or not isinstance(body.get("jobPostings"), list):
                return OfferStatus.UNKNOWN
            found = any(isinstance(p, dict) and p.get("externalPath")
                        and wd.posting_id(str(p["externalPath"])) == job_id
                        for p in body["jobPostings"])
            return OfferStatus.OPEN if found else OfferStatus.CLOSED
        return OfferStatus.UNKNOWN


# ---------------------------------------------------------------------- per-ATS mapping
# Each returns (title, url, location, workplace_type, contract_hint, description).

_Mapped = tuple[str, str, str, WorkplaceType, str | None, str]


def _greenhouse(raw: dict) -> _Mapped:
    location = str((raw.get("location") or {}).get("name") or "")
    return (
        str(raw.get("title") or ""),
        str(raw.get("absolute_url") or ""),
        location,
        WorkplaceType.UNKNOWN,
        None,
        html_to_text(raw.get("content")),
    )


def _lever(raw: dict) -> _Mapped:
    cats = raw.get("categories") or {}
    places = [str(cats.get("location") or "")] + [
        str(p) for p in (cats.get("allLocations") or []) if p
    ]
    location = ", ".join(_dedupe(places))
    parts = [str(raw.get("descriptionPlain") or raw.get("description") or "")]
    for block in raw.get("lists") or []:
        if isinstance(block, dict):
            parts.append(str(block.get("text") or ""))
            parts.append(html_to_text(block.get("content")))
    parts.append(str(raw.get("additionalPlain") or ""))
    return (
        str(raw.get("text") or ""),
        str(raw.get("hostedUrl") or ""),
        location,
        _workplace(raw.get("workplaceType")),
        str(cats.get("commitment") or "") or None,
        "\n".join(p for p in parts if p).strip(),
    )


def _ashby(raw: dict) -> _Mapped:
    address = ((raw.get("address") or {}).get("postalAddress") or {})
    places = [str(raw.get("location") or "")]
    # The structured address repeats what `location` usually says ("Paris, France");
    # it is only added when it brings a place the free text does not name.
    places += [str(p) for p in (address.get("addressLocality"), address.get("addressCountry"))
               if p and str(p).lower() not in places[0].lower()]
    for extra in raw.get("secondaryLocations") or []:
        if isinstance(extra, dict) and extra.get("location"):
            places.append(str(extra["location"]))
    workplace = _workplace(raw.get("workplaceType"))
    if workplace is WorkplaceType.UNKNOWN and raw.get("isRemote") is True:
        workplace = WorkplaceType.REMOTE
    return (
        str(raw.get("title") or ""),
        str(raw.get("jobUrl") or ""),
        ", ".join(_dedupe(places)),
        workplace,
        _ASHBY_EMPLOYMENT.get(str(raw.get("employmentType") or "").lower()),
        str(raw.get("descriptionPlain") or html_to_text(raw.get("descriptionHtml"))),
    )


def _workday(raw: dict) -> _Mapped:
    info = raw.get(DETAIL_KEY) or {}
    places = [str(info.get("location") or raw.get("locationsText") or "")]
    places += [str(p) for p in info.get("additionalLocations") or [] if p]
    country = str((info.get("country") or {}).get("descriptor") or "")
    # The location gate reads the place text: "Brest" alone says nothing of the country.
    if country and all(country.lower() not in p.lower() for p in places):
        places.append(country)
    return (
        str(info.get("title") or raw.get("title") or ""),
        str(info.get("externalUrl") or ""),
        ", ".join(_dedupe(places)),
        _workplace(info.get("remoteType")),
        None,  # `timeType` ("Full time") is working time, not a contract
        html_to_text(info.get("jobDescription")),
    )


def _smartrecruiters(raw: dict) -> _Mapped:
    detail = raw.get(DETAIL_KEY) or {}
    loc = detail.get("location") or raw.get("location") or {}
    location = str(loc.get("fullLocation") or ", ".join(
        str(p) for p in (loc.get("city"), loc.get("country")) if p))
    if loc.get("remote") is True:
        workplace = WorkplaceType.REMOTE
    elif loc.get("hybrid") is True:
        workplace = WorkplaceType.HYBRID
    else:
        workplace = WorkplaceType.UNKNOWN  # `false` twice may still be unstated
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    parts = []
    for name in ("jobDescription", "qualifications", "additionalInformation",
                 "companyDescription"):
        section = sections.get(name) or {}
        if section.get("text"):
            parts.append(html_to_text(section["text"]))
    employment = str(((detail.get("typeOfEmployment") or raw.get("typeOfEmployment") or {})
                      .get("id")) or "").replace("_", " ") or None
    slug = str((raw.get("company") or {}).get("identifier") or "")
    url = str(detail.get("postingUrl") or (
        f"https://jobs.smartrecruiters.com/{slug}/{raw['id']}" if slug else ""))
    return (
        str(detail.get("name") or raw.get("name") or ""),
        url,
        location,
        workplace,
        employment,
        "\n".join(parts).strip(),
    )


def _talentsoft(raw: dict) -> _Mapped:
    title, url, location, contract, description = talentsoft.map_item(raw)
    return title, url, location, WorkplaceType.UNKNOWN, contract, description


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        v = v.strip()
        if v and v.lower() not in (s.lower() for s in seen):
            seen.append(v)
    return seen


def _workplace(value: Any) -> WorkplaceType:
    return _WORKPLACE.get(str(value or "").lower(), WorkplaceType.UNKNOWN)


def _published_at(ats: str, raw: dict) -> datetime | None:
    value = {"greenhouse": raw.get("first_published"), "lever": raw.get("createdAt"),
             "ashby": raw.get("publishedAt"), "smartrecruiters": raw.get("releasedDate"),
             "talentsoft": raw.get("published"),
             "workday": (raw.get(DETAIL_KEY) or {}).get("startDate")}.get(ats)
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        logger.debug("could not parse datetime: %r", value)
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


__all__ = ["AtsBoardSource", "board_id", "board_url"]
