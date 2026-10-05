from job_match.config.schema import Profile, Settings
from job_match.domain.models import (
    EligibilityResult,
    ExperienceRequirement,
    Job,
    RejectionReason,
)
from job_match.experience.parser import infer_seniority_min
from job_match.normalization.skills import matches_skill, title_keyword


def is_relevant(
    job: Job,
    profile: Profile,
    target_title_keywords: list[str],
    aliases: dict[str, list[str]] | None = None,
) -> bool:
    """A job is a target role if it matches >=1 preferred skill (title or description,
    aliases included) OR its title contains a target-role keyword. Empty keywords = gate off."""
    if not target_title_keywords:
        return True
    if title_keyword(job.title, target_title_keywords):
        return True
    text = f"{job.title} {job.description}"
    return any(matches_skill(text, s.name, aliases or {}) for s in profile.skills.preferred)


def evaluate(
    job: Job,
    requirement: ExperienceRequirement,
    profile: Profile,
    settings: Settings | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> EligibilityResult:
    reasons: list[RejectionReason] = []

    # 0. Relevance: not a target role at all (e.g. "Réceptionniste en hôtellerie")
    if settings and not is_relevant(
        job, profile, settings.relevance.target_title_keywords, aliases
    ):
        reasons.append(RejectionReason.NOT_RELEVANT)

    # 1. Experience hard gate
    # Seniority keywords (title or description) set a minimum when no explicit number exists.
    # An explicit number in the text always wins over the keyword minimum.
    seniority_min: float | None = None
    if settings and settings.seniority_min_years:
        s = infer_seniority_min(job.title, job.description, settings.seniority_min_years)
        if s is not None:
            seniority_min = float(s)

    if requirement.min_years is not None:
        effective_min: float | None = requirement.min_years  # explicit wins
    else:
        effective_min = seniority_min  # keyword fallback (may be 0 = no restriction)

    if effective_min is not None and effective_min > profile.candidate.experience_years:
        reasons.append(RejectionReason.EXPERIENCE)

    # 2. Contract type
    allowed = profile.filters.contract_types
    if allowed and job.contract_type not in allowed:
        reasons.append(RejectionReason.CONTRACT)

    # 3. Location — "remote" anywhere in job.location always passes
    locs = profile.filters.locations
    if locs:
        job_loc = job.location.lower()
        if "remote" not in job_loc:
            if not any(loc.lower() in job_loc for loc in locs):
                reasons.append(RejectionReason.LOCATION)

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
