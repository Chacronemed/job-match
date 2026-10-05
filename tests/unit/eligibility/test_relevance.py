"""Relevance gate: a job must match >=1 preferred skill or have a target-role title keyword."""
from datetime import UTC, datetime

import pytest

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    RelevanceConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import (
    ContractType,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RejectionReason,
    WorkplaceType,
)
from job_match.eligibility.gate import evaluate, is_relevant

KEYWORDS = ["devops", "sre", "cloud", "platform", "infra", "système", "production", "kubernetes"]
NOT_MENTIONED = ExperienceRequirement(status=ExperienceStatus.NOT_MENTIONED)


def _job(title: str, description: str = "") -> Job:
    return Job(
        source="test", source_job_id="1", title=title, company="Acme", location="Paris",
        workplace_type=WorkplaceType.UNKNOWN, contract_type=ContractType.CDI,
        description=description, url="https://x.test/1", collected_at=datetime.now(UTC),
    )


def _profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=5),
        skills=Skills(preferred=[SkillWeight("kubernetes", 3), SkillWeight("terraform", 3)]),
        filters=Filters(),
        ft_search=FTSearch(),
    )


def _settings(keywords: list[str] | None = None) -> Settings:
    return Settings(relevance=RelevanceConfig(
        target_title_keywords=KEYWORDS if keywords is None else keywords))


def test_receptionist_is_not_relevant():
    job = _job("Réceptionniste en hôtellerie (H/F)",
               "Accueil des clients, gestion des réservations et du standard.")
    result = evaluate(job, NOT_MENTIONED, _profile(), _settings())
    assert not result.eligible
    assert result.reasons == (RejectionReason.NOT_RELEVANT,)


@pytest.mark.parametrize("title", [
    "Ingénieur DevOps (H/F)",
    "Administrateur Systèmes Linux",       # "système" prefix, accent-insensitive
    "Ingénieur Infrastructure Cloud",       # "infra" prefix
    "Ingénieur de production informatique",
])
def test_target_title_keyword_is_relevant(title):
    assert is_relevant(_job(title), _profile(), KEYWORDS)


def test_preferred_skill_in_description_is_relevant():
    job = _job("Data Engineer", "Pipelines déployés sur Kubernetes.")
    assert is_relevant(job, _profile(), KEYWORDS)


def test_preferred_skill_alias_counts():
    job = _job("Développeur backend", "Déploiement sur k8s.")
    assert is_relevant(job, _profile(), KEYWORDS, aliases={"kubernetes": ["k8s"]})
    assert not is_relevant(job, _profile(), KEYWORDS)  # without the alias table


def test_empty_keyword_list_disables_the_gate():
    result = evaluate(_job("Réceptionniste"), NOT_MENTIONED, _profile(), _settings([]))
    assert result.eligible


def test_not_relevant_combines_with_other_reasons():
    profile = _profile()
    profile.filters.contract_types = [ContractType.CDI]
    job = _job("Barista")
    job = Job(**{**{f: getattr(job, f) for f in job.__slots__}, "contract_type": ContractType.CDD})
    result = evaluate(job, NOT_MENTIONED, profile, _settings())
    assert set(result.reasons) == {RejectionReason.NOT_RELEVANT, RejectionReason.CONTRACT}


# ---------------------------------------------------------------------------
# Committed keyword list (config/settings.yaml)
# ---------------------------------------------------------------------------

def _committed_keywords() -> list[str]:
    from pathlib import Path

    from job_match.config.loader import load_settings

    settings = load_settings(Path(__file__).parents[3] / "config" / "settings.yaml")
    return settings.relevance.target_title_keywords


def test_committed_keywords_drop_bare_production():
    kws = _committed_keywords()
    assert "production" not in kws
    assert {"ingénieur de production informatique", "exploitation"} <= set(kws)


@pytest.mark.parametrize("title,relevant", [
    ("Ingénieur de Production Qualité (H/F)", False),
    ("Ingénieur de Production - Optimisation des Processus (H/F)", False),
    ("Conducteur de ligne de production (H/F)", False),
    ("Ingénieur de production informatique (H/F)", True),
    ("Ingénieur d'exploitation (H/F)", True),
    ("Technicien d'Exploitation Systèmes (H/F)", True),
])
def test_committed_keywords_on_production_titles(title, relevant):
    no_skills = Profile(candidate=Candidate(experience_years=5), skills=Skills(),
                        filters=Filters(), ft_search=FTSearch())
    assert is_relevant(_job(title), no_skills, _committed_keywords()) is relevant
