from datetime import datetime

import pytest

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Job, WorkplaceType
from job_match.scoring.native import NativeRuleScorer

ALIASES: dict[str, list[str]] = {
    "kubernetes": ["k8s", "kube"],
    "ci/cd": ["ci cd", "cicd", "continuous integration", "continuous delivery"],
    "docker": ["dockerfile", "docker-compose", "docker compose"],
    "terraform": ["tf", "opentofu"],
    "python": ["python3", "py"],
    "linux": ["unix", "rhel", "ubuntu", "debian", "centos"],
    "ansible": ["ansible-playbook"],
}

SETTINGS = Settings(base_score=50, title_bonus=10)


def _make_job(title: str = "DevOps Engineer", description: str = "") -> Job:
    return Job(
        source="test",
        source_job_id="1",
        title=title,
        company="ACME",
        location="Paris",
        workplace_type=WorkplaceType.ONSITE,
        contract_type=ContractType.CDI,
        description=description,
        url="https://example.com/job/1",
        collected_at=datetime(2026, 10, 1),
    )


def _make_profile(
    preferred: list[tuple[str, int]] | None = None,
    negative: list[tuple[str, int]] | None = None,
    keywords: list[str] | None = None,
) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(
            preferred=[SkillWeight(name=n, weight=w) for n, w in (preferred or [])],
            negative=[SkillWeight(name=n, weight=w) for n, w in (negative or [])],
        ),
        filters=Filters(),
        ft_search=FTSearch(keywords=keywords or []),
        scoring=ScoringConfig(),
    )


SCORER = NativeRuleScorer(ALIASES)


def test_canonical_skill_match() -> None:
    job = _make_job(description="kubernetes cluster management")
    profile = _make_profile(preferred=[("kubernetes", 3)])
    result = SCORER.score(job, profile, SETTINGS)
    assert "kubernetes" in result.positive_matches
    assert result.score == 53


def test_alias_match_k8s() -> None:
    job = _make_job(description="deploy on k8s")
    profile = _make_profile(preferred=[("kubernetes", 3)])
    result = SCORER.score(job, profile, SETTINGS)
    assert "kubernetes" in result.positive_matches
    assert result.score == 53


def test_no_match_goes_to_missing() -> None:
    job = _make_job(description="java spring boot application")
    profile = _make_profile(preferred=[("kubernetes", 3)])
    result = SCORER.score(job, profile, SETTINGS)
    assert result.positive_matches == ()
    assert "kubernetes" in result.missing_preferences


def test_negative_skill_match() -> None:
    job = _make_job(description="SAP integration project")
    profile = _make_profile(negative=[("SAP", -5)])
    result = SCORER.score(job, profile, SETTINGS)
    assert "SAP" in result.negative_matches
    assert result.score == 45


def test_whole_word_go_matches() -> None:
    scorer = NativeRuleScorer({})
    job = _make_job(description="proficient in go and cloud")
    profile = _make_profile(preferred=[("go", 2)])
    result = scorer.score(job, profile, SETTINGS)
    assert "go" in result.positive_matches


def test_go_does_not_match_google() -> None:
    scorer = NativeRuleScorer({})
    job = _make_job(description="google cloud platform experience required")
    profile = _make_profile(preferred=[("go", 2)])
    result = scorer.score(job, profile, SETTINGS)
    assert result.positive_matches == ()
    assert "go" in result.missing_preferences


def test_title_bonus_triggered() -> None:
    job = _make_job(title="devops engineer", description="")
    profile = _make_profile(keywords=["devops"])
    result = SCORER.score(job, profile, SETTINGS)
    assert result.score == 60  # base=50 + title_bonus=10


def test_no_title_bonus_when_keyword_absent() -> None:
    job = _make_job(title="backend developer", description="")
    profile = _make_profile(keywords=["devops"])
    result = SCORER.score(job, profile, SETTINGS)
    assert result.score == 50  # base only


def test_score_clamped_to_100() -> None:
    preferred = [(f"skill{i}", 15) for i in range(10)]
    desc = " ".join(f"skill{i}" for i in range(10))
    job = _make_job(description=desc)
    profile = _make_profile(preferred=preferred)
    scorer = NativeRuleScorer({})
    result = scorer.score(job, profile, SETTINGS)
    assert result.score == 100


def test_score_floor_is_zero() -> None:
    negative = [(f"bad{i}", -15) for i in range(10)]
    desc = " ".join(f"bad{i}" for i in range(10))
    job = _make_job(description=desc)
    profile = _make_profile(negative=negative)
    scorer = NativeRuleScorer({})
    result = scorer.score(job, profile, SETTINGS)
    assert result.score == 0


def test_skill_counted_once_on_repetition() -> None:
    job = _make_job(description="kubernetes kubernetes kubernetes k8s k8s")
    profile = _make_profile(preferred=[("kubernetes", 3)])
    result = SCORER.score(job, profile, SETTINGS)
    assert result.positive_matches == ("kubernetes",)
    assert result.score == 53


def test_available_true_on_success() -> None:
    job = _make_job()
    profile = _make_profile()
    result = SCORER.score(job, profile, SETTINGS)
    assert result.available is True


def test_explanations_mention_matched_skill() -> None:
    job = _make_job(description="kubernetes cluster")
    profile = _make_profile(preferred=[("kubernetes", 3)])
    result = SCORER.score(job, profile, SETTINGS)
    assert any("kubernetes" in e for e in result.explanations)


def test_explanations_mention_missed_skill() -> None:
    job = _make_job(description="java spring")
    profile = _make_profile(preferred=[("terraform", 3)])
    result = SCORER.score(job, profile, SETTINGS)
    assert any("terraform" in e for e in result.explanations)


def test_phrase_alias_matches_ci_cd() -> None:
    job = _make_job(description="maintaining the ci cd pipeline")
    profile = _make_profile(preferred=[("ci/cd", 2)])
    result = SCORER.score(job, profile, SETTINGS)
    assert "ci/cd" in result.positive_matches


@pytest.mark.parametrize("alias", ["cicd", "continuous integration", "continuous delivery"])
def test_other_ci_cd_aliases(alias: str) -> None:
    job = _make_job(description=f"experience with {alias}")
    profile = _make_profile(preferred=[("ci/cd", 2)])
    result = SCORER.score(job, profile, SETTINGS)
    assert "ci/cd" in result.positive_matches
