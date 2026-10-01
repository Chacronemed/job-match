import hashlib

from job_match.domain.models import Job
from job_match.normalization.company import normalize_company
from job_match.normalization.location import normalize_location
from job_match.normalization.text import normalize_text
from job_match.normalization.title import normalize_title


def compute_fingerprint(job: Job) -> str:
    """SHA-256 of normalized company|title|location|contract|desc[:500]."""
    parts = [
        normalize_company(job.company),
        normalize_title(job.title),
        normalize_location(job.location),
        str(job.contract_type),
        normalize_text(job.description)[:500],
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
