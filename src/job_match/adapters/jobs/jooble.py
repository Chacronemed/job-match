"""Jooble job source.

Quota-light: the free plan allows a few hundred calls a day, so there is no
keyword x department fan-out here. One POST per keyword x region, page 1 only, and a hard
`max_calls_per_run` ceiling on top.

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
QUERY_KEY = "_jm_query"   # adapter-private: which keyword returned the item
REGION_KEY = "_jm_region"


class JoobleSource:
    name = "jooble"

    def __init__(
        self,
        profile: Profile,
        api_key: str,
        regions: list[str],
        http: HttpClient | None = None,
        max_results: int = PAGE_SIZE,
        max_calls_per_run: int = 15,
        requests_per_second: float = 1.0,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._regions = regions or [""]  # "" = whole country, still one call
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
        """One entry per (keyword, region) query, in execution order."""
        return tuple(self._query_stats)

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request_time)
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def fetch(self, since: datetime | None = None) -> Iterator[RawItem]:
        for keyword in self._profile.ft_search.keywords:
            for region in self._regions:
                if self._api_calls >= self._max_calls:
                    logger.warning(
                        "%s: call budget exhausted (%d/%d), stopping this run",
                        self.name, self._api_calls, self._max_calls,
                    )
                    return
                yield from self._fetch_query(keyword, region)
        logger.info("%s: %d/%d calls used", self.name, self._api_calls, self._max_calls)

    def _fetch_query(self, keyword: str, region: str) -> Iterator[RawItem]:
        area = region or "all"
        fetched = 0
        total: int | None = None
        try:
            self._throttle()
            resp = self._http.post(
                f"{API_ROOT}/{self._api_key}",
                json={
                    "keywords": keyword,
                    "location": region,
                    "page": "1",
                    "ResultOnPage": str(min(self._max_results, PAGE_SIZE)),
                },
            )
            self._api_calls += 1
            resp.raise_for_status()
            body = resp.json() or {}
            total = _as_int(body.get("totalCount"))

            for item in body.get("jobs") or []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue  # no stable id → nothing to dedup or upsert on
                item[QUERY_KEY] = keyword
                item[REGION_KEY] = area
                yield item
                fetched += 1
                if fetched >= self._max_results:
                    return
        finally:
            self._query_stats.append(QueryStat(keyword, area, fetched, total, self.name))
            logger.info(
                "%s query area=%s fetched=%d available=%s (%s)",
                self.name, area, fetched, total if total is not None else "?", _SAFE_URL,
            )
            logger.debug("%s query keyword=%s area=%s", self.name, keyword, area)

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
