import re

from job_match.normalization.fr_geo import (
    CITY_DEPARTMENT,
    DEPARTMENT_NAMES,
    FOREIGN_PLACES,
    FRENCH_DEPARTMENTS,
    REGION_DEPARTMENTS,
)
from job_match.normalization.text import normalize_text

# France Travail formats locations as "NN - City": "92 - Nanterre", "06 - Nice",
# "2A - Ajaccio", "971 - Fort-de-France". Anything else has no department code.
_DEPT_PREFIX_RE = re.compile(r"^\s*(\d{2,3}|2[ab])\s*-\s*\S", re.IGNORECASE)


def normalize_location(location: str) -> str:
    """Fold accents, lowercase, collapse whitespace."""
    return normalize_text(location)


def parse_department(location: str) -> str | None:
    """Department code from a "NN - City" location, or None when there is no such prefix.

    None means "unreadable", not "wrong": "Paris 15e", "France" and "" all return None.
    """
    match = _DEPT_PREFIX_RE.match(location or "")
    return match.group(1).upper() if match else None


def _place_table() -> list[tuple[str, re.Pattern[str], frozenset[str]]]:
    """Known place names → departments, longest name first.

    Longest first so "boulogne billancourt" (92) is tried before "boulogne sur mer" (62),
    and "saint quentin en yvelines" (78) before "saint quentin".
    """
    table: dict[str, frozenset[str]] = {}
    for name, dept in CITY_DEPARTMENT.items():
        table[normalize_text(name)] = frozenset({dept})
    for name, dept in DEPARTMENT_NAMES.items():
        table.setdefault(normalize_text(name), frozenset({dept}))
    for name, depts in REGION_DEPARTMENTS.items():
        table.setdefault(normalize_text(name), frozenset(depts))
    return [
        (key, re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)"), depts)
        for key, depts in sorted(table.items(), key=lambda kv: -len(kv[0]))
    ]


_PLACES = _place_table()


def departments_for(location: str) -> frozenset[str]:
    """Departments a location could be in. Empty means "we cannot tell".

    Three ways to resolve, in order of confidence:
      1. a "NN - City" prefix (France Travail) — exact;
      2. a known city or department name (Jooble, Adzuna) — exact;
      3. a region name — every department of that region.

    An empty result is the normal case for "France", "Télétravail" or a city we do not
    list, and callers must treat it as unknown, never as "wrong place".
    """
    prefix = parse_department(location)
    if prefix:
        return frozenset({prefix})

    normalized = normalize_location(location)
    if not normalized:
        return frozenset()

    found: set[str] = set()
    matched_spans: list[tuple[int, int]] = []
    for _key, pattern, depts in _PLACES:
        for match in pattern.finditer(normalized):
            span = match.span()
            # A longer name already covering this text wins: "boulogne sur mer" must not
            # also register the region hit inside it.
            if any(s <= span[0] and span[1] <= e for s, e in matched_spans):
                continue
            matched_spans.append(span)
            found |= depts
    return frozenset(found)


_FOREIGN = [
    re.compile(r"(?<!\w)" + re.escape(normalize_text(name)) + r"(?!\w)")
    for name in sorted(FOREIGN_PLACES, key=len, reverse=True)
]
_FRANCE = re.compile(r"(?<!\w)france(?!\w)")


def is_french_department(code: str) -> bool:
    """True for a real department or overseas code. France Travail says "99" for abroad."""
    return (code or "").strip().upper() in FRENCH_DEPARTMENTS


def department_of(location: str) -> str | None:
    """The single department a location resolves to, or None.

    None covers both "unreadable" and "ambiguous": a region name resolves to many
    departments, so it gets no single one. For run-summary breakdowns, not for gating.
    """
    candidates = departments_for(location)
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def french_location(location: str) -> bool | None:
    """Tri-state: True = clearly in France, False = clearly abroad, None = cannot tell.

    Used by the gate when the search scope is the whole country: there is no department
    list to compare against, so the only job we reject is one we can see is somewhere else.
    None is the normal answer for "", "Teletravail" or a town nobody listed, and the caller
    keeps those jobs.

    Foreign markers are checked first, so "Lille, Belgique" is abroad rather than Nord.
    """
    normalized = normalize_location(location)
    if not normalized:
        return None
    if any(pattern.search(normalized) for pattern in _FOREIGN):
        return False
    code = parse_department(location)
    if code:
        return is_french_department(code)
    if _FRANCE.search(normalized) or departments_for(location):
        return True
    return None


def block_location(location: str) -> str:
    """Dedup blocking key for a location: its department, or the normalized text.

    Two postings in different departments are different offers, so they must never be
    compared. When no single department resolves ("France", "Teletravail", a town nobody
    lists) the normalized text is the key: identical location strings still block together,
    and nothing else does.
    """
    return department_of(location) or normalize_location(location)
