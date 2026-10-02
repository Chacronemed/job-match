from datetime import UTC, datetime

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
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
) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=experience_years),
        skills=Skills(),
        filters=Filters(
            contract_types=contract_types or [],
            locations=locations or [],
        ),
        ft_search=FTSearch(),
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
    result = evaluate(
        _make_job(location="69 - Lyon"),
        _req(),
        _make_profile(locations=["Paris"]),
    )
    assert result.eligible is False
    assert RejectionReason.LOCATION in result.reasons


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
