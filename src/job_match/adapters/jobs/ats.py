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

The endpoint shapes above follow the provider modules of career-ops
(https://github.com/career-ops-hq/career-ops, `providers/greenhouse.mjs`, `lever.mjs`,
`ashby.mjs`; MIT License, Copyright (c) 2026 Santiago Fernández de Valderrama), read for
their field mapping and re-implemented here in Python: `absolute_url` / `hostedUrl` /
`jobUrl` as the posting URL, `first_published` / `createdAt` / `publishedAt` as the posting
date, Lever's `lists` folded into the description, Ashby's `isRemote` as a fallback for
`workplaceType`. No code is copied.

Terms: public JSON only, no HTML page is fetched, one request per second (Lever's
robots.txt asks for `Crawl-delay: 1`), the project's User-Agent. A board that answers 404
(the company left the ATS, or the slug changed) or any network error is logged and skipped;
the other boards still run, and a run with every board down yields nothing instead of
failing. The gates, dedup and scoring downstream are the same as for any other source.

`source_job_id` is `<ats>:<slug>:<id>` so `check_offer` can find the board again: an id
missing from a board that answered 200 is CLOSED, a board that could not be read is UNKNOWN.
"""
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from job_match.adapters.http import HttpClient
from job_match.adapters.jobs.base import OfferStatus, QueryStat, RawItem
from job_match.config.schema import AtsBoard
from job_match.domain.models import Job, WorkplaceType
from job_match.normalization.contract import parse_contract_type
from job_match.normalization.text import html_to_text

logger = logging.getLogger(__name__)

SOURCE_NAME = "ats"
BOARD_KEY = "_jm_board"  # adapter-private: "<ats>:<slug>" the item came from
COMPANY_KEY = "_jm_company"  # the configured display name, not the source's

ENDPOINTS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

_WORKPLACE: dict[str, WorkplaceType] = {
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
    "onsite": WorkplaceType.ONSITE,
    "on-site": WorkplaceType.ONSITE,
    "unspecified": WorkplaceType.UNKNOWN,
}

# Ashby's `employmentType` values that name a contract type; the rest ("FullTime",
# "PartTime") are working time, not a contract, and fall through to the text parser.
_ASHBY_EMPLOYMENT: dict[str, str] = {"intern": "internship", "temporary": "temporary"}


def board_url(board: AtsBoard) -> str:
    return ENDPOINTS[board.ats].format(slug=board.slug)


class AtsBoardSource:
    name = SOURCE_NAME
    reports_by_company = True  # the run summary counts fetched / eligible per board company

    def __init__(
        self,
        boards: list[AtsBoard],
        http: HttpClient | None = None,
        max_results: int | None = None,
        requests_per_second: float = 1.0,
    ) -> None:
        self._boards = list(boards)
        self._http = http or HttpClient()
        self._max_results = max_results
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request_time = 0.0
        self._api_calls = 0
        self._query_stats: list[QueryStat] = []
        # "<ats>:<slug>" → ids the board listed, or None when the board could not be read.
        self._board_ids: dict[str, set[str] | None] = {}

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

    @property
    def query_stats(self) -> tuple[QueryStat, ...]:
        """One entry per board, in execution order: query=slug, area=ATS name."""
        return tuple(self._query_stats)

    # ------------------------------------------------------------------ fetching

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request_time)
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def _get_board(self, board: AtsBoard) -> list[dict] | None:
        """The board's postings, or None when it could not be read (logged, never raised)."""
        url = board_url(board)
        try:
            self._throttle()
            resp = self._http.get(url)
            self._api_calls += 1
            if resp.status_code == 404:
                logger.warning("%s: %s/%s answers 404, skipped (slug gone?)",
                               self.name, board.ats, board.slug)
                return None
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("%s: %s/%s unreachable: %s", self.name, board.ats, board.slug,
                           type(exc).__name__)
            return None
        jobs = body if isinstance(body, list) else (body or {}).get("jobs")
        if not isinstance(jobs, list):
            logger.warning("%s: %s/%s: unexpected payload shape, skipped",
                           self.name, board.ats, board.slug)
            return None
        return [j for j in jobs if isinstance(j, dict) and j.get("id") is not None]

    def fetch(self, since: datetime | None = None) -> Iterator[RawItem]:
        if not self._boards:
            logger.warning("%s: no board configured (config/ats_boards.yaml)", self.name)
            return
        unreachable = 0
        for board in self._boards:
            key = f"{board.ats}:{board.slug}"
            jobs = self._get_board(board)
            if jobs is None:
                unreachable += 1
                self._board_ids[key] = None
                self._query_stats.append(QueryStat(board.slug, board.ats, 0, None, self.name))
                continue
            self._board_ids[key] = {str(j["id"]) for j in jobs}
            fetched = 0
            for item in jobs:
                if board.ats == "ashby" and item.get("isListed") is False:
                    continue
                if since is not None:
                    published = _published_at(board.ats, item)
                    if published is not None and published < since:
                        continue
                item[BOARD_KEY] = key
                item[COMPANY_KEY] = board.company
                yield item
                fetched += 1
                if self._max_results is not None and fetched >= self._max_results:
                    break
            self._query_stats.append(
                QueryStat(board.slug, board.ats, fetched, len(jobs), self.name)
            )
            logger.info("%s: %s/%s fetched=%d available=%d",
                        self.name, board.ats, board.slug, fetched, len(jobs))
        if unreachable:
            logger.warning("%s: %d/%d boards skipped as unreachable",
                           self.name, unreachable, len(self._boards))

    # ------------------------------------------------------------------ mapping

    def to_job(self, raw: RawItem) -> Job:
        ats, slug = str(raw[BOARD_KEY]).split(":", 1)
        company = str(raw.get(COMPANY_KEY) or raw.get("company_name") or slug)
        mapper = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}[ats]
        title, url, location, workplace, contract_hint, description = mapper(raw)
        return Job(
            source=self.name,
            source_job_id=f"{ats}:{slug}:{raw['id']}",
            title=title,
            company=company,
            location=location,
            workplace_type=workplace,
            contract_type=parse_contract_type(contract_hint, title, description),
            description=description,
            url=url,
            published_at=_published_at(ats, raw),
            collected_at=datetime.now(UTC),
            search_query=slug,
        )

    # ------------------------------------------------------------------ closure

    def check_offer(self, source_job_id: str) -> OfferStatus:
        """Still listed on its board? One board read per run, shared by every offer of it."""
        try:
            ats, slug, job_id = source_job_id.split(":", 2)
        except ValueError:
            return OfferStatus.UNKNOWN
        key = f"{ats}:{slug}"
        if key not in self._board_ids:
            board = next((b for b in self._boards if f"{b.ats}:{b.slug}" == key), None)
            if board is None:
                return OfferStatus.UNKNOWN  # no longer configured: nothing to ask
            jobs = self._get_board(board)
            self._board_ids[key] = None if jobs is None else {str(j["id"]) for j in jobs}
        ids = self._board_ids[key]
        if ids is None:
            return OfferStatus.UNKNOWN
        return OfferStatus.OPEN if job_id in ids else OfferStatus.CLOSED


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
             "ashby": raw.get("publishedAt")}.get(ats)
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


__all__ = ["AtsBoardSource", "board_url"]
