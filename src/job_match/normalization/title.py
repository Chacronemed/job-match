import re

from job_match.normalization.text import normalize_text

# After normalize_text, punctuation is replaced by spaces:
#   H/F  → h f,  (H/F) → h f,  M/W/D → m w d
_NOISE = re.compile(
    r"\b(h f|f h|hf|fh|m f|f m|m w d|w m d|cdi|cdd|stage|alternance|interim)\b"
)


def normalize_title(title: str) -> str:
    """Remove gender markers, contract noise; fold and lowercase."""
    n = normalize_text(title)
    n = _NOISE.sub("", n)
    return re.sub(r"\s+", " ", n).strip()
