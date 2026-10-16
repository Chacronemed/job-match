from job_match.config.schema import Profile, Settings
from job_match.domain.models import (
    EligibilityResult,
    ExperienceRequirement,
    Job,
    RejectionReason,
)
from job_match.experience.parser import infer_seniority_min
from job_match.normalization.location import normalize_location, parse_department
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

    # 3. Location
    locs = profile.filters.locations
    if locs and not location_allowed(job.location, profile):
        reasons.append(RejectionReason.LOCATION)

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))


def location_allowed(location: str, profile: Profile) -> bool:
    """Accept remote, a configured city name, or a department we actually queried.

    The department codes come from `ft_search.departments` — the same list that drives the
    API fan-out, so there is no second location list to keep in sync. A location with no
    readable "NN - City" prefix is kept: we never reject on a location we could not parse.
    """
    job_loc = normalize_location(location)
    if "remote" in job_loc:
        return True
    if any(normalize_location(loc) in job_loc for loc in profile.filters.locations):
        return True
    dept = parse_department(location)
    if dept is None:
        return True  # unknown / unparseable → keep the job
    return dept in {str(d).upper() for d in profile.ft_search.departments}
