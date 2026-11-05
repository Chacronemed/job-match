"""Which ATS really serves each target company's postings (M28, ADR 0020 amendment).

`config/companies.yaml` carries an *unverified* ATS guess per company. This module checks
each one against the ATS's public, unauthenticated JSON endpoint, the same kind of endpoint
the `ats` source reads (ADR 0020), plus the two the big groups use:

    greenhouse       GET  boards-api.greenhouse.io/v1/boards/<slug>/jobs
    lever            GET  api.lever.co/v0/postings/<slug>?mode=json
    ashby            GET  api.ashbyhq.com/posting-api/job-board/<slug>
    smartrecruiters  GET  api.smartrecruiters.com/v1/companies/<id>/postings?limit=1
    workday          POST <tenant>.<wdN>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs

Three steps, stopping at the first verified answer:

1. **url**: the ATS and identifier written in `careers_url` itself
   (`ag.wd3.myworkdayjobs.com/Airbus`, `jobs.lever.co/alan`).
2. **page**: one GET of the careers page (redirects followed): the final URL and the
   ATS links in the HTML. The page is read for links only, never stored or logged.
3. **slug**: the company name as a slug (`dassaultsystemes`, `dassault-systemes`) on the
   guessed ATS first, then on the others. Workday cannot be guessed (it needs a site name).

**Verified** means the endpoint answered 200 with the expected shape and at least one
posting: an unknown SmartRecruiters company answers 200 with zero postings, so an empty
board proves nothing. **Custom** means no supported endpoint answered but the careers page
is reachable: either a platform without a public JSON board was recognized (Taleo,
SuccessFactors, Talentsoft...) or the site is the company's own (its listings may still
come from an ATS loaded by JavaScript, which one GET cannot see). **Not found**: neither.

One request per second per host, the project's User-Agent. Aggregates only: no title or
description of any posting is kept.
"""
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from job_match.adapters.http import HttpClient
from job_match.config.schema import TargetCompany

logger = logging.getLogger(__name__)

VERIFIED, CUSTOM, NOT_FOUND = "verified", "custom", "not_found"

# The ATS with a public JSON endpoint, in the order an unguided slug is tried.
PUBLIC_ATS: tuple[str, ...] = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
SLUG_ATS: tuple[str, ...] = ("greenhouse", "lever", "ashby", "smartrecruiters")

_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}"
_LOCALE = r"(?:[a-z]{2}(?:[-_][A-Za-z]{2})?/)?"

# (ats, pattern) — group 1 is the identifier; Workday's are tenant/site (see _workday_id).
_LINKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("workday", re.compile(
        rf"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/{_LOCALE}({_ID})", re.I)),
    ("workday", re.compile(
        rf"https?://(wd\d+)\.myworkdaysite\.com/{_LOCALE}recruiting/([a-z0-9_-]+)/({_ID})", re.I)),
    ("smartrecruiters", re.compile(rf"(?:jobs|careers)\.smartrecruiters\.com/({_ID})", re.I)),
    ("smartrecruiters", re.compile(rf"api\.smartrecruiters\.com/v1/companies/({_ID})", re.I)),
    ("greenhouse", re.compile(
        rf"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?({_ID})", re.I)),
    ("greenhouse", re.compile(rf"boards-api\.greenhouse\.io/v1/boards/({_ID})", re.I)),
    ("lever", re.compile(rf"jobs\.lever\.co/({_ID})", re.I)),
    ("lever", re.compile(rf"api\.lever\.co/v0/postings/({_ID})", re.I)),
    ("ashby", re.compile(rf"jobs\.ashbyhq\.com/({_ID})", re.I)),
    ("ashby", re.compile(rf"api\.ashbyhq\.com/posting-api/job-board/({_ID})", re.I)),
)
# Path words that follow an ATS host but are not a board identifier.
_NOT_AN_ID = {"embed", "api", "v0", "v1", "js", "static", "assets", "jobs", "job", "share",
              "careers", "en", "fr", "en-us", "fr-fr", "search", "apply", "widget"}

# Platforms without a public JSON board this project reads: recognized, reported as custom.
_PLATFORMS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.I)) for name, pattern in (
        ("taleo", r"\.taleo\.net"),
        ("successfactors", r"successfactors\.(?:com|eu)|jobs\.sap\.com|career\d*\.sapsf"),
        ("talentsoft", r"talent-soft\.com|talentsoft\.(?:com|net)"),
        ("oracle_hcm", r"oraclecloud\.com/hcmUI/CandidateExperience"),
        ("icims", r"\.icims\.com"),
        ("teamtailor", r"\.teamtailor\.com"),
        ("welcometothejungle", r"welcometothejungle\.com"),
        ("workable", r"apply\.workable\.com"),
        ("recruitee", r"\.recruitee\.com"),
        ("jobvite", r"jobs\.jobvite\.com"),
        ("cornerstone", r"\.csod\.com"),
        ("avature", r"\.avature\.net"),
        ("phenom", r"phenompeople\.com|cdn\.phenompeople"),
        ("eightfold", r"\.eightfold\.ai"),
        ("digitalrecruiters", r"digitalrecruiters\.com"),
        ("jobs_net", r"\.jobs\.net"),
        ("njoyn", r"\.njoyn\.com"),
        ("beetween", r"beetween\.com"),
        ("flatchr", r"flatchr\.io"),
        ("jobaffinity", r"jobaffinity\.fr"),
    )
)

