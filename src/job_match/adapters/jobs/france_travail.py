import logging
import os
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime

from job_match.adapters.http import HttpClient
from job_match.adapters.jobs.base import RawItem
from job_match.config.schema import Profile
from job_match.domain.models import ContractType, Job, WorkplaceType

logger = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
PAGE_SIZE = 150
MAX_RESULTS = 3000
SCOPE = "api_offresdemploiv2 o2dsoffre"

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

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

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
        departments = self._profile.ft_search.departments or [None]
        keywords = self._profile.ft_search.keywords or []

        # One request per (keyword, department) — never join keywords (AND semantics)
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
        total_logged = False

        while fetched < self._max_results:
            end = start + PAGE_SIZE - 1
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
            resp.raise_for_status()

            if resp.status_code == 204:
                logger.info("query keyword=%r dept=%s → 0 results", label, dept_label)
                break

            body = resp.json()
            results: list[RawItem] = body.get("resultats") or []
            total = _parse_content_range_total(resp.headers.get("Content-Range", ""))

            if not total_logged:
                logger.info(
                    "query keyword=%r dept=%s → %d total", label, dept_label, total or len(results)
                )
                total_logged = True

            for item in results:
                yield item
                fetched += 1
                if fetched >= self._max_results:
                    return

            if total is None or fetched >= total or not results:
                break
            start += len(results)

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
