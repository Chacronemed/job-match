from job_match.config.schema import Profile, Settings
from job_match.domain.models import (
    EXCLUDES_APPRENTICESHIP_NOTE,
    EligibilityResult,
    ExperienceRequirement,
    Job,
    ScoreResult,
    ScoringBreakdown,
    stretch_note,
)
from job_match.scoring.base import Scorer


class ScoringEngine:
    def __init__(self, scorers: list[Scorer]) -> None:
        self._scorers = scorers

    def score(
        self,
        job: Job,
        profile: Profile,
        settings: Settings,
        eligibility: EligibilityResult,
        experience: ExperienceRequirement,
    ) -> ScoringBreakdown:
        engines: dict[str, ScoreResult] = {}

        for scorer in self._scorers:
            try:
                result = scorer.score(job, profile, settings)
            except Exception:
                result = ScoreResult(engine=scorer.name, available=False)
            engines[scorer.name] = result

        available = [r for r in engines.values() if r.available and r.score is not None]

        primary: ScoreResult | None = None
        native = engines.get("native")
        if native is not None and native.available:
            primary = native
        elif available:
            primary = available[0]

        divergence: int | None = None
        if len(available) >= 2:
            scores = [r.score for r in available]
            divergence = max(scores) - min(scores)  # type: ignore[type-var]

        needs_review = (
            divergence is not None and divergence >= settings.divergence_threshold
        )

        # A stretch job says so first: the score is the same as for any eligible job, the
        # explanation is what tells the reader why it is in its own section.
        notes: tuple[str, ...] = ()
        if eligibility.stretch and eligibility.required_years is not None:
            notes = (
                stretch_note(eligibility.required_years, profile.candidate.experience_years),
            )
        if experience.excludes_apprenticeship:
            notes += (EXCLUDES_APPRENTICESHIP_NOTE,)

        # What the "why this job" panel shows about experience, fixed at scoring time.
        experience_detail = {
            "required_years": eligibility.required_years,
            "basis": str(eligibility.basis),
            "sentence": eligibility.basis_evidence,
            "excludes_apprenticeship": experience.excludes_apprenticeship,
        }

        if primary is not None:
            return ScoringBreakdown(
                eligible=eligibility.eligible,
                experience=experience.status,
                score=primary.score,
                positive_matches=primary.positive_matches,
                negative_matches=primary.negative_matches,
                missing_preferences=primary.missing_preferences,
                explanations=notes + tuple(primary.explanations),
                engines=engines,
                divergence=divergence,
                needs_review=needs_review,
                evidence=primary.evidence,
                weights=primary.weights,
                unlisted=primary.unlisted,
                experience_detail=experience_detail,
            )

        return ScoringBreakdown(
            eligible=eligibility.eligible,
            experience=experience.status,
            explanations=notes,
            engines=engines,
            divergence=divergence,
            needs_review=needs_review,
            experience_detail=experience_detail,
        )
