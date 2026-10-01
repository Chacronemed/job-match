from dataclasses import dataclass

from rapidfuzz.fuzz import token_set_ratio

from job_match.config.schema import Settings
from job_match.domain.models import Job
from job_match.normalization.text import normalize_text
from job_match.normalization.title import normalize_title


@dataclass(frozen=True)
class DedupResult:
    is_duplicate: bool
    canonical_id: int | None = None
    reason: str | None = None  # 'exact_fingerprint' | 'fuzzy'
    similarity: float | None = None


class DedupEngine:
    def __init__(self, settings: Settings) -> None:
        # rapidfuzz returns 0–100; thresholds in settings are 0.0–1.0
        self._t_title = settings.fuzzy_title_threshold * 100
        self._t_desc = settings.fuzzy_desc_threshold * 100

    def check(
        self,
        job: Job,
        exact_candidates: list[Job],
        fuzzy_candidates: list[Job],
    ) -> DedupResult:
        """Check job against existing DB candidates.

        exact_candidates: jobs with the same fingerprint
        fuzzy_candidates: jobs in the same (company_normalized, contract_type) block
        Both lists contain only already-saved rows (have .id set).
        """
        for c in exact_candidates:
            return DedupResult(
                is_duplicate=True,
                canonical_id=c.id,
                reason="exact_fingerprint",
                similarity=1.0,
            )

        job_fp = job.fingerprint or ""
        title_n = normalize_title(job.title)
        desc_n = normalize_text(job.description)[:1000]

        for c in fuzzy_candidates:
            if c.fingerprint and c.fingerprint == job_fp:
                continue  # would be exact; already handled above
            t_sim = token_set_ratio(title_n, normalize_title(c.title))
            d_sim = token_set_ratio(desc_n, normalize_text(c.description)[:1000])
            if t_sim >= self._t_title and d_sim >= self._t_desc:
                return DedupResult(
                    is_duplicate=True,
                    canonical_id=c.id,
                    reason="fuzzy",
                    similarity=round((t_sim + d_sim) / 200.0, 3),
                )

        return DedupResult(is_duplicate=False)
