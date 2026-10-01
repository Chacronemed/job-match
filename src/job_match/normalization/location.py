from job_match.normalization.text import normalize_text


def normalize_location(location: str) -> str:
    """Fold accents, lowercase, collapse whitespace."""
    return normalize_text(location)
