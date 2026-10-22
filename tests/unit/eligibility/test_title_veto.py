"""The title veto: a developer role is a developer role, whatever its description says.

Regression: "Développeur(se) - Java Angular & Cloud - Services Publics" scored 74 and was
emailed as a strong match, because its body text mentions cloud, Kubernetes and Docker.
The title decides the role.
"""
from pathlib import Path

import pytest

from job_match.config.loader import load_settings
from job_match.config.schema import (
    Candidate,
    Filters,
    Profile,
    RelevanceConfig,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Job, RejectionReason, WorkplaceType
from job_match.eligibility.gate import evaluate, title_is_a_dev_role
from job_match.experience.parser import parse as parse_experience

ROLE_TITLES = [
    "devops", "sre", "site reliability", "platform engineer", "cloud engineer",
    "ingénieur cloud", "infrastructure", "ops", "ingénieur système", "kubernetes",
]
DEV_TITLES = [
    "développeur", "développeuse", "developer", "dev", "fullstack", "full stack",
    "frontend", "backend", "java", "angular", "react", ".net", "php",
    "data scientist", "data analyst",
]

REAL_RELEVANCE = load_settings(Path("config/settings.yaml")).relevance


def _relevance(**kwargs) -> RelevanceConfig:
    return RelevanceConfig(
        target_title_keywords=kwargs.pop("target_title_keywords", []),
        role_titles=kwargs.pop("role_titles", ROLE_TITLES),
        dev_titles=kwargs.pop("dev_titles", DEV_TITLES),
    )


# ---------------------------------------------------------------------------
# The four cases from the bug report
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("title", "vetoed"),
    [
        ("Développeur(se) - Java Angular & Cloud - Services Publics", True),
        ("Ingénieur DevOps Java", False),
        ("Cloud Engineer", False),
        ("Développeur Cloud", True),
    ],
)
def test_the_reported_titles(title, vetoed):
    assert title_is_a_dev_role(title, _relevance()) is vetoed


@pytest.mark.parametrize(
    ("title", "vetoed"),
    [
        ("Développeur(se) - Java Angular & Cloud - Services Publics", True),
        ("Ingénieur DevOps Java", False),
        ("Cloud Engineer", False),
        ("Développeur Cloud", True),
    ],
)
def test_the_reported_titles_against_the_committed_config(title, vetoed):
    """The lists live in config/settings.yaml, not in the code — check the real ones."""
    assert title_is_a_dev_role(title, REAL_RELEVANCE) is vetoed


# ---------------------------------------------------------------------------
# "cloud" alone never rescues a dev title
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Développeur Cloud",
        "Développeur Java Cloud AWS",
        "Backend Developer - Cloud Native",
        "Data Scientist Cloud",
    ],
)
def test_bare_cloud_is_not_an_explicit_role(title):
    assert title_is_a_dev_role(title, _relevance()) is True


@pytest.mark.parametrize(
    "title",
    [
        "Cloud Engineer",
        "Ingénieur Cloud",
        "Ingénieur Cloud & Java",       # explicit role_title phrase, dev title tolerated
        "Cloud Engineer (React)",
    ],
)
def test_an_explicit_cloud_role_phrase_passes(title):
    assert title_is_a_dev_role(title, _relevance()) is False


# ---------------------------------------------------------------------------
# A role_title alongside a dev_title keeps the job
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Ingénieur DevOps Java",
        "DevOps / Backend Engineer",
        "SRE (Java, Kubernetes)",
        "Site Reliability Engineer - Angular shop",
        "Platform Engineer PHP",
        "Ingénieur Système et développeur de scripts",
        "Kubernetes Engineer with .NET experience",
    ],
)
def test_an_explicit_role_title_survives_a_dev_title(title):
    assert title_is_a_dev_role(title, _relevance()) is False


# ---------------------------------------------------------------------------
# Titles with no dev_title are never vetoed (the veto only ever removes dev roles)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Ingénieur DevOps",
        "Administrateur Systèmes et Réseaux",
        "Technicien Support",            # irrelevant, but not the veto's job
        "Réceptionniste en hôtellerie",
        "Network Engineer",              # ".net" must not match "network"
        "Netapp Storage Administrator",
        "Expert Cdiscount",              # "dev"/"cdi" substrings must not fire
        "",
    ],
)
def test_titles_without_a_dev_title_pass_the_veto(title):
    assert title_is_a_dev_role(title, _relevance()) is False


def test_matching_is_whole_word_not_prefix():
    """"dev" must not match "devops", or every DevOps job would need a rescue."""
    assert title_is_a_dev_role("DevOps", _relevance(role_titles=[])) is False


def test_accents_and_punctuation_do_not_matter():
    assert title_is_a_dev_role("DÉVELOPPEUR(SE) JAVA", _relevance()) is True


# ---------------------------------------------------------------------------
# The veto is configuration, and off when unconfigured
# ---------------------------------------------------------------------------

