"""The location gate under `location_scope: france`.

One profile setting decides both what we query and what we accept. Nationally the gate has
no department list to match against, so it keeps every French location and rejects the
rest. "The rest" depends on the source: France Travail is French unless it says 99, while
Jooble and Adzuna index the whole world, so there an unreadable location is rejected too.
"""
from dataclasses import replace

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

FT = "france_travail"
JOOBLE = "jooble"


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
    ],
)
@pytest.mark.parametrize("source", [FT, JOOBLE])
def test_a_national_scope_accepts_french_locations_from_any_source(location, source):
    assert location_allowed(location, _profile(), source=source) is True


@pytest.mark.parametrize(
    "location",
    [
        "Nanterre",                       # a commune
        "Châteauneuf-d'Ille-et-Vilaine",  # one nobody would hand-list
        "Lyon 1er Arrondissement",        # a municipal arrondissement
        "Rennes, France",
        "Porto-Vecchio",                  # "porto" inside a Corsican town is not Portugal
        "75008 Paris",                    # postal code
        "Saint-Quentin-en-Yvelines",      # a business district, not a commune
        "Télétravail",
    ],
)
def test_a_jooble_job_in_a_french_town_is_kept(location):
    assert location_allowed(location, _profile(), source=JOOBLE) is True


@pytest.mark.parametrize(
    "location",
    [
        "Bruxelles, Belgique",
        "99 - ALLEMAGNE",
        "London, UK",
        "Genève",
        "Luxembourg",
        "Montréal, Canada",
        "Bethpage, NY",          # US "City, ST"
        "Washington DC",
        "Arlington, VA",
        "Austin, TX, USA",
        "Saint-Louis, MO",       # a French commune name, a US state
    ],
)
@pytest.mark.parametrize("source", [FT, JOOBLE])
def test_a_national_scope_rejects_clearly_foreign_locations(location, source):
    assert location_allowed(location, _profile(), source=source) is False


UNREADABLE = ["", "   ", "Saint-Machin-sur-Glane", "Siège social", "Bethpage"]


@pytest.mark.parametrize("location", UNREADABLE)
def test_an_unreadable_location_is_kept_from_france_travail(location):
    """France Travail is French by construction: only the abroad code 99 says otherwise."""
    assert location_allowed(location, _profile(), source=FT) is True


@pytest.mark.parametrize("location", UNREADABLE)
def test_an_unreadable_location_is_rejected_from_a_worldwide_index(location):
    """Jooble and Adzuna index the whole world: no positive French evidence, no job."""
    assert location_allowed(location, _profile(), source=JOOBLE) is False


# ---------------------------------------------------------------------------
# A restricted scope still behaves as before
# ---------------------------------------------------------------------------

def test_a_restricted_scope_accepts_its_departments():
    assert location_allowed("92 - Nanterre", _profile(departments=["75", "92"])) is True


def test_a_restricted_scope_rejects_the_others():
    assert location_allowed("13 - Marseille", _profile(departments=["75", "92"])) is False


def test_a_restricted_scope_keeps_an_unreadable_location():
    assert location_allowed("France", _profile(departments=["75"])) is True
    assert location_allowed("Saint-Machin-sur-Glane", _profile(departments=["75"])) is True


def test_a_restricted_scope_rejects_a_foreign_location_even_with_a_french_town_in_it():
    assert location_allowed("Lille, Belgique", _profile(departments=["59"])) is False
    assert location_allowed("Zurich", _profile(departments=["75"])) is False


def test_a_restricted_scope_still_filters_france_travail_by_department():
    assert location_allowed("31 - Toulouse", _profile(departments=["75"]), source=FT) is False
    assert location_allowed("75 - Paris", _profile(departments=["75"]), source=FT) is True


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


def test_a_jooble_job_in_the_us_is_rejected_with_a_location_reason():
    job = replace(_job("Bethpage, NY"), source="jooble")
    result = evaluate(job, parse_experience(job.description), _profile())

    assert result.eligible is False
    assert RejectionReason.LOCATION in result.reasons


def test_a_jooble_job_with_no_location_is_rejected_but_a_france_travail_one_is_kept():
    jooble = replace(_job(""), source="jooble")
    ft = _job("")
    assert RejectionReason.LOCATION in evaluate(jooble, parse_experience(""), _profile()).reasons
    assert evaluate(ft, parse_experience(""), _profile()).eligible is True


def test_the_same_job_was_rejected_by_the_old_department_scope():
    """Why this change exists: Toulouse used to be thrown away after we paid for it."""
    job = _job("31 - Toulouse")
    old = evaluate(job, parse_experience(job.description), _profile(departments=["75", "92"]))

    assert old.eligible is False
    assert RejectionReason.LOCATION in old.reasons