_PAGE_LIMIT = 3_000_000  # characters of HTML scanned for links; the rest is ignored


@dataclass(frozen=True)
class Candidate:
    ats: str
    identifier: str  # slug, company id, or "<host>/<tenant>/<site>" for Workday
    method: str      # url | page | slug


@dataclass
class Detection:
    company: str
    status: str                       # verified | custom | not_found
    ats: str | None = None
    identifier: str | None = None
    postings: int | None = None       # what the board lists, every country
    method: str | None = None
    platform: str | None = None       # custom: the recognized platform, if any
    guess: str | None = None          # companies.yaml's ats_guess, for the comparison
    notes: list[str] = field(default_factory=list)

    @property
    def names_company(self) -> bool:
        """Does the board id carry the company's name? A careers page may link to a parent
        group's or a partner's board (Padok → `theodo`): verified, but to check by hand."""
        if not self.identifier:
            return False
        ident = re.sub(r"[^a-z0-9]", "", self.identifier.lower())
        words = [w for w in re.split(r"-", (slugs_for(self.company) or [""])[-1]) if len(w) > 2]
        compact = (slugs_for(self.company) or [""])[0]
        return bool(compact) and (compact in ident or any(w in ident for w in words))

    @property
    def guess_confirmed(self) -> bool | None:
        if self.status != VERIFIED or not self.guess:
            return None
        return self.guess == self.ats


# ---------------------------------------------------------------------- parsing

