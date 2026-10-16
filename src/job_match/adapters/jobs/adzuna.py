"""Adzuna job source (disabled by default — the free tier is too small to be useful).

Quota-light, like Jooble, but cheaper per region: Adzuna's `what_or` takes OR'd keywords,
so all keywords fit in **one** call per region instead of one per keyword x region. Page 1
only, capped by `max_calls_per_run`.

`app_id` and `app_key` travel as query parameters, so they must never reach a log line.
`_SAFE_URL` is what this module logs; `cli.py` keeps httpx's own request log above INFO.
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

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
_SAFE_URL = f"{SEARCH_URL}?app_id=<id>&app_key=<key>"
PAGE_SIZE = 50
QUERY_KEY = "_jm_query"
REGION_KEY = "_jm_region"


class AdzunaSource:
    name = "adzuna"

    def __init__(
        self,
        profile: Profile,
        app_id: str,
        app_key: str,
        regions: list[str],
        http: HttpClient | None = None,
        max_results: int = PAGE_SIZE,
        max_calls_per_run: int = 20,
        requests_per_second: float = 1.0,
    ) -> None:
        self._profile = profile
        self._app_id = app_id
        self._app_key = app_key
        self._regions = regions or [""]
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

    def fetch(self, since: datetime | None = None) -> Iterator[RawItem]:
        # All keywords in one query per region: what_or is OR semantics, so this costs
        # one call where France Travail would spend one per keyword.
        what_or = " ".join(self._profile.ft_search.keywords)
        for region in self._regions:
            if self._api_calls >= self._max_calls:
                logger.warning(
                    "%s: call budget exhausted (%d/%d), stopping this run",
                    self.name, self._api_calls, self._max_calls,
                )
                return
            yield from self._fetch_query(what_or, region, since)
        logger.info("%s: %d/%d calls used", self.name, self._api_calls, self._max_calls)

    def _fetch_query(
        self, what_or: str, region: str, since: datetime | None
    ) -> Iterator[RawItem]:
        area = region or "all"
        fetched = 0
        total: int | None = None
        params = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": str(min(self._max_results, PAGE_SIZE)),
            "content-type": "application/json",
        }
        if what_or:
            params["what_or"] = what_or
        if region:
            params["where"] = region
        if since is not None:
            params["max_days_old"] = str(max(1, (datetime.now(UTC) - since).days))

        try:
            self._throttle()
            resp = self._http.get(SEARCH_URL, params=params)
            self._api_calls += 1
            resp.raise_for_status()
            body = resp.json() or {}
            total = _as_int(body.get("count"))

            for item in body.get("results") or []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue  # no stable id → nothing to dedup or upsert on
                item[QUERY_KEY] = "what_or"  # one query covers every keyword
                item[REGION_KEY] = area
                yield item
                fetched += 1
                if fetched >= self._max_results:
                    return
        finally:
            self._query_stats.append(QueryStat("what_or", area, fetched, total, self.name))
            logger.info(
                "%s query area=%s fetched=%d available=%s (%s)",
                self.name, area, fetched, total if total is not None else "?", _SAFE_URL,
            )

    def to_job(self, raw: RawItem) -> Job:
        description = str(raw.get("description") or "")
        return Job(
            source=self.name,
            source_job_id=str(raw["id"]),
            title=str(raw.get("title") or ""),
            company=str((raw.get("company") or {}).get("display_name") or ""),
            location=str((raw.get("location") or {}).get("display_name") or ""),
            workplace_type=WorkplaceType.UNKNOWN,  # Adzuna has no workplace field
            contract_type=parse_contract_type(
                raw.get("contract_type"), raw.get("title"), description
            ),
            description=description,
            url=str(raw.get("redirect_url") or ""),
            published_at=_parse_dt(raw.get("created")),
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
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.debug("could not parse datetime: %r", value)
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
