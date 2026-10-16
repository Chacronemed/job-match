import re

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
