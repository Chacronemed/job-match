"""Workday boards: what the `ats` source needs to call them as little as possible.

Since 2026-11-16 Workday's edge answers the project's client with an HTML « Security Check »
page (HTTP 429, no `Retry-After`): an anti-robot protection. It is never worked around (no
proxy or IP rotation, no headless browser, no browser-like headers). The source only makes
fewer calls (ADR 0020, amendment 2026-11-20, part 2):

- **a filtered search** instead of the whole French listing: one `searchText` call per
  keyword (Workday reads several words as AND, measured 2026-11-20), the France facet applied,
  one page of 20 each;
- **a detail call only for a posting worth it**: its title passes the title filter, it is not
  stored yet, the freshest first (`postedOn`);
- **a cap of calls per tenant and run**, every request counted, retries included;
- **a frequency per tenant**: read every `frequency_days` days, the tenants spread over the
  days by their position in config/ats_boards.yaml, with no state to keep;
- **a security check stops the tenant at once** for the run: no retry, no further call.

This module holds the pure parts (schedule, statuses, facets, ids); `AtsBoardSource`
(ats.py) makes the calls.
"""
import re
from datetime import date
from typing import Any

import httpx

from job_match.normalization.location import french_location

COUNTRY = "france"  # the country facet value's descriptor, case-insensitive
DOMAIN = ".myworkdayjobs.com"  # every tenant's host: one shared queue
PAGE = 20  # Workday refuses a larger `limit`

# What happened to a board this run, as the run summary shows it.
OK = "ok"            # read
CAPPED = "capped"    # read, then stopped at the call cap: details or closure probes left out
SKIPPED = "skipped"  # not its day (frequency): no call at all
BLOCKED = "blocked"  # the edge served its security check: stopped at once, no retry
ERROR = "error"      # anything else: unreachable, a wrong site name, no France facet
STATUS_TEXT = {
    OK: "OK",
    CAPPED: "OK, plafond d'appels atteint",
    SKIPPED: "sauté par fréquence",
    BLOCKED: "bloqué anti-robot",
    ERROR: "erreur",
}


# ---------------------------------------------------------------------- schedule

def due_in_days(index: int, frequency_days: int, today: date) -> int:
    """Days until the board at position `index` (among the Workday boards, file order) is
    read: 0 means today. Board `i` owns day `i % frequency_days` of every period, so eleven
    boards on a weekly frequency are read two a day at most, and a board always keeps its day.
    Stateless on purpose: a missed run costs that board one period, nothing to repair."""
    if frequency_days <= 1:
        return 0
    return (index - today.toordinal()) % frequency_days


# ---------------------------------------------------------------------- answers

def is_security_check(resp: httpx.Response) -> bool:
    """The edge's HTML « Security Check » page, served with a 429 (and seen as a 403 on
    other sites of the same edge): an anti-robot answer, not a quota."""
    return resp.status_code in (403, 429) and "html" in resp.headers.get(
        "Content-Type", "").lower()


def failure_reason(resp: httpx.Response) -> str:
    """What a failed answer was, for the log."""
    if is_security_check(resp):
        return f"HTTP {resp.status_code} (security check page)"
    return f"HTTP {resp.status_code}"


# ---------------------------------------------------------------------- facets

def country_facet(facets: Any) -> tuple[str, str | None] | None:
    """(facet parameter, France value id or None) of the first country facet, nested
    groups included (`locationMainGroup` → `locationCountry`); None without one."""
    for facet in facets or []:
        if not isinstance(facet, dict):
            continue
        values = facet.get("values") or []
        if values and isinstance(values[0], dict) and "facetParameter" in values[0]:
            found = country_facet(values)
            if found is not None:
                return found
            continue
        param = str(facet.get("facetParameter") or "")
        if "country" not in param.lower():
            continue
        france = next((v.get("id") for v in values if isinstance(v, dict)
                       and str(v.get("descriptor") or "").strip().lower() == COUNTRY
                       and v.get("id")), None)
        return param, (str(france) if france else None)
    return None


def france_facet(facets: Any) -> tuple[str, list[str]] | None:
    """(facet parameter, the value ids that mean France), or None when the board cannot
    be filtered. The country facet when there is one; else the `locations` facet, keeping
    the places `french_location` reads as French (Euronext lists cities only: "Paris").
    An empty list is a facet without any French value: no French posting."""
    country = country_facet(facets)
    if country is not None:
        param, value = country
        return param, ([value] if value else [])
    places = facet_values(facets, "locations")
    if places is None:
        return None
    return "locations", [
        str(v["id"]) for v in places if isinstance(v, dict) and v.get("id")
        and french_location(str(v.get("descriptor") or "")) is True
    ]


def facet_values(facets: Any, parameter: str) -> list | None:
    """The values of the facet named `parameter`, nested groups included; None without it."""
    for facet in facets or []:
        if not isinstance(facet, dict):
            continue
        values = facet.get("values") or []
        if facet.get("facetParameter") == parameter:
            return values
        if values and isinstance(values[0], dict) and "facetParameter" in values[0]:
            found = facet_values(values, parameter)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------- postings

def posting_id(external_path: str) -> str:
    """`/job/Brest/Ingenieur-CFD_R0347114-1` → `R0347114-1`: the requisition id Workday
    ends every posting path with. A path without one keeps its last segment."""
    tail = external_path.rstrip("/").rsplit("/", 1)[-1]
    ident = tail.rsplit("_", 1)[-1] if "_" in tail else tail
    cleaned = "".join(ch for ch in ident if ch.isalnum() or ch in "-.")
    return cleaned[:100] or "unknown"


_DAYS_AGO = re.compile(r"(\d+)\s*(\+)?\s*day", re.IGNORECASE)
UNKNOWN_AGE = 15  # a `postedOn` that cannot be read: between a fresh and an old posting


def posted_days(posted_on: Any) -> int:
    """`postedOn` as days: "Posted Today" 0, "Posted Yesterday" 1, "Posted 3 Days Ago" 3,
    "Posted 30+ Days Ago" 31. A search answers by relevance, not by date, so the detail
    calls a tenant is allowed go to the freshest postings first."""
    text = str(posted_on or "").lower()
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    match = _DAYS_AGO.search(text)
    if match:
        return int(match.group(1)) + (1 if match.group(2) else 0)
    return UNKNOWN_AGE


__all__ = [
    "BLOCKED", "CAPPED", "COUNTRY", "DOMAIN", "ERROR", "OK", "PAGE", "SKIPPED",
    "STATUS_TEXT", "country_facet", "due_in_days", "facet_values", "failure_reason",
    "france_facet", "is_security_check", "posted_days", "posting_id",
]