def test_empty_dev_titles_disables_the_veto():
    assert title_is_a_dev_role("Développeur Java", _relevance(dev_titles=[])) is False


def test_lists_come_from_config_not_code():
    """Swapping the config swaps the behaviour — nothing is hard-coded."""
    custom = _relevance(dev_titles=["chef de projet"], role_titles=["devops"])
    assert title_is_a_dev_role("Chef de Projet IT", custom) is True
    assert title_is_a_dev_role("Développeur Java", custom) is False


def test_the_committed_config_has_both_lists():
    assert "développeur" in REAL_RELEVANCE.dev_titles
    assert "devops" in REAL_RELEVANCE.role_titles
    assert "cloud" not in REAL_RELEVANCE.role_titles  # only the explicit phrases count


# ---------------------------------------------------------------------------
# End to end through the gate: the veto beats a description full of our skills
# ---------------------------------------------------------------------------

def _profile() -> Profile:
    from job_match.config.schema import FTSearch
    return Profile(
        candidate=Candidate(experience_years=2.0),
        skills=Skills(
            preferred=[
                SkillWeight(name="kubernetes", weight=3),
                SkillWeight(name="docker", weight=2),
                SkillWeight(name="cloud", weight=2),
            ],
            negative=[],
        ),
        filters=Filters(contract_types=[ContractType.CDI], locations=[]),
        ft_search=FTSearch(keywords=["cloud"], departments=["75"]),
        scoring=ScoringConfig(),
    )


def _settings() -> Settings:
    return Settings(
        relevance=_relevance(target_title_keywords=["devops", "cloud", "infra"]),
    )


def _job(title: str, description: str) -> Job:
    from datetime import UTC, datetime
    return Job(
        source="france_travail",
        source_job_id="FT-1",
        title=title,
        company="Acme",
        location="75 - Paris",
        workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI,
        description=description,
        url="https://example.com/1",
        collected_at=datetime.now(UTC),
    )


DEV_DESCRIPTION = (
    "Au sein de notre equipe, vous developpez des applications Java Angular deployees "
    "sur notre cloud interne avec Kubernetes et Docker."
)


def test_the_reported_job_is_now_rejected_despite_matching_skills():
    job = _job("Développeur(se) - Java Angular & Cloud - Services Publics", DEV_DESCRIPTION)
    result = evaluate(job, parse_experience(job.description), _profile(), _settings(), {})

    assert result.eligible is False
    assert RejectionReason.NOT_RELEVANT in result.reasons


def test_a_devops_job_with_the_same_description_is_still_eligible():
    """The description is identical — only the title differs."""
    job = _job("Ingénieur DevOps Java", DEV_DESCRIPTION)
    result = evaluate(job, parse_experience(job.description), _profile(), _settings(), {})
    assert result.eligible is True


# ---------- M24: another trade in the title (title_relevance.off_domain) ----------

def _m24_settings() -> Settings:
    from job_match.config.schema import TitleRelevanceConfig
    return Settings(
        relevance=_relevance(target_title_keywords=["devops", "cloud", "infra", "exploitation"]),
        title_relevance=TitleRelevanceConfig(
            core=["devops"], off_domain=["recrutement", "mécanique"]
        ),
    )


def test_an_off_domain_title_is_rejected_with_reason_title_whatever_its_skills():
    # the skills match; "devsecops" is not the configured "devops" prefix
    job = _job("Consultant en recrutement DevSecOps", DEV_DESCRIPTION)
    result = evaluate(job, parse_experience(job.description), _profile(), _m24_settings(), {})
    assert result.eligible is False
    assert RejectionReason.TITLE in result.reasons


def test_a_core_term_keeps_an_off_domain_word_in_the_title_eligible():
    job = _job("Ingénieur DevOps - recrutement interne", "Kubernetes et Docker au quotidien.")
    result = evaluate(job, parse_experience(job.description), _profile(), _m24_settings(), {})
    assert result.eligible is True


def test_without_title_relevance_no_title_veto_runs():
    job = _job("Ingénieur mécanique", "Kubernetes et Docker au quotidien.")
    result = evaluate(job, parse_experience(job.description), _profile(), _settings(), {})
    assert RejectionReason.TITLE not in result.reasons


def test_a_core_title_with_a_sales_role_is_kept_and_scored_as_other():
    from job_match.config.schema import TitleRelevanceConfig
    from job_match.scoring.native import NativeRuleScorer
    settings = Settings(
        relevance=_relevance(target_title_keywords=["devops", "cloud"]),
        title_relevance=TitleRelevanceConfig(
            core=["cloud"], off_domain=["commercial"], core_overrides=["commercial"]
        ),
    )
    job = _job("Ingénieur commercial Cloud", "Kubernetes et Docker au quotidien.")
    result = evaluate(job, parse_experience(job.description), _profile(), settings, {})
    assert result.eligible is True and RejectionReason.TITLE not in result.reasons
    scored = NativeRuleScorer({}).score(job, _profile(), settings)
    assert "Title relevance: other (-15)" in scored.explanations
