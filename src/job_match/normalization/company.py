import re

from job_match.normalization.text import normalize_text

_LEGAL_SUFFIXES = re.compile(
    r"\b(sas|sa|sarl|sasu|srl|gmbh|inc|ltd|llc|corp|bv|nv|ag|plc|oy|ab|spa)\b"
)


def normalize_company(name: str) -> str:
    """Strip legal suffixes, fold accents, lowercase."""
    # Collapse dotted acronyms (S.A.S. → SAS) before normalization
    name = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", "", name)
    n = normalize_text(name)
    n = _LEGAL_SUFFIXES.sub("", n)
    return re.sub(r"\s+", " ", n).strip()
