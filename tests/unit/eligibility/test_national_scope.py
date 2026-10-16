"""The location gate under `location_scope: france`.

One profile setting decides both what we query and what we accept. Nationally the gate has
no department list to match against, so it keeps every French location, keeps anything it
cannot read, and rejects only what it can see is abroad.
"""
import pytest

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    ScoringConfig,
    Skills,
)
from job_match.domain.models import ContractType, Job, RejectionReason, WorkplaceType
from job_match.eligibility.gate import evaluate, location_allowed
from job_match.experience.parser import parse as parse_experience


def _profile(departments: list[str] | None = None, locations: list[str] | None = None) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=5.0),
        skills=Skills(),
        filters=Filters(contract_types=[], locations=locations or []),
        ft_search=FTSearch(keywords=["devops"], departments=departments or []),
        scoring=ScoringConfig(),
    )


def _job(location: str) -> Job:
    from datetime import UTC, datetime
    return Job(
        source="france_travail",
        source_job_id="FT-1",
        title="Ingénieur DevOps",
        company="Acme",
        location=location,
        workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI,
        description="Kubernetes, Terraform, CI/CD.",
        url="https://example.com/1",
        collected_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# National scope accepts France, all of it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "location",
    [
        "92 - Nanterre",
        "13 - Marseille",       # outside the 14 departments we used to query
        "44 - Nantes",
        "67 - Strasbourg",
        "2B - Bastia",
        "972 - Fort-de-France",
        "Lyon",
        "Bretagne",
        "France",
        "Télétravail",
        "Remote (France)",
        "",                      # unreadable: kept, never rejected
        "Saint-Machin-sur-Glane",
    ],
)
def test_a_national_scope_accepts_french_and_unknown_locations(location):
    assert location_allowed(location, _profile()) is True


@pytest.mark.parametrize(
    "location",
    [
        "Bruxelles, Belgique",
        "99 - ALLEMAGNE",
        "London, UK",
        "Genève",
        "Luxembourg",
        "Montréal, Canada",
    ],
)
def test_a_national_scope_rejects_clearly_foreign_locations(location):
    assert location_allowed(location, _profile()) is False


# ---------------------------------------------------------------------------
# A restricted scope still behaves as before
# ---------------------------------------------------------------------------

def test_a_restricted_scope_accepts_its_departments():
    assert location_allowed("92 - Nanterre", _profile(departments=["75", "92"])) is True


def test_a_restricted_scope_rejects_the_others():
    assert location_allowed("13 - Marseille", _profile(departments=["75", "92"])) is False


def test_a_restricted_scope_keeps_an_unreadable_location():
    assert location_allowed("France", _profile(departments=["75"])) is True


def test_remote_passes_any_scope():
    assert location_allowed("Télétravail", _profile(departments=["75"])) is True


def test_a_configured_city_still_passes_a_restricted_scope():
    assert location_allowed("Nantes centre", _profile(departments=["75"], locations=["Nantes"]))


# ---------------------------------------------------------------------------
# End to end through the gate
# ---------------------------------------------------------------------------

def test_a_provincial_job_is_eligible_nationally():
    job = _job("31 - Toulouse")
    result = evaluate(job, parse_experience(job.description), _profile())

    assert result.eligible is True


def test_a_foreign_job_is_rejected_with_a_location_reason():
    job = _job("99 - BELGIQUE")
    result = evaluate(job, parse_experience(job.description), _profile())

    assert result.eligible is False
    assert RejectionReason.LOCATION in result.reasons


def test_the_same_job_was_rejected_by_the_old_department_scope():
    """Why this change exists: Toulouse used to be thrown away after we paid for it."""
    job = _job("31 - Toulouse")
    old = evaluate(job, parse_experience(job.description), _profile(departments=["75", "92"]))

    assert old.eligible is False
    assert RejectionReason.LOCATION in old.reasons
