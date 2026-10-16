import logging
import os
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime

from job_match.adapters.http import HttpClient
from job_match.adapters.jobs.base import QueryStat, RawItem
from job_match.config.schema import Profile
from job_match.domain.models import ContractType, Job, WorkplaceType

logger = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
PAGE_SIZE = 150
# The endpoint only exposes a window: the Range start may not exceed 1000 and its end may
# not exceed 1149, so with 150-offer pages a single query reaches 1050 offers over 7 pages
# and no more. Per department that ceiling was out of reach; a national query hits it, so
# we clamp the range, stop, and say so instead of being refused.
MAX_RANGE_START = 1000
MAX_RANGE_END = 1149
MAX_RESULTS = MAX_RANGE_END + 1
SCOPE = "api_offresdemploiv2 o2dsoffre"
QUERY_KEY = "_jm_query"  # set on raw items by _fetch_query, mapped to Job.search_query

_CONTRACT_MAP: dict[str, ContractType] = {
    "CDI": ContractType.CDI,
    "CDD": ContractType.CDD,
    "MIS": ContractType.INTERIM,
    "SAI": ContractType.CDD,   # saisonnier
    "ALT": ContractType.ALTERNANCE,
    "PRO": ContractType.ALTERNANCE,  # professionnalisation
    "FRA": ContractType.FREELANCE,
    "LIB": ContractType.FREELANCE,
}

_CONTENT_RANGE_RE = re.compile(r"offres\s+\d+-\d+/(\d+)", re.IGNORECASE)


class FranceTravailSource:
    name = "france_travail"

    def __init__(
        self,
        profile: Profile,
        http: HttpClient | None = None,
        max_results: int = MAX_RESULTS,
        requests_per_second: float = 3.0,
    ) -> None:
        self._profile = profile
        self._http = http or HttpClient()
        self._max_results = max_results
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._min_interval: float = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request_time: float = 0.0
        self._api_calls: int = 0
        self._query_stats: list[QueryStat] = []

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

    @property
    def query_stats(self) -> tuple[QueryStat, ...]:
        """One entry per (keyword|rome, department) query, in execution order."""
        return tuple(self._query_stats)

    def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at - 60:
            return self._token
        resp = self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": os.environ["FT_CLIENT_ID"],
                "client_secret": os.environ["FT_CLIENT_SECRET"],
                "scope": SCOPE,
            },
            params={"realm": "/partenaire"},
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.monotonic() + float(body["expires_in"])
        return self._token

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def fetch(self, since: datetime | None = None) -> Iterator[RawItem]:
        # An empty department list is a national search (`location_scope: france`): no
        # `departement` param, one paginated query per keyword.
        departments = self._profile.ft_search.departments or [None]
        keywords = self._profile.ft_search.keywords or []

        # One request per (keyword, area) — never join keywords (AND semantics)
        for keyword in keywords:
            for dept in departments:
                yield from self._fetch_query(since, dept, keyword=keyword)

        # Optional ROME-only searches (off by default — controlled by use_rome_search in profile)
        if self._profile.ft_search.use_rome_search:
            for rome_code in self._profile.ft_search.rome_codes:
                for dept in departments:
                    yield from self._fetch_query(since, dept, rome_code=rome_code)

    def _fetch_query(
        self,
        since: datetime | None,
        dept: str | None,
        *,
        keyword: str | None = None,
        rome_code: str | None = None,
    ) -> Iterator[RawItem]:
        params = _build_params(self._profile, since, dept, keyword=keyword, rome_code=rome_code)
        label = keyword or rome_code or "no-filter"
        dept_label = dept or "all"
        start = 0
        fetched = 0
        total: int | None = None
        window_exhausted = False

        # _max_results caps THIS query only — never the fan-out, so every
        # (keyword, department) pair always gets its own budget.
        try:
            while fetched < self._max_results:
                if start > MAX_RANGE_START:
                    window_exhausted = True
                    break  # no further page is addressable; see the warning in `finally`
                end = min(start + PAGE_SIZE - 1, MAX_RANGE_END)
                token = self._ensure_token()
                self._throttle()
                resp = self._http.get(
                    SEARCH_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Range": f"{start}-{end}",
                    },
                    params=params,
                )
                self._api_calls += 1

                if resp.status_code == 400:
                    # A refused range ends this query, it does not end the run: the other
                    # keywords are still worth fetching.
                    logger.warning(
                        "%s: area=%s range %d-%d refused (HTTP 400), stopping this query",
                        self.name, dept_label, start, end,
                    )
                    break
                resp.raise_for_status()

                if resp.status_code == 204:
                    break

                body = resp.json()
                results: list[RawItem] = body.get("resultats") or []
                page_total = _parse_content_range_total(resp.headers.get("Content-Range", ""))
                if page_total is not None:
                    total = page_total

                for item in results:
                    item[QUERY_KEY] = label  # adapter-private: which query returned the item
                    yield item
                    fetched += 1
                    if fetched >= self._max_results:
                        return

                if total is None or fetched >= total or not results:
                    break
                start += len(results)
        finally:
            # Runs on normal exit, on the max_results return, and on errors.
            if window_exhausted and total is not None and fetched < total:
                # Drained the whole window and the API says there is more. Nationwide this
                # is the ceiling that bites, and it must not be silent.
                logger.warning(
                    "%s: area=%s truncated by the API window: %d of %d offers reachable "
                    "(narrow the keyword, or restrict location_scope)",
                    self.name, dept_label, fetched, total,
                )
            self._query_stats.append(QueryStat(label, dept_label, fetched, total, self.name))
            available = total if total is not None else "?"
            # Query keywords come from the private profile: aggregates at INFO, keyword at DEBUG.
            logger.info("query dept=%s fetched=%d available=%s", dept_label, fetched, available)
            logger.debug(
                "query keyword=%s dept=%s fetched=%d available=%s",
                label, dept_label, fetched, available,
            )

    def to_job(self, raw: RawItem) -> Job:
        return Job(
            source=self.name,
            source_job_id=raw["id"],
            title=raw.get("intitule", ""),
            company=(raw.get("entreprise") or {}).get("nom", ""),
            location=(raw.get("lieuTravail") or {}).get("libelle", ""),
            workplace_type=WorkplaceType.UNKNOWN,
            contract_type=_CONTRACT_MAP.get(
                raw.get("typeContrat", ""), ContractType.UNKNOWN
            ),
            description=raw.get("description", ""),
            url=(raw.get("origineOffre") or {}).get("urlOrigine", ""),
            published_at=_parse_dt(raw.get("dateCreation")),
            collected_at=datetime.now(UTC),
            search_query=raw.get(QUERY_KEY),
        )


def _build_params(
    profile: Profile,
    since: datetime | None,
    dept: str | None,
    *,
    keyword: str | None = None,
    rome_code: str | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {}
    if keyword:
        params["motsCles"] = keyword  # single keyword — never combined with ROME
    elif rome_code:
        params["codeROME"] = rome_code  # ROME-only, no keywords
    if dept:
        params["departement"] = dept
    if since:
        params["minCreationDate"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    return params


def _parse_content_range_total(header: str) -> int | None:
    m = _CONTENT_RANGE_RE.match(header.strip())
    return int(m.group(1)) if m else None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).astimezone(UTC)
    except (ValueError, TypeError):
        logger.debug("could not parse datetime: %r", s)
        return None
