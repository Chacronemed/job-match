import re

from job_match.domain.models import ExperienceRequirement, ExperienceStatus
from job_match.normalization.numbers import WORD_NUMBERS as _WORD_NUMS

# Non-capturing alternation of written numbers
_W = "(?:" + "|".join(_WORD_NUMS) + ")"
# Capturing group: 1-2 digit integer OR written number with word boundaries
_NC = r"(\d{1,2}|\b" + _W + r"\b)"

# Strips company-founding year context ("fondée en 2018", "founded in 2010")
_FALSE_POSITIVE_RE = re.compile(
    r"(?:fond[eé]e?|cr[eé][eé]e?|[eé]tabli(?:e)?|founded|established)\s+(?:en\s+|in\s+)?\d{4}",
    re.IGNORECASE,
)

# Ambiguous phrases — checked only when no numeric match is found
_AMBIGUOUS_RE = re.compile(
    r"\b(?:premi[eè]re?\s+exp[eé]rience|premier\s+emploi|d[eé]butant"
    r"|junior|entry[\s-]level"
    r"|solid\s+experience|significant\s+experience"
    r"|proven\s+experience|extensive\s+experience)\b",
    re.IGNORECASE,
)

# Range: "2 à 5 ans", "2-5 years", "2 to 5 years"
_RANGE_RE = re.compile(
    r"(\d{1,2}|\b" + _W + r"\b)\s*(?:à|to|-)\s*(\d{1,2}|\b" + _W + r"\b)\s*(?:ans?|years?)",
    re.IGNORECASE,
)

# Explicit minimum: "au moins 3 ans", "at least 3 years", "minimum 3 years"
_MIN_EXPLICIT_RE = re.compile(
    r"(?:au\s+moins|minimum|au\s+minimum|at\s+least)\s+" + _NC + r"\s*(?:ans?|years?)",
    re.IGNORECASE,
)

# Plus notation: "3+ ans", "3+ years"
_MIN_PLUS_RE = re.compile(r"(\d{1,2})\s*\+\s*(?:ans?|years?)", re.IGNORECASE)

# Plain: "3 ans d'expérience", "3 years of experience", "deux ans d'expérience"
# NOTE: numbers at positions claimed by other patterns are skipped in parse()
_PLAIN_RE = re.compile(
    _NC + r"\s+(?:ans?|years?)"
    r"(?:\s+(?:d[''']?expérience|of\s+experience|expérience|experience))?",
    re.IGNORECASE,
)

# Maximum: "jusqu'à 2 ans", "up to 2 years", "moins de 2 ans", "less than 2 years"
_MAX_RE = re.compile(
    r"(?:jusqu[''']à|up\s+to|moins\s+de|less\s+than)\s+" + _NC + r"\s*(?:ans?|years?)",
    re.IGNORECASE,
)


def parse(text: str) -> ExperienceRequirement:
    if not text:
        return ExperienceRequirement(status=ExperienceStatus.NOT_MENTIONED)

    clean = _FALSE_POSITIVE_RE.sub("", text)

    # (min_years, max_years, evidence)
    candidates: list[tuple[float | None, float | None, str]] = []
    # Positions of number groups already claimed by a specific pattern;
    # prevents _PLAIN_RE from double-capturing numbers inside max phrases.
    claimed: set[int] = set()

    for m in _RANGE_RE.finditer(clean):
        lo = _to_num(m.group(1))
        hi = _to_num(m.group(2))
        if lo is not None and hi is not None:
            candidates.append((lo, hi, m.group(0)))
            claimed.add(m.start(1))
            claimed.add(m.start(2))

    for m in _MIN_EXPLICIT_RE.finditer(clean):
        val = _to_num(m.group(1))
        if val is not None:
            candidates.append((val, None, m.group(0)))
            claimed.add(m.start(1))

    for m in _MIN_PLUS_RE.finditer(clean):
        candidates.append((float(m.group(1)), None, m.group(0)))
        claimed.add(m.start(1))

    for m in _MAX_RE.finditer(clean):
        val = _to_num(m.group(1))
        if val is not None:
            candidates.append((None, val, m.group(0)))
            claimed.add(m.start(1))

    for m in _PLAIN_RE.finditer(clean):
        if m.start(1) in claimed:
            continue
        val = _to_num(m.group(1))
        if val is not None:
            candidates.append((val, None, m.group(0)))

    if not candidates:
        am = _AMBIGUOUS_RE.search(clean)
        if am:
            return ExperienceRequirement(status=ExperienceStatus.UNKNOWN, evidence=am.group(0))
        return ExperienceRequirement(status=ExperienceStatus.NOT_MENTIONED)

    # Smallest-minimum rule: pick the candidate with the lowest explicit min_years
    with_min = [(mn, mx, ev) for mn, mx, ev in candidates if mn is not None]
    if with_min:
        mn, mx, ev = min(with_min, key=lambda t: t[0])
        return ExperienceRequirement(
            status=ExperienceStatus.ELIGIBLE, min_years=mn, max_years=mx, evidence=ev
        )

    # Only max-only candidates
    _, mx, ev = min(
        ((mn, mx, ev) for mn, mx, ev in candidates if mx is not None),
        key=lambda t: t[1],  # type: ignore[arg-type]
    )
    return ExperienceRequirement(
        status=ExperienceStatus.ELIGIBLE, min_years=None, max_years=mx, evidence=ev
    )


def infer_seniority_min(title: str, description: str, seniority_map: dict[str, int]) -> int | None:
    """Return highest min_years implied by seniority keywords in title or description.

    Returns None when no keyword matches or the map is empty.
    An explicit numeric requirement from the parser always wins over this value.
    """
    if not seniority_map:
        return None
    text = f"{title} {description}"
    best: int | None = None
    for keyword, min_years in seniority_map.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", text, re.IGNORECASE):
            if best is None or min_years > best:
                best = min_years
    return best


def _to_num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return _WORD_NUMS.get(s.lower())
