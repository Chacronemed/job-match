from datetime import UTC, datetime

import pytest

from job_match.config.schema import (
    Candidate,
    ExperienceConfig,
    Filters,
    FTSearch,
    Profile,
    RelevanceConfig,
    ScoringConfig,
    Settings,
    Skills,
)
from job_match.domain.models import (
    ContractType,
    EligibilityResult,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RejectionReason,
    WorkplaceType,
)
from job_match.eligibility.gate import evaluate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(**kwargs) -> Job:
    defaults: dict = dict(
        source="test",
        source_job_id="JOB001",
        title="DevOps Engineer",
        company="Acme",
        location="75 - Paris",
        workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI,
        description="",
        url="https://example.com/job/1",
        collected_at=datetime.now(UTC),
    )
    return Job(**{**defaults, **kwargs})


def _make_profile(
    experience_years: float = 5.0,
    contract_types: list | None = None,
    locations: list | None = None,
    departments: list[str] | None = None,
) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=experience_years),
        skills=Skills(),
        filters=Filters(
            contract_types=contract_types or [],
            locations=locations or [],
        ),
        ft_search=FTSearch(departments=departments or []),
        scoring=ScoringConfig(),
    )


def _req(
    status: ExperienceStatus = ExperienceStatus.ELIGIBLE,
    min_years: float | None = None,
    max_years: float | None = None,
) -> ExperienceRequirement:
    return ExperienceRequirement(status=status, min_years=min_years, max_years=max_years)


# ---------------------------------------------------------------------------
# Experience gate
# ---------------------------------------------------------------------------


def test_eligible_under_threshold():
    result = evaluate(_make_job(), _req(min_years=3.0), _make_profile(experience_years=5.0))
    assert result.eligible is True
    assert result.reasons == ()


def test_eligible_at_exact_threshold():
    result = evaluate(_make_job(), _req(min_years=5.0), _make_profile(experience_years=5.0))
    assert result.eligible is True


def test_rejected_over_threshold():
    result = evaluate(_make_job(), _req(min_years=6.0), _make_profile(experience_years=5.0))
    assert result.eligible is False
    assert RejectionReason.EXPERIENCE in result.reasons


def test_unknown_stays_eligible():
    result = evaluate(_make_job(), _req(status=ExperienceStatus.UNKNOWN), _make_profile())
    assert result.eligible is True


def test_not_mentioned_stays_eligible():
    result = evaluate(_make_job(), _req(status=ExperienceStatus.NOT_MENTIONED), _make_profile())
    assert result.eligible is True


def test_eligible_status_without_min_years_passes():
    # ELIGIBLE status but min_years=None (e.g. only a max was found)
    result = evaluate(_make_job(), _req(min_years=None, max_years=2.0), _make_profile())
    assert result.eligible is True


# ---------------------------------------------------------------------------
# Contract gate
# ---------------------------------------------------------------------------


def test_contract_match():
    result = evaluate(
        _make_job(contract_type=ContractType.CDI),
        _req(),
        _make_profile(contract_types=[ContractType.CDI]),
    )
    assert result.eligible is True


def test_contract_rejected():
    result = evaluate(
        _make_job(contract_type=ContractType.CDD),
        _req(),
        _make_profile(contract_types=[ContractType.CDI]),
    )
    assert result.eligible is False
    assert RejectionReason.CONTRACT in result.reasons


def test_contract_filter_empty():
    result = evaluate(
        _make_job(contract_type=ContractType.CDD),
        _req(),
        _make_profile(contract_types=[]),
    )
    assert result.eligible is True


def test_contract_multiple_allowed():
    result = evaluate(
        _make_job(contract_type=ContractType.FREELANCE),
        _req(),
        _make_profile(contract_types=[ContractType.CDI, ContractType.FREELANCE]),
    )
    assert result.eligible is True


# ---------------------------------------------------------------------------
# Location gate
# ---------------------------------------------------------------------------


def test_location_match_substring():
    result = evaluate(
        _make_job(location="75 - Paris"),
        _req(),
        _make_profile(locations=["Paris"]),
    )
    assert result.eligible is True