def slugs_for(name: str) -> list[str]:
    """`Dassault Systèmes` → [`dassaultsystemes`, `dassault-systemes`]; legal suffixes dropped."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    folded = re.sub(r"\(.*?\)", " ", folded)
    words = [w for w in re.split(r"[^a-z0-9]+", folded)
             if w and w not in {"group", "groupe", "sa", "sas", "se", "the"}]
    if not words:
        return []
    compact, hyphen = "".join(words), "-".join(words)
    return [compact] if compact == hyphen else [compact, hyphen]


def _workday_id(match: re.Match[str]) -> str:
    """`<host>/<tenant>/<site>` for both Workday URL forms."""
    if "myworkdaysite" in match.group(0).lower():
        wd, tenant, site = match.groups()
        return f"{wd.lower()}.myworkdaysite.com/{tenant.lower()}/{site}"
    tenant, wd, site = match.groups()
    return f"{tenant.lower()}.{wd.lower()}.myworkdayjobs.com/{tenant.lower()}/{site}"


def candidates_in(text: str, method: str) -> list[Candidate]:
    """Every public-ATS board named in a URL or an HTML page, first seen first, no repeats."""
    found: list[Candidate] = []
    for ats, pattern in _LINKS:
        for m in pattern.finditer(text):
            ident = _workday_id(m) if ats == "workday" else m.group(1)
            if ats != "workday":
                ident = ident.strip(".")
                if ident.lower() in _NOT_AN_ID:
                    continue
            elif re.fullmatch(r"[a-z]{2}([-_][a-z]{2})?", ident.rsplit("/", 1)[1].lower()):
                continue  # a bare locale (`/fr-FR`): the site name is missing
            cand = Candidate(ats, ident, method)
            if all((c.ats, c.identifier.lower()) != (ats, ident.lower()) for c in found):
                found.append(cand)
    return found


def platforms_in(text: str) -> list[str]:
    return [name for name, pattern in _PLATFORMS if pattern.search(text)]


# ---------------------------------------------------------------------- probing

class Detector:
    def __init__(
        self,
        http: HttpClient | None = None,
        page_http: HttpClient | None = None,
        per_host_interval: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http or HttpClient(max_retries=1, timeout_read=20.0)
        # The careers page may redirect (to its ATS, often); the JSON endpoints never need to.
        self._page_http = page_http or HttpClient(
            max_retries=1, timeout_read=20.0, follow_redirects=True
        )
        self._interval = per_host_interval
        self._sleep = sleep
        self._clock = clock
        self._last: dict[str, float] = {}
        self.requests = 0

    def close(self) -> None:
        self._http.close()
        self._page_http.close()

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        last = self._last.get(host)
        if last is not None:
            wait = self._interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()
        self.requests += 1

    def probe(self, ats: str, identifier: str) -> tuple[int | None, str | None]:
        """(postings, None) when the endpoint answers with a board, else (None, why)."""
        try:
            if ats == "workday":
                host, tenant, site = identifier.split("/", 2)
                url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
                self._throttle(url)
                resp = self._http.post(
                    url,
                    json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                    headers={"Accept": "application/json"},
                )
            else:
                url = {
                    "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs",
                    "lever": f"https://api.lever.co/v0/postings/{identifier}?mode=json",
                    "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{identifier}",
                    "smartrecruiters": (
                        f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings?limit=1"
                    ),
                }[ats]
                self._throttle(url)
                resp = self._http.get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # network, 5xx after retries: this candidate only
            return None, type(exc).__name__
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        try:
            body = resp.json()
        except ValueError:
            return None, "not JSON"
        count = _count(ats, body)
        if count is None:
            return None, "unexpected shape"
        return count, None

    def _page(self, url: str) -> tuple[str | None, str | None, str | None]:
        """(final URL, HTML, None) or (None, None, why). One GET, redirects followed."""
        try:
            self._throttle(url)
            resp = self._page_http.get(
                url, headers={"Accept": "text/html,application/xhtml+xml"}
            )
        except Exception as exc:
            return None, None, type(exc).__name__
        if resp.status_code != 200:
            return str(resp.url), None, f"HTTP {resp.status_code}"
        kind = resp.headers.get("content-type", "")
        text = resp.text[:_PAGE_LIMIT] if "html" in kind or not kind else ""
        return str(resp.url), text, None

    def _first_verified(
        self, cands: Iterable[Candidate], result: Detection, tried: set[tuple[str, str]],
        limit: int,
    ) -> bool:
        for cand in cands:
            key = (cand.ats, cand.identifier.lower())
            if key in tried:
                continue
            if len(tried) >= limit:
                result.notes.append("probe limit reached")
                return False
            tried.add(key)
            count, why = self.probe(cand.ats, cand.identifier)
            if count:
                result.status, result.ats, result.identifier = VERIFIED, cand.ats, cand.identifier
                result.postings, result.method = count, cand.method
                return True
            reason = why or "0 postings"
            result.notes.append(f"{cand.method} {cand.ats}:{cand.identifier} → {reason}")
        return False

    def detect(self, company: TargetCompany, max_probes: int = 8) -> Detection:
        result = Detection(company=company.name, status=NOT_FOUND, guess=company.ats_guess)
        tried: set[tuple[str, str]] = set()
        url = company.careers_url or ""

        # 1. The URL names its ATS.
        if self._first_verified(candidates_in(url, "url"), result, tried, max_probes):
            return result

        # 2. The careers page links to it, or redirects to it.
        platforms = platforms_in(url)
        page_ok = False
        if url:
            final, html, why = self._page(url)
            if why:
                result.notes.append(f"page → {why}")
            else:
                page_ok = True
                text = f"{final}\n{html or ''}"
                if self._first_verified(candidates_in(text, "page"), result, tried, max_probes):
                    return result
                platforms += [p for p in platforms_in(text) if p not in platforms]

        # 3. The name as a slug: the guessed ATS first, Workday never (it needs a site).
        order = [a for a in SLUG_ATS if a == company.ats_guess] + [
            a for a in SLUG_ATS if a != company.ats_guess
        ]
        slugs = slugs_for(company.name)
        guesses = [Candidate(a, s, "slug")
                   for a in order for s in slugs[: 2 if a == order[0] else 1]]
        if self._first_verified(guesses, result, tried, max_probes):
            return result

        if platforms or page_ok:
            result.status = CUSTOM
            result.platform = platforms[0] if platforms else None
        return result


def _count(ats: str, body: object) -> int | None:
    """Postings on the board, or None when the body is not that ATS's board."""
    if ats == "lever":
        return len(body) if isinstance(body, list) else None
    if not isinstance(body, dict):
        return None
    if ats in ("greenhouse", "ashby"):
        jobs = body.get("jobs")
        return len(jobs) if isinstance(jobs, list) else None
    if ats == "smartrecruiters":
        total = body.get("totalFound")
        return total if isinstance(total, int) and isinstance(body.get("content"), list) else None
    if ats == "workday":
        total = body.get("total")
        listed = isinstance(body.get("jobPostings"), list)
        return total if isinstance(total, int) and listed else None
    return None


def detect_all(
    companies: Iterable[TargetCompany], detector: Detector,
    progress: Callable[[int, Detection], None] | None = None,
) -> list[Detection]:
    results = []
    for i, company in enumerate(companies, 1):
        found = detector.detect(company)
        logger.info("%s: %s %s", company.name, found.status, found.ats or found.platform or "")
        results.append(found)
        if progress:
            progress(i, found)
    return results


__all__ = [
    "CUSTOM", "NOT_FOUND", "PUBLIC_ATS", "VERIFIED", "Candidate", "Detection", "Detector",
    "candidates_in", "detect_all", "platforms_in", "slugs_for",
]
