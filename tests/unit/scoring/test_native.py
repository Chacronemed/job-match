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


def test_positive_and_missing_never_overlap() -> None:
    """A skill must appear in exactly one of positive_matches or missing_preferences."""
    skills = [("kubernetes", 3), ("terraform", 2), ("gitlab", 3), ("ci/cd", 2), ("python", 1)]
    # Job description mentions some skills (matched) and omits others (missing)
    job = _make_job(description="kubernetes cluster with gitlab ci and python scripts")
    profile = _make_profile(preferred=skills)
    aliases = {"ci/cd": ["ci cd", "cicd"], "kubernetes": ["k8s"]}
    scorer = NativeRuleScorer(aliases)
    result = scorer.score(job, profile, SETTINGS)

    overlap = set(result.positive_matches) & set(result.missing_preferences)
    assert not overlap, f"Skills in both positive and missing: {overlap}"
    # Every preferred skill is accounted for exactly once
    all_accounted = set(result.positive_matches) | set(result.missing_preferences)
    assert all_accounted == {s[0] for s in skills}
    assert len(result.positive_matches) + len(result.missing_preferences) == len(skills)


# ---------- M24: title family and profile section ----------

from job_match.config.schema import TitleRelevanceConfig  # noqa: E402
from job_match.scoring.native import profile_weight  # noqa: E402

TITLES = TitleRelevanceConfig(
    core=["devops"], near=["administrateur système"], off_domain=["recrutement"],
    core_points=20, near_points=10, other_points=-15,
)
M24 = Settings(base_score=50, title_bonus=10, title_relevance=TITLES,
               scoring=ScoringConfig(profile_section_multiplier=1.5))


def test_title_family_replaces_the_keyword_bonus():
    profile = _make_profile(keywords=["devops"])
    core = NativeRuleScorer(ALIASES).score(_make_job("Ingénieur DevOps"), profile, M24)
    assert core.score == 70  # 50 + 20, not + 10 more for the keyword
    assert "Title relevance: core (+20)" in core.explanations
    assert not any(e.startswith("Title keyword match") for e in core.explanations)
    assert core.raw["title_family"] == "core"
    other = NativeRuleScorer(ALIASES).score(_make_job("Chef de projet"), profile, M24)
    assert other.score == 35 and "Title relevance: other (-15)" in other.explanations
    near = NativeRuleScorer(ALIASES).score(_make_job("Administrateur système Linux"), profile, M24)
    assert near.score == 60 and "Title relevance: near (+10)" in near.explanations


def test_without_title_relevance_the_keyword_bonus_still_applies():
    profile = _make_profile(keywords=["devops"])
    r = NativeRuleScorer(ALIASES).score(_make_job("DevOps Engineer"), profile, SETTINGS)
    assert r.score == 60 and r.raw["title_family"] is None


def test_a_skill_asked_for_in_the_profile_section_weighs_more():
    desc = ("Vos missions :\n- maintenir les pipelines Docker\n\n"
            "Profil recherché\nTu maîtrises Kubernetes et Terraform.")
    profile = _make_profile(preferred=[("docker", 3), ("kubernetes", 4), ("terraform", 3)])
    r = NativeRuleScorer(ALIASES).score(_make_job("Ingénieur DevOps", desc), profile, M24)
    assert r.weights == {"docker": 3, "kubernetes": 6, "terraform": 5}  # 4x1.5, 3x1.5 half up
    assert "Matched preferred: kubernetes (+6)" in r.explanations
    assert "Profile section: kubernetes (x1.5)" in r.explanations
    assert "Profile section: docker (x1.5)" not in r.explanations
    assert r.score == 50 + 20 + 3 + 6 + 5


def test_negatives_are_never_multiplied_and_no_section_means_no_change():
    desc = "Profil :\nTu connais SAP et Docker."
    profile = _make_profile(preferred=[("docker", 3)], negative=[("sap", -5)])
    r = NativeRuleScorer(ALIASES).score(_make_job("Ingénieur DevOps", desc), profile, M24)
    assert r.weights == {"docker": 5, "sap": -5}
    flat_job = _make_job("Ingénieur DevOps", "Docker et SAP au quotidien.")
    flat = NativeRuleScorer(ALIASES).score(flat_job, profile, M24)
    assert flat.weights == {"docker": 3, "sap": -5}


def test_profile_weight_rounds_half_up():
    assert [profile_weight(w, 1.5) for w in (1, 2, 3, 4, 5)] == [2, 3, 5, 6, 8]
    assert profile_weight(4, 1.0) == 4
