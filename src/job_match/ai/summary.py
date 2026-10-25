"""The anonymous skills summary sent to the model with every offer (ADR 0016 §6).

Generated from the profile, it carries skills with a weight band, negative skills, the
years of experience, the accepted contract types and whether the search is national or
restricted. Never a name, an email, a phone number, a city, the department codes, the
search keywords or anything else from the profile: `KEYS` is the whole allow-list, and a
test checks that nothing personal can pass through `skills_summary`.
"""
from __future__ import annotations

from job_match.config.schema import Profile

KEYS: tuple[str, ...] = (
    "contract_types", "experience_years", "mobility", "negative", "preferred",
)
STRONG_WEIGHT = 3  # a preferred skill at this weight or more is "fort", below is "moyen"
MOBILITY_NATIONAL = "france"
MOBILITY_RESTRICTED = "departements"  # some departments, which ones is not said


def skills_summary(profile: Profile) -> dict:
    preferred = sorted(
        ({"name": s.name.strip().lower(), "band": "fort" if s.weight >= STRONG_WEIGHT else "moyen"}
         for s in profile.skills.preferred if s.name.strip()),
        key=lambda s: (s["band"] != "fort", s["name"]),
    )
    negative = sorted(
        ({"name": s.name.strip().lower()} for s in profile.skills.negative if s.name.strip()),
        key=lambda s: s["name"],
    )
    years = profile.candidate.experience_years
    return {
        "contract_types": sorted(c.value for c in profile.filters.contract_types),
        "experience_years": int(years) if float(years).is_integer() else float(years),
        "mobility": MOBILITY_NATIONAL if profile.ft_search.national else MOBILITY_RESTRICTED,
        "negative": negative,
        "preferred": preferred,
    }
