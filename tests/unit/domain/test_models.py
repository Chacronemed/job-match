from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from job_match.domain.models import (
    ContractType,
    EligibilityResult,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RejectionReason,
    RunSummary,
    ScoreResult,
    ScoringBreakdown,
    WorkplaceType,
)


class TestEnums:
    def test_experience_status_members(self):
        assert set(ExperienceStatus) == {
            ExperienceStatus.ELIGIBLE,
            ExperienceStatus.REJECTED,
            ExperienceStatus.UNKNOWN,
            ExperienceStatus.NOT_MENTIONED,
        }

    def test_contract_type_members(self):
        assert set(ContractType) == {
            ContractType.CDI,
            ContractType.CDD,
            ContractType.INTERIM,
            ContractType.ALTERNANCE,
            ContractType.STAGE,
            ContractType.FREELANCE,
            ContractType.UNKNOWN,
        }

    def test_rejection_reason_members(self):
        assert set(RejectionReason) == {
            RejectionReason.EXPERIENCE,
            RejectionReason.CONTRACT,
            RejectionReason.LOCATION,
            RejectionReason.TITLE,
            RejectionReason.NOT_RELEVANT,
        }

    def test_workplace_type_members(self):
        assert set(WorkplaceType) == {
            WorkplaceType.ONSITE,
            WorkplaceType.HYBRID,
            WorkplaceType.REMOTE,
            WorkplaceType.UNKNOWN,
        }

    def test_str_enum_equality(self):
        assert ContractType.CDI == "CDI"
        assert ExperienceStatus.UNKNOWN == "UNKNOWN"
        assert WorkplaceType.REMOTE == "REMOTE"


class TestExperienceRequirement:
    def test_all_optional_fields_default_to_none(self):
        req = ExperienceRequirement(status=ExperienceStatus.UNKNOWN)
        assert req.status == ExperienceStatus.UNKNOWN
        assert req.min_years is None
        assert req.max_years is None
        assert req.evidence is None

    def test_all_fields_set(self):
        req = ExperienceRequirement(
            status=ExperienceStatus.ELIGIBLE,
            min_years=3.0,
            max_years=5.0,
            evidence="3 ans d'expérience",
        )
        assert req.min_years == 3.0
        assert req.max_years == 5.0
        assert req.evidence == "3 ans d'expérience"


class TestEligibilityResult:
    def test_empty_reasons(self):
        result = EligibilityResult(eligible=True)
        assert result.reasons == ()

    def test_with_reasons(self):
        result = EligibilityResult(
            eligible=False,
            reasons=(RejectionReason.EXPERIENCE, RejectionReason.CONTRACT),
        )
        assert RejectionReason.EXPERIENCE in result.reasons


class TestJobIsFrozen:
    @pytest.fixture
    def minimal_job(self):
        return Job(
            source="france_travail",
            source_job_id="ABC123",
            title="DevOps Engineer",
            company="Acme",
            location="Paris",
            workplace_type=WorkplaceType.HYBRID,
            contract_type=ContractType.CDI,
            description="A great job.",
            url="https://example.com/job/ABC123",
            collected_at=datetime(2026, 10, 1, tzinfo=UTC),
        )

    def test_optional_fields_default_to_none(self, minimal_job):
        assert minimal_job.id is None
        assert minimal_job.company_id is None
        assert minimal_job.published_at is None
        assert minimal_job.fingerprint is None
        assert minimal_job.eligibility is None
        assert minimal_job.rejection_reason is None
        assert minimal_job.experience is None
        assert minimal_job.score is None
        assert minimal_job.scoring_breakdown is None

    def test_frozen_raises_on_assignment(self, minimal_job):
        with pytest.raises(FrozenInstanceError):
            minimal_job.score = 80  # type: ignore[misc]


class TestScoringBreakdown:
    def test_defaults(self):
        bd = ScoringBreakdown(eligible=True, experience=ExperienceStatus.ELIGIBLE)
        assert bd.score is None
        assert bd.divergence is None
        assert bd.needs_review is False
        assert bd.positive_matches == ()
        assert bd.engines == {}

    def test_with_divergence(self):
        bd = ScoringBreakdown(
            eligible=True,
            experience=ExperienceStatus.ELIGIBLE,
            score=85,
            divergence=35,
            needs_review=True,
        )
        assert bd.divergence == 35
        assert bd.needs_review is True


class TestRunSummary:
    def test_defaults_are_zero(self):
        summary = RunSummary(pipeline="jobs")
        assert summary.fetched == 0
        assert summary.eligible == 0
        assert summary.errors == 0
        assert summary.rejected_by_reason == {}

    def test_with_counts(self):
        summary = RunSummary(
            pipeline="jobs",
            fetched=10,
            eligible=7,
            rejected_by_reason={"EXPERIENCE": 3},
        )
        assert summary.fetched == 10
        assert summary.rejected_by_reason["EXPERIENCE"] == 3


class TestScoreResult:
    def test_unavailable(self):
        result = ScoreResult(engine="jms", available=False)
        assert result.score is None
        assert result.positive_matches == ()
        assert result.raw == {}

    def test_frozen(self):
        result = ScoreResult(engine="native", available=True, score=72)
        with pytest.raises(FrozenInstanceError):
            result.score = 80  # type: ignore[misc]
