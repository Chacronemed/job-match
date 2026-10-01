from job_match.config.schema import Profile
from job_match.domain.models import (
    EligibilityResult,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RejectionReason,
)


def evaluate(job: Job, requirement: ExperienceRequirement, profile: Profile) -> EligibilityResult:
    reasons: list[RejectionReason] = []

    # 1. Experience hard gate — UNKNOWN and NOT_MENTIONED stay eligible
    if (
        requirement.status == ExperienceStatus.ELIGIBLE
        and requirement.min_years is not None
        and requirement.min_years > profile.candidate.experience_years
    ):
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
