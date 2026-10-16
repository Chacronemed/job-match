import re

from job_match.normalization.fr_geo import (
    CITY_DEPARTMENT,
    DEPARTMENT_NAMES,
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
