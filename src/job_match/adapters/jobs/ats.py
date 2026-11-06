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
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from job_match.adapters.http import HttpClient
from job_match.adapters.jobs.base import OfferStatus, QueryStat, RawItem, RequestStats
from job_match.config.schema import AtsBoard
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
}
PAGED_ATS = ("workday", "smartrecruiters")
DEFAULT_MAX_POSTINGS = 100  # per paged board and run: the newest French postings
WORKDAY_PAGE = 20  # Workday refuses a larger `limit`
SMARTRECRUITERS_PAGE = 100
SMARTRECRUITERS_COUNTRY = "fr"
WORKDAY_COUNTRY = "france"  # the facet value's descriptor, case-insensitive

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
    return ENDPOINTS[board.ats].format(slug=board.slug)


class _Listing(NamedTuple):
    jobs: list[dict]
    available: int | None  # what the board says it has (French only for the paged ATS)
    complete: bool         # every posting listed: a missing id means closed


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
    ) -> None:
        self._boards = list(boards)
        self._http = http or HttpClient()
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

    # ------------------------------------------------------------------ HTTP

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        last = self._last_request.get(host)
        if last is not None:
            wait = self._min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def _call(self, method: str, url: str, label: str, **kwargs: Any) -> tuple[int | None, Any]:
        """(HTTP status, decoded body): (None, None) on a network error, (404, None) for a
        404, (status, None) for any other error status. Logged, never raised."""
        self._attempted += 1
        try:
            self._throttle(url)
            headers = {"Accept": "application/json"}
            if method == "POST":
                resp = self._http.post(url, headers=headers, **kwargs)
            else:
                resp = self._http.get(url, headers=headers, **kwargs)
            self._api_calls += 1
            if resp.status_code == 404:
                logger.warning("%s: %s answers 404 (gone?)", self.name, label)
                return 404, None
            resp.raise_for_status()
            return resp.status_code, resp.json()
        except Exception as exc:
            self._failed += 1
            logger.warning("%s: %s unreachable: %s", self.name, label, type(exc).__name__)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return status, None

    def _json(self, method: str, url: str, label: str, **kwargs: Any) -> Any:
        """The decoded body, or None when the call failed (logged, never raised)."""
        return self._call(method, url, label, **kwargs)[1]

    # ------------------------------------------------------------------ listings

    def _list_board(self, board: AtsBoard) -> _Listing | None:
        if board.ats == "workday":
            return self._list_workday(board)
        if board.ats == "smartrecruiters":
            return self._list_smartrecruiters(board)
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
        facet = _workday_country_facet(first.get("facets"))
        if facet is None:
            logger.warning("%s: %s has no country facet, skipped (cannot keep France only)",
                           self.name, label)
            return None
        param, value = facet
        if value is None:
            return _Listing([], 0, True)  # a country facet without France: no French posting
        cap = self._cap(board)
        jobs: list[dict] = []
        total: int | None = None
        offset = 0
        while len(jobs) < cap:
            body = self._json("POST", url, label, json={
                "appliedFacets": {param: [value]}, "limit": WORKDAY_PAGE,
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
                posting["id"] = _workday_id(str(posting["externalPath"]))
            jobs.extend(page)
            offset += WORKDAY_PAGE
            if not page or (total is not None and offset >= total):
                break
        jobs = jobs[:cap]
        complete = total is not None and len(jobs) >= total
        return _Listing(jobs, total, complete)

    def _list_smartrecruiters(self, board: AtsBoard) -> _Listing | None:
        label = f"smartrecruiters/{board.slug}"
        url = board_url(board)
        cap = self._cap(board)
        jobs: list[dict] = []
        total: int | None = None
        offset = 0
        while len(jobs) < cap:
            body = self._json("GET", url, label, params={
                "country": SMARTRECRUITERS_COUNTRY, "limit": SMARTRECRUITERS_PAGE,
                "offset": offset,
            })
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
            listing = self._list_board(board)
            if listing is None:
                unreachable += 1
                self._board_ids[key] = None
                self._query_stats.append(
                    QueryStat(board_id(board), board.ats, 0, None, self.name))
                continue
            self._board_ids[key] = ({str(j["id"]) for j in listing.jobs}, listing.complete)
            fetched = skipped = 0
            for item in listing.jobs:
                if board.ats == "ashby" and item.get("isListed") is False:
                    continue
                if since is not None:
                    published = _published_at(board.ats, item)
                    if published is not None and published < since:
                        continue
                if board.ats in PAGED_ATS:
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
            self._query_stats.append(
                QueryStat(board_id(board), board.ats, fetched, listing.available, self.name)
            )
            logger.info("%s: %s/%s fetched=%d available=%s%s",
                        self.name, board.ats, board_id(board), fetched, listing.available,
                        f" detail_failed={skipped}" if skipped else "")
        if unreachable:
            logger.warning("%s: %d/%d boards skipped as unreachable",
                           self.name, unreachable, len(self._boards))

    # ------------------------------------------------------------------ mapping

    def to_job(self, raw: RawItem) -> Job:
        ats, bid = str(raw[BOARD_KEY]).split(":", 1)
        company = str(raw.get(COMPANY_KEY) or raw.get("company_name") or bid)
        mapper = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby,
                  "workday": _workday, "smartrecruiters": _smartrecruiters}[ats]
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
        if key not in self._board_ids:
            board = next((b for b in self._boards
                          if f"{b.ats}:{board_id(b)}" == key), None)
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
        board = next(b for b in self._boards if f"{b.ats}:{board_id(b)}" == key)
        return self._probe(board, job_id)

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
                        and _workday_id(str(p["externalPath"])) == job_id
                        for p in body["jobPostings"])
            return OfferStatus.OPEN if found else OfferStatus.CLOSED
        return OfferStatus.UNKNOWN


# ---------------------------------------------------------------------- Workday helpers

def _workday_country_facet(facets: Any) -> tuple[str, str | None] | None:
    """(facet parameter, France value id or None) of the first country facet, nested
    groups included (`locationMainGroup` → `locationCountry`); None without one."""
    for facet in facets or []:
        if not isinstance(facet, dict):
            continue
        values = facet.get("values") or []
        if values and isinstance(values[0], dict) and "facetParameter" in values[0]:
            found = _workday_country_facet(values)
            if found is not None:
                return found
            continue
        param = str(facet.get("facetParameter") or "")
        if "country" not in param.lower():
            continue
        france = next((v.get("id") for v in values if isinstance(v, dict)
                       and str(v.get("descriptor") or "").strip().lower() == WORKDAY_COUNTRY
                       and v.get("id")), None)
        return param, (str(france) if france else None)
    return None


def _workday_id(external_path: str) -> str:
    """`/job/Brest/Ingenieur-CFD_R0347114-1` → `R0347114-1`: the requisition id Workday
    ends every posting path with. A path without one keeps its last segment."""
    tail = external_path.rstrip("/").rsplit("/", 1)[-1]
    ident = tail.rsplit("_", 1)[-1] if "_" in tail else tail
    cleaned = "".join(ch for ch in ident if ch.isalnum() or ch in "-.")
    return cleaned[:100] or "unknown"


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