def test_location_rejected():
    """A restricted scope rejects a department outside it."""
    result = evaluate(
        _make_job(location="69 - Lyon"),
        _req(),
        _make_profile(locations=["Paris"], departments=["75"]),
    )
    assert result.eligible is False
    assert RejectionReason.LOCATION in result.reasons


def test_a_city_filter_alone_does_not_restrict_a_national_scope():
    """No department list = national: Lyon is in France, so it stays."""
    result = evaluate(
        _make_job(location="69 - Lyon"),
        _req(),
        _make_profile(locations=["Paris"]),
    )
    assert result.eligible is True


def test_location_remote_always_passes():
    result = evaluate(
        _make_job(location="remote"),
        _req(),
        _make_profile(locations=["Paris"]),
    )
    assert result.eligible is True


def test_location_remote_case_insensitive():
    result = evaluate(
        _make_job(location="Full Remote"),
        _req(),
        _make_profile(locations=["Paris"]),
    )
    assert result.eligible is True


def test_location_filter_empty():
    result = evaluate(
        _make_job(location="69 - Lyon"),
        _req(),
        _make_profile(locations=[]),
    )
    assert result.eligible is True


def test_location_case_insensitive_match():
    result = evaluate(
        _make_job(location="75 - paris"),
        _req(),
        _make_profile(locations=["Paris"]),
    )
    assert result.eligible is True


# ---------------------------------------------------------------------------
# Location gate — department prefix (the codes we actually query)
# ---------------------------------------------------------------------------

_IDF = ["75", "77", "78", "91", "92", "93", "94", "95"]


@pytest.mark.parametrize(
    ("location", "why"),
    [
        ("92 - Nanterre", "department 92 is queried, city is not in the list"),
        ("77 - Melun", "department 77 is queried, city is not in the list"),
        ("Paris 15e", "city name matches, no department prefix to read"),
        ("France", "unparseable location is kept, never rejected"),
    ],
)
def test_location_accepted(location, why):
    result = evaluate(
        _make_job(location=location),
        _req(),
        _make_profile(locations=["Paris"], departments=_IDF),
    )
    assert result.eligible is True, why


def test_location_rejected_when_department_is_not_queried():
    """A readable department outside the configured list is still a rejection."""
    result = evaluate(
        _make_job(location="13 - Marseille"),
        _req(),
        _make_profile(locations=["Paris"], departments=_IDF),
    )
    assert result.eligible is False
    assert RejectionReason.LOCATION in result.reasons


def test_location_department_match_needs_no_duplicated_city_list():
    """ft_search.departments is the single source of truth: no city names configured."""
    result = evaluate(
        _make_job(location="93 - Saint-Denis"),
        _req(),
        _make_profile(locations=["Paris"], departments=["93"]),
    )
    assert result.eligible is True


def test_location_remote_passes_even_for_a_foreign_department():
    result = evaluate(
        _make_job(location="13 - Marseille, remote"),
        _req(),
        _make_profile(locations=["Paris"], departments=_IDF),
    )
    assert result.eligible is True


# ---------------------------------------------------------------------------
# Multiple rejections
# ---------------------------------------------------------------------------


def test_multiple_rejections_all_three():
    result = evaluate(
        _make_job(contract_type=ContractType.CDD, location="69 - Lyon"),
        _req(min_years=10.0),
        _make_profile(
            experience_years=5.0,
            contract_types=[ContractType.CDI],
            locations=["Paris"],
            departments=["75"],
        ),
    )
    assert result.eligible is False
    assert RejectionReason.EXPERIENCE in result.reasons
    assert RejectionReason.CONTRACT in result.reasons
    assert RejectionReason.LOCATION in result.reasons


def test_multiple_rejections_returns_eligibility_result():
    result = evaluate(_make_job(), _req(), _make_profile())
    assert isinstance(result, EligibilityResult)
    assert isinstance(result.reasons, tuple)


# ---------------------------------------------------------------------------
# Seniority keyword gate
# ---------------------------------------------------------------------------

_SMAP = {"junior": 0, "senior": 5, "expert": 7, "confirmé": 3}


def _make_settings(**kwargs) -> Settings:
    return Settings(**kwargs)


