import functools
import importlib.resources
import re

from job_match.normalization.fr_geo import (
    DEPARTMENT_NAMES,
    EXTRA_PLACES,
    FOREIGN_PLACES,
    FRENCH_DEPARTMENTS,
    REGION_DEPARTMENTS,
    US_STATE_CODES,
)
from job_match.normalization.text import normalize_text

# France Travail formats locations as "NN - City": "92 - Nanterre", "06 - Nice",
# "2A - Ajaccio", "971 - Fort-de-France". Anything else has no department code.
_DEPT_PREFIX_RE = re.compile(r"^\s*(\d{2,3}|2[ab])\s*-\s*\S", re.IGNORECASE)
# "Bethpage, NY", "Austin, TX, USA": a two-letter state after a comma, at the end. On the raw
# string, uppercase only, so "Paris, LA DEFENSE" is not Louisiana.
_US_STYLE_RE = re.compile(
    r",\s*([A-Z]{2})(?:\s*,?\s*(?:USA|U\.S\.A\.|US|United States))?\s*\.?\s*$"
)
_POSTAL_RE = re.compile(r"^\d{5}$")
_FRANCE = re.compile(r"(?<!\w)france(?!\w)")

_COMMUNES_FILE = "fr_communes.tsv"
Places = dict[str, frozenset[str] | None]  # name -> departments, None = clearly abroad


def normalize_location(location: str) -> str:
    """Fold accents, lowercase, collapse whitespace."""
    return normalize_text(location)


def parse_department(location: str) -> str | None:
    """Department code from a "NN - City" location, or None when there is no such prefix.

    None means "unreadable", not "wrong": "Paris 15e", "France" and "" all return None.
    """
    match = _DEPT_PREFIX_RE.match(location or "")
    return match.group(1).upper() if match else None


def _load_communes() -> dict[str, set[str]]:
    """The official communes list, shipped as package data: normalized name -> departments.

    Built by `scripts/build_fr_communes.py` from geo.api.gouv.fr. A name that exists in
    several departments ("Saint-Denis": 93 and 974) keeps all of them.
    """
    text = importlib.resources.files(__package__).joinpath(_COMMUNES_FILE).read_text("ascii")
    communes: dict[str, set[str]] = {}
    for line in text.splitlines():
        name, _sep, dept = line.partition("\t")
        if name and dept:
            communes.setdefault(name, set()).add(dept)
    return communes


@functools.lru_cache(maxsize=1)
def _places() -> tuple[Places, int]:
    """Every name we can resolve, and the longest one in words.

    First writer wins, in order of confidence: a region ("Bretagne" is the region, not the
    two villages of that name), a department name, a business district, then the explicit
    foreign markers ("Montréal" is Canada before it is a village in the Aude), then the
    communes. Loaded lazily: `--help` never pays for 35k towns.
    """
    table: Places = {}
    for name, depts in REGION_DEPARTMENTS.items():
        table.setdefault(normalize_text(name), frozenset(depts))
    for name, dept in DEPARTMENT_NAMES.items():
        table.setdefault(normalize_text(name), frozenset({dept}))
    for name, dept in EXTRA_PLACES.items():
        table.setdefault(normalize_text(name), frozenset({dept}))
    for name in FOREIGN_PLACES:
        table.setdefault(normalize_text(name), None)
    for name, depts in _load_communes().items():
        table.setdefault(name, frozenset(depts))
    return table, max(len(name.split()) for name in table)


def _postal_department(token: str) -> str | None:
    """A five-digit French postal code -> its department, or None."""
    if not _POSTAL_RE.match(token):
        return None
    if token.startswith("20"):  # Corsica: 2A below Bastia's 20200, 2B from there
        code = "2A" if int(token) < 20200 else "2B"
    elif token.startswith(("97", "98")):
        code = token[:3]
    else:
        code = token[:2]
    return code if code in FRENCH_DEPARTMENTS else None


def _scan(normalized: str) -> tuple[frozenset[str], bool]:
    """Departments named in a normalized location, and whether a foreign marker is there.

    Greedy, longest name first, left to right: "porto vecchio" (2A) is consumed whole, so
    the "porto" marker inside it never fires, and "boulogne billancourt" is never read as
    Boulogne plus something. A name under three letters ("Y", "Eu", "Oz") only counts when it
    is the whole location, so a stray token never resolves to a village.
    """
    table, max_words = _places()
    tokens = normalized.split()
    found: set[str] = set()
    foreign = False
    i = 0
    while i < len(tokens):
        for n in range(min(max_words, len(tokens) - i), 0, -1):
            key = " ".join(tokens[i:i + n])
            if key not in table or (len(key) < 3 and len(tokens) > 1):
                continue
            hit = table[key]
            if hit is None:
                foreign = True
            else:
                found |= hit
            i += n
            break
        else:
            if dept := _postal_department(tokens[i]):
                found.add(dept)
            i += 1
    return frozenset(found), foreign


def _us_style(location: str) -> bool:
    """"City, ST" with a US state or Canadian province code."""
    match = _US_STYLE_RE.search(location or "")
    return bool(match) and match.group(1) in US_STATE_CODES


def departments_for(location: str) -> frozenset[str]:
    """Departments a location could be in. Empty means "we cannot tell", or "abroad".

    Three ways to resolve, in order of confidence:
      1. a "NN - City" prefix (France Travail) — exact;
      2. a commune, department or business-district name, or a postal code (Jooble, Adzuna);
      3. a region name — every department of that region.

    A foreign marker empties the answer ("Lille, Belgique" is Belgium, not Nord, and
    "Saint-Louis, MO" is Missouri, not the Haut-Rhin). An empty
    result is also the normal case for "France", "Télétravail" or a place nobody lists, and
    callers that need the difference ask `french_location`.
    """
    prefix = parse_department(location)
    if prefix:
        return frozenset({prefix})

    normalized = normalize_location(location)
    if not normalized or _us_style(location):
        return frozenset()
    found, foreign = _scan(normalized)
    return frozenset() if foreign else found


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

    True needs positive evidence: a French department prefix, a commune, department, region
    or district name, a postal code, or the word "France". False is a "City, ST" US format,
    a "99 - COUNTRY" prefix or a foreign marker, and the marker wins over a French town in
    the same string ("Lille, Belgique" is abroad). None is "", "Télétravail", "Siège social"
    or a town nobody lists; what the caller does with None depends on the source.
    """
    normalized = normalize_location(location)
    if not normalized:
        return None
    if _us_style(location):
        return False
    code = parse_department(location)
    if code:
        return is_french_department(code)
    found, foreign = _scan(normalized)
    if foreign:
        return False
    if found or _FRANCE.search(normalized):
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


def same_block_location(key: str, other: str) -> bool:
    """Whether two blocking keys can describe the same place.

    Two real departments are two places: 59 is not 78. But a key that is not a department
    code ("france", "teletravail", a town nobody lists) means "we cannot tell", and unknown
    never splits a block here, exactly as it never rejects a job in the gate. Jooble often
    says only "France" where France Travail says "92 - Nanterre", and those two postings
    still have to be comparable.
    """
    if key == other:
        return True
    return not (is_french_department(key) and is_french_department(other))
