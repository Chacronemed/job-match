from job_match.config.schema import Profile, RelevanceConfig, Settings
from job_match.domain.models import (
    ContractType,
    EligibilityResult,
    ExperienceRequirement,
    Job,
    RejectionReason,
)
from job_match.experience.parser import infer_seniority_min
from job_match.normalization.location import (
    departments_for,
    french_location,
    normalize_location,
)
from job_match.normalization.skills import matches_skill, title_keyword, title_term


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


def title_is_a_dev_role(title: str, relevance: RelevanceConfig) -> bool:
    """True when the TITLE says developer and never says the role we want.

    The description is not consulted on purpose. "Développeur(se) - Java Angular & Cloud"
    matches kubernetes, cloud and docker in its body text and scored 74 as a strong match,
    but the title decides what the job is. A dev_title plus an explicit role_title is
    fine ("Ingénieur DevOps Java"), because then the role is stated.

    "cloud" is deliberately absent from role_titles: only "cloud engineer" and
    "ingénieur cloud" count, so "Développeur Cloud" stays rejected.
    """
    if not relevance.dev_titles:
        return False  # veto off
    if title_term(title, relevance.dev_titles) is None:
        return False
    return title_term(title, relevance.role_titles) is None


def evaluate(
    job: Job,
    requirement: ExperienceRequirement,
    profile: Profile,
    settings: Settings | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> EligibilityResult:
    reasons: list[RejectionReason] = []

    # 0. Relevance: not a target role at all (e.g. "Réceptionniste en hôtellerie"), or a
    # developer role wearing our keywords in its description. The title veto runs first
    # and overrides the skill match — that is the point of it.
    if settings and (
        title_is_a_dev_role(job.title, settings.relevance)
        or not is_relevant(job, profile, settings.relevance.target_title_keywords, aliases)
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

    # 2. Contract type. UNKNOWN is "not stated", not "wrong": Jooble and Adzuna often
    # ship no usable contract field, and we never reject on something we could not read.
    allowed = profile.filters.contract_types
    if allowed and job.contract_type is not ContractType.UNKNOWN:
        if job.contract_type not in allowed:
            reasons.append(RejectionReason.CONTRACT)

    # 3. Location. Always checked now: with a national scope there is no department list
    # to opt in with, and a foreign offer would otherwise sail through.
    if not location_allowed(job.location, profile):
        reasons.append(RejectionReason.LOCATION)

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))


def location_allowed(location: str, profile: Profile) -> bool:
    """Accept remote, a configured city name, and whatever the search scope covers.

    The scope is `profile.ft_search.departments`, the parsed form of the profile's single
    `location_scope` key, so there is no second location list to keep in sync:

    * national scope (empty list) -> every French location passes and only a location we
      can see is abroad is rejected ("Bruxelles, Belgique", "99 - ALLEMAGNE", "London");
    * restricted scope -> the location must resolve to one of those departments.

    Source-independent by design: France Travail sends "92 - Nanterre", Jooble and Adzuna
    send "Nanterre" or "Ile-de-France", and `departments_for` resolves all three. In both
    modes a location that resolves to nothing is kept: we never reject on a location we
    could not read.
    """
    job_loc = normalize_location(location)
    if "remote" in job_loc or "teletravail" in job_loc:
        return True
    if any(normalize_location(loc) in job_loc for loc in profile.filters.locations):
        return True

    if profile.ft_search.national:
        return french_location(location) is not False

    candidates = departments_for(location)
    if not candidates:
        return True  # unknown / unparseable -> keep the job
    return bool(candidates & {str(d).upper() for d in profile.ft_search.departments})