def test_seniority_rejects_when_no_explicit_number():
    job = _make_job(title="Ingénieur DevOps Senior")
    req = _req(status=ExperienceStatus.NOT_MENTIONED)
    result = evaluate(
        job, req, _make_profile(experience_years=2.0), _make_settings(seniority_min_years=_SMAP)
    )
    assert not result.eligible
    assert RejectionReason.EXPERIENCE in result.reasons


def test_seniority_eligible_when_candidate_meets_minimum():
    job = _make_job(title="Senior DevOps Engineer")
    req = _req(status=ExperienceStatus.NOT_MENTIONED)
    result = evaluate(
        job, req, _make_profile(experience_years=5.0), _make_settings(seniority_min_years=_SMAP)
    )
    assert result.eligible


def test_explicit_number_wins_over_seniority_keyword():
    # Title says "Senior" (→ 5 yrs) but description says "2 ans minimum" → effective_min=2
    job = _make_job(title="Senior DevOps", description="Minimum 2 ans d'expérience")
    req = _req(status=ExperienceStatus.ELIGIBLE, min_years=2.0)
    result = evaluate(
        job, req, _make_profile(experience_years=3.0), _make_settings(seniority_min_years=_SMAP)
    )
    assert result.eligible  # explicit 2 wins over seniority 5; candidate has 3


def test_seniority_not_applied_without_settings():
    # No settings passed → old behaviour: NOT_MENTIONED = eligible regardless
    job = _make_job(title="Senior DevOps Engineer")
    req = _req(status=ExperienceStatus.NOT_MENTIONED)
    result = evaluate(job, req, _make_profile(experience_years=2.0))
    assert result.eligible


# ---------------------------------------------------------------------------
# Experience stretch tier: candidate < required <= candidate + stretch_years
# ---------------------------------------------------------------------------

def _stretch_settings(years: float = 1, **kwargs) -> Settings:
    return Settings(
        experience=ExperienceConfig(stretch_years=years), seniority_min_years=_SMAP, **kwargs
    )


def test_one_year_over_is_stretch_not_rejected():
    result = evaluate(
        _make_job(), _req(min_years=3.0), _make_profile(experience_years=2.0),
        _stretch_settings(1),
    )
    assert result.eligible is True
    assert result.stretch is True
    assert result.reasons == ()
    assert result.required_years == 3.0


def test_a_seniority_keyword_without_a_number_can_be_stretch():
    """"confirmé" implies 3 years (settings map); candidate has 2, band is 1."""
    job = _make_job(title="Ingénieur DevOps confirmé", description="Kubernetes.")
    result = evaluate(
        job, _req(status=ExperienceStatus.NOT_MENTIONED), _make_profile(experience_years=2.0),
        _stretch_settings(1),
    )
    assert result.stretch is True
    assert result.required_years == 3.0


def test_beyond_the_band_is_rejected_as_before():
    result = evaluate(
        _make_job(), _req(min_years=4.0), _make_profile(experience_years=2.0),
        _stretch_settings(1),
    )
    assert result.eligible is False
    assert result.stretch is False
    assert RejectionReason.EXPERIENCE in result.reasons


def test_stretch_needs_every_other_gate_to_pass():
    """A dev title in the band is rejected (NOT_RELEVANT), not stretch."""
    settings = _stretch_settings(
        1,
        relevance=RelevanceConfig(
            target_title_keywords=["devops"], role_titles=["devops"], dev_titles=["développeur"],
        ),
    )
    job = _make_job(title="Développeur Java", description="Kubernetes. 3 ans d'expérience.")
    result = evaluate(job, _req(min_years=3.0), _make_profile(experience_years=2.0), settings)
    assert result.eligible is False
    assert result.stretch is False
    assert RejectionReason.NOT_RELEVANT in result.reasons
    assert RejectionReason.EXPERIENCE not in result.reasons  # it was within the band


def test_stretch_years_zero_disables_the_tier():
    result = evaluate(
        _make_job(), _req(min_years=3.0), _make_profile(experience_years=2.0),
        _stretch_settings(0),
    )
    assert result.eligible is False
    assert RejectionReason.EXPERIENCE in result.reasons


def test_no_stretch_without_settings():
    result = evaluate(_make_job(), _req(min_years=3.0), _make_profile(experience_years=2.0))
    assert result.eligible is False


