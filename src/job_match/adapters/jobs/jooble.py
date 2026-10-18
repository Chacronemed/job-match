"""Jooble job source.

Quota-light: the free plan allows a few hundred calls a day, so there is no
keyword x department fan-out here. One POST per region, with every keyword in it, and a
hard `max_calls_per_run` ceiling on top.

One combined query is enough because Jooble ORs the words in `keywords` and ranks by
relevance, it does not AND them: probing Ile-de-France (scripts/jooble_probe.py) returned
21 offers for "devops", 3 for "kubernetes", and exactly their union -- the same 21 ids --
for "devops kubernetes sre". The combined query covered 100% of both single-keyword result
sets, so 7 keywords x N regions collapse to N calls. The budget freed up pays for
pagination instead: each page is one call, and a region gets at most
`max_calls_per_run // len(regions)` of them, so page 1 of every region is always affordable.

The regions are how "France" is said to Jooble: jooble.org is a worldwide index whose
`location` is a literal filter, so an empty location is the whole planet and "France" only
the offers that literally say "France" (scripts/jooble_location_probe.py, 2026-10-18).

The API key is a path segment (`POST /api/<key>`), so it must never reach a log line.
`_SAFE_URL` is what this module logs, and `cli.py` keeps httpx's own request log — which
would print the real URL — above INFO.
"""
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime

from job_match.adapters.http import HttpClient
from job_match.adapters.jobs.base import QueryStat, RawItem
from job_match.config.schema import Profile
from job_match.domain.models import Job, WorkplaceType
from job_match.normalization.contract import parse_contract_type

logger = logging.getLogger(__name__)

API_ROOT = "https://jooble.org/api"
_SAFE_URL = f"{API_ROOT}/<key>"  # what we log instead of the real URL
PAGE_SIZE = 50
QUERY_KEY = "_jm_query"   # adapter-private: the keyword string the item came back for
REGION_KEY = "_jm_region"


class JoobleSource:
    name = "jooble"

    def __init__(
        self,
        profile: Profile,
        api_key: str,
        regions: list[str],
        http: HttpClient | None = None,
        max_results: int | None = None,
        max_calls_per_run: int = 15,
        requests_per_second: float = 1.0,
        radius_km: int | None = None,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._regions = regions or [""]  # "" = the whole index (worldwide), still one call
        self._radius_km = radius_km  # None = the place itself, as the index matches it
        self._http = http or HttpClient()
        self._max_results = max_results
        self._max_calls = max_calls_per_run
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request_time = 0.0
        self._api_calls = 0
        self._query_stats: list[QueryStat] = []

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

    @property
    def query_stats(self) -> tuple[QueryStat, ...]:
        """One entry per region query, in execution order."""
        return tuple(self._query_stats)

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request_time)
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    @property
    def pages_per_region(self) -> int:
        """Page budget per region, so every region can afford its page 1."""
        return max(1, self._max_calls // max(1, len(self._regions)))

    def fetch(self, since: datetime | None = None) -> Iterator[RawItem]:
        keywords = " ".join(self._profile.ft_search.keywords)
        pages = self.pages_per_region
        for region in self._regions:
            if self._out_of_budget():
                break
            yield from self._fetch_query(keywords, region, pages)
        logger.info("%s: %d/%d calls used", self.name, self._api_calls, self._max_calls)

    def _out_of_budget(self) -> bool:
        if self._api_calls < self._max_calls:
            return False
        logger.warning(
            "%s: call budget exhausted (%d/%d), stopping this run",
            self.name, self._api_calls, self._max_calls,
        )
        return True

    def _fetch_query(self, keywords: str, region: str, max_pages: int) -> Iterator[RawItem]:
        """One region, pages 1..max_pages. Every page spends one call."""
        area = region or "all"
        page_size = PAGE_SIZE if self._max_results is None else min(self._max_results, PAGE_SIZE)
        fetched = 0
        pages = 0
        total: int | None = None
        try:
            for page in range(1, max_pages + 1):
                if self._out_of_budget():
                    return
                body_out = {
                    "keywords": keywords,
                    "location": region,
                    "page": str(page),
                    "ResultOnPage": str(page_size),
                }
                if self._radius_km is not None:
                    body_out["radius"] = str(self._radius_km)
                self._throttle()
                resp = self._http.post(f"{API_ROOT}/{self._api_key}", json=body_out)
                self._api_calls += 1
                pages += 1
                resp.raise_for_status()
                body = resp.json() or {}
                if (count := _as_int(body.get("totalCount"))) is not None:
                    total = count

                raw_items = body.get("jobs") or []
                for item in raw_items:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue  # no stable id → nothing to dedup or upsert on
                    item[QUERY_KEY] = keywords
                    item[REGION_KEY] = area
                    yield item
                    fetched += 1
                    if self._max_results is not None and fetched >= self._max_results:
                        return
                if len(raw_items) < page_size or (total is not None and fetched >= total):
                    return  # last page for this region
        finally:
            self._query_stats.append(QueryStat(keywords, area, fetched, total, self.name))
            logger.info(
                "%s query area=%s pages=%d fetched=%d available=%s (%s)",
                self.name, area, pages, fetched,
                total if total is not None else "?", _SAFE_URL,
            )
            logger.debug("%s query keywords=%s area=%s", self.name, keywords, area)

    def to_job(self, raw: RawItem) -> Job:
        snippet = str(raw.get("snippet") or "")
        return Job(
            source=self.name,
            source_job_id=str(raw["id"]),
            title=str(raw.get("title") or ""),
            company=str(raw.get("company") or ""),
            location=str(raw.get("location") or ""),
            workplace_type=WorkplaceType.UNKNOWN,  # Jooble has no workplace field
            contract_type=parse_contract_type(raw.get("type"), raw.get("title"), snippet),
            description=snippet,  # Jooble returns a snippet, never the full description
            url=str(raw.get("link") or ""),
            published_at=_parse_dt(raw.get("updated")),
            collected_at=datetime.now(UTC),
            search_query=raw.get(QUERY_KEY),
        )


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        logger.debug("could not parse datetime: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
