from datetime import datetime

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
    ScoreResult,
    WorkplaceType,
)
from job_match.scoring.engine import ScoringEngine
from job_match.scoring.native import NativeRuleScorer

SETTINGS = Settings(base_score=50, title_bonus=10)


def _make_job() -> Job:
    return Job(
        source="test",
        source_job_id="1",
        title="DevOps Engineer",
        company="ACME",
        location="Paris",
        workplace_type=WorkplaceType.ONSITE,
        contract_type=ContractType.CDI,
        description="",
        url="https://example.com/job/1",
        collected_at=datetime(2026, 10, 1),
    )


def _make_profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(),
        scoring=ScoringConfig(),
    )


def _make_eligibility(eligible: bool = True) -> EligibilityResult:
    return EligibilityResult(eligible=eligible)


def _make_experience(
    status: ExperienceStatus = ExperienceStatus.NOT_MENTIONED,
) -> ExperienceRequirement:
    return ExperienceRequirement(status=status)


class FakeScorer:
    def __init__(self, scorer_name: str, scorer_score: int) -> None:
        self._name = scorer_name
        self._score = scorer_score

    @property
    def name(self) -> str:
        return self._name

    def score(self, job: Job, profile: Profile, settings: Settings) -> ScoreResult:
        return ScoreResult(engine=self._name, available=True, score=self._score)


class CrashingScorer:
    @property
    def name(self) -> str:
        return "bad"

    def score(self, job: Job, profile: Profile, settings: Settings) -> ScoreResult:
        raise RuntimeError("scorer exploded")


def test_engine_with_native_returns_breakdown() -> None:
    engine = ScoringEngine([NativeRuleScorer({})])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(),
    )
    assert breakdown.score is not None
    assert "native" in breakdown.engines


def test_scorer_exception_marks_unavailable() -> None:
    engine = ScoringEngine([CrashingScorer()])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(),
    )
    assert breakdown.engines["bad"].available is False
    assert breakdown.engines["bad"].score is None


def test_engine_with_no_scorers_returns_none_score() -> None:
    engine = ScoringEngine([])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(),
    )
    assert breakdown.score is None
    assert breakdown.engines == {}
    assert breakdown.eligible is True


def test_divergence_computed_for_two_scorers() -> None:
    engine = ScoringEngine([FakeScorer("native", 80), FakeScorer("jms", 40)])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(),
    )
    assert breakdown.divergence == 40


def test_needs_review_when_divergence_over_threshold() -> None:
    engine = ScoringEngine([FakeScorer("native", 80), FakeScorer("jms", 40)])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(),
    )
    assert breakdown.needs_review is True


def test_needs_review_false_when_single_scorer() -> None:
    engine = ScoringEngine([NativeRuleScorer({})])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(),
    )
    assert breakdown.needs_review is False
    assert breakdown.divergence is None


def test_eligibility_propagated() -> None:
    engine = ScoringEngine([])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(eligible=False), _make_experience(),
    )
    assert breakdown.eligible is False


def test_experience_status_propagated() -> None:
    engine = ScoringEngine([])
    breakdown = engine.score(
        _make_job(), _make_profile(), SETTINGS,
        _make_eligibility(), _make_experience(status=ExperienceStatus.UNKNOWN),
    )
    assert breakdown.experience == ExperienceStatus.UNKNOWN