def test_meeting_the_requirement_is_eligible_not_stretch():
    result = evaluate(
        _make_job(), _req(min_years=2.0), _make_profile(experience_years=2.0),
        _stretch_settings(1),
    )
    assert result.eligible is True
    assert result.stretch is False


def test_the_band_edge_is_inclusive_and_fractional_years_count():
    settings = _stretch_settings(1)
    assert evaluate(_make_job(), _req(min_years=3.0), _make_profile(2.0), settings).stretch
    assert evaluate(_make_job(), _req(min_years=2.5), _make_profile(2.0), settings).stretch
    assert not evaluate(_make_job(), _req(min_years=3.5), _make_profile(2.0), settings).eligible


def test_seniority_junior_never_rejects():
    job = _make_job(title="Junior DevOps Engineer")
    req = _req(status=ExperienceStatus.NOT_MENTIONED)
    smap = {"junior": 0}
    result = evaluate(
        job, req, _make_profile(experience_years=0.0), _make_settings(seniority_min_years=smap)
    )
    assert result.eligible


def test_seniority_unknown_status_with_keyword():
    # exp is UNKNOWN (ambiguous text) but title says "Senior" → seniority applies
    job = _make_job(title="Senior DevOps")
    req = _req(status=ExperienceStatus.UNKNOWN)
    result = evaluate(
        job, req, _make_profile(experience_years=2.0), _make_settings(seniority_min_years=_SMAP)
    )
    assert not result.eligible


def test_seniority_confirme_in_title():
    job = _make_job(title="Ingénieur DevOps Confirmé")
    req = _req(status=ExperienceStatus.NOT_MENTIONED)
    result = evaluate(
        job, req, _make_profile(experience_years=2.0), _make_settings(seniority_min_years=_SMAP)
    )
    assert not result.eligible  # confirmé → 3 yrs; candidate has 2


# ---------------------------------------------------------------------------
# Location gate — Jooble / Adzuna formats (city or region name, no "NN -" prefix)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("location", "why"),
    [
        ("Nanterre", "bare city resolves to 92, which we query"),
        ("Nanterre, Hauts-de-Seine", "Adzuna's city + department form"),
        ("Île-de-France", "region overlaps the departments we query"),
        ("Melun", "77 is queried even though no city name is configured"),
        ("Télétravail", "remote in French"),
        ("Saint-Machin-sur-Glane", "unknown place is kept under a restricted scope"),
        ("France", "country-wide posting is kept"),
    ],
)
def test_location_accepted_without_a_department_prefix(location, why):
    result = evaluate(
        _make_job(location=location),
        _req(),
        _make_profile(locations=["Paris"], departments=_IDF),
    )
    assert result.eligible is True, why


@pytest.mark.parametrize("location", ["Marseille", "Nantes", "Strasbourg"])
def test_location_rejected_for_a_city_outside_the_queried_departments(location):
    result = evaluate(
        _make_job(location=location),
        _req(),
        _make_profile(locations=["Paris"], departments=_IDF),
    )
    assert result.eligible is False
    assert RejectionReason.LOCATION in result.reasons


def test_region_passes_when_only_one_of_its_departments_is_queried():
    """"Provence-Alpes-Côte d'Azur" covers 06, which we query — keep it."""
    result = evaluate(
        _make_job(location="Provence-Alpes-Côte d'Azur"),
        _req(),
        _make_profile(locations=["Nice"], departments=["06"]),
    )
    assert result.eligible is True


# ---------------------------------------------------------------------------
# Contract gate — UNKNOWN is "not stated", not "wrong"
# ---------------------------------------------------------------------------

def test_unknown_contract_type_is_not_a_rejection():
    """Jooble and Adzuna often ship no usable contract field; we don't reject on silence."""
    result = evaluate(
        _make_job(contract_type=ContractType.UNKNOWN),
        _req(),
        _make_profile(contract_types=[ContractType.CDI]),
    )
    assert result.eligible is True


def test_a_stated_contract_outside_the_filter_is_still_rejected():
    result = evaluate(
        _make_job(contract_type=ContractType.STAGE),
        _req(),
        _make_profile(contract_types=[ContractType.CDI]),
    )
    assert result.eligible is False
    assert RejectionReason.CONTRACT in result.reasons
