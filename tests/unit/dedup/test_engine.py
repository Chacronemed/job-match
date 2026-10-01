from datetime import UTC, datetime

import pytest

from job_match.config.schema import Settings
from job_match.dedup.engine import DedupEngine, DedupResult
from job_match.dedup.fingerprint import compute_fingerprint
from job_match.domain.models import ContractType, Job, WorkplaceType

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _settings(**overrides) -> Settings:
    defaults = dict(fuzzy_title_threshold=0.85, fuzzy_desc_threshold=0.80)
    return Settings(**{**defaults, **overrides})


def _job(job_id: int | None = None, **overrides) -> Job:
    defaults = dict(
        source="france_travail",
        source_job_id="1",
        title="DevOps Engineer",
        company="Acme Corp",
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="We need a DevOps engineer with Kubernetes and Terraform skills.",
        url="https://example.com/job/1",
        collected_at=_NOW,
    )
    j = Job(**{**defaults, **overrides})
    fp = compute_fingerprint(j)
    # attach fingerprint and id
    return Job(
        id=job_id,
        fingerprint=fp,
        source=j.source, source_job_id=j.source_job_id,
        title=j.title, company=j.company, location=j.location,
        workplace_type=j.workplace_type, contract_type=j.contract_type,
        description=j.description, url=j.url, collected_at=j.collected_at,
    )


@pytest.fixture
def engine():
    return DedupEngine(_settings())


def test_no_candidates_returns_not_duplicate(engine):
    job = _job()
    result = engine.check(job, [], [])
    assert result == DedupResult(is_duplicate=False)


def test_exact_fingerprint_match(engine):
    existing = _job(job_id=10)
    new_job = _job(job_id=None)  # same content
    result = engine.check(new_job, [existing], [])
    assert result.is_duplicate
    assert result.reason == "exact_fingerprint"
    assert result.canonical_id == 10
    assert result.similarity == 1.0


def test_fuzzy_match_above_threshold(engine):
    base_desc = "We need a DevOps engineer with Kubernetes and Terraform skills " * 5
    existing = _job(job_id=5, description=base_desc)
    # Slightly different title and very similar description
    new_job = _job(
        job_id=None,
        title="DevOps Engineer Senior",
        description=base_desc + " Also Docker.",
    )
    result = engine.check(new_job, [], [existing])
    assert result.is_duplicate
    assert result.reason == "fuzzy"
    assert result.canonical_id == 5
    assert result.similarity is not None


def test_fuzzy_near_miss_not_duplicate(engine):
    existing = _job(
        job_id=7,
        title="Frontend Developer",
        description="React, TypeScript, CSS, Node, GraphQL expertise required.",
    )
    new_job = _job(
        job_id=None,
        title="DevOps Engineer",
        description="We need a DevOps engineer with Kubernetes and Terraform skills.",
    )
    result = engine.check(new_job, [], [existing])
    assert not result.is_duplicate


def test_exact_candidate_in_fuzzy_list_skipped(engine):
    # Same fingerprint job is in the fuzzy list — should not create a second match
    existing = _job(job_id=3)
    new_job = _job(job_id=None)
    # fuzzy_candidates contains the same job (exact fp) — must be skipped
    result = engine.check(new_job, [], [existing])
    # Should not find a fuzzy match since fps are equal and we skip those
    assert not result.is_duplicate


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_anonymous_company_different_jobs_not_duplicate(engine):
    """Different jobs at anonymous/empty company must NOT be linked."""
    j1 = _job(
        job_id=1,
        company="",
        title="DevOps Engineer",
        description=(
            "Kubernetes cluster management, CI/CD pipelines, Terraform IaC, "
            "Ansible automation, AWS infrastructure."
        ),
    )
    j2 = _job(
        job_id=None,
        company="",
        title="Data Scientist",
        description=(
            "Machine learning model training, Python, TensorFlow, statistics, "
            "feature engineering, neural networks, pandas."
        ),
    )
    result = engine.check(j2, [], [j1])
    assert not result.is_duplicate


def test_anonymous_company_entreprise_anonyme_not_duplicate(engine):
    """France Travail often uses 'Entreprise anonyme'; unrelated jobs must not match."""
    j1 = _job(
        job_id=2,
        company="Entreprise anonyme",
        title="Développeur Java",
        description=(
            "Spring Boot, microservices, JPA Hibernate, PostgreSQL, REST APIs, "
            "Maven, JUnit tests, Agile Scrum."
        ),
    )
    j2 = _job(
        job_id=None,
        company="Entreprise anonyme",
        title="Ingénieur Réseaux",
        description=(
            "Administration réseau Cisco, BGP OSPF, VLAN, firewall, VPN, "
            "supervision Nagios, datacenter, on-call."
        ),
    )
    result = engine.check(j2, [], [j1])
    assert not result.is_duplicate


def test_different_companies_title_subset_not_duplicate(engine):
    """'DevOps' (short) vs 'DevOps Engineer Senior Kubernetes' at different companies.
    Different companies means different blocks; engine receives no fuzzy candidates."""
    new_job = _job(
        job_id=None,
        company="Beta Inc",
        title="DevOps",
        description="DevOps position at Beta Inc, various infra tasks.",
    )
    # Different company → empty candidate list in the real pipeline
    result = engine.check(new_job, [], [])
    assert not result.is_duplicate


def test_same_company_title_subset_different_roles_not_duplicate(engine):
    """Same company: 'DevOps' vs 'DevOps Engineer Senior Kubernetes' are different roles."""
    existing = _job(
        job_id=3,
        title="DevOps Engineer Senior Kubernetes",
        description=(
            "Lead a team of 5 engineers, architect multi-cloud Kubernetes platforms, "
            "define SLOs and SLAs, mentor junior engineers, 7+ years required."
        ),
    )
    new_job = _job(
        job_id=None,
        title="DevOps",
        description=(
            "Junior DevOps position. First experience welcome. "
            "Learn CI/CD and Docker basics. Great team."
        ),
    )
    result = engine.check(new_job, [], [existing])
    assert not result.is_duplicate


def test_reworded_description_different_url_is_near_duplicate(engine):
    """Same job reposted with slightly reworded description and a different URL."""
    desc1 = (
        "Nous cherchons un ingénieur DevOps pour gérer nos clusters Kubernetes "
        "et pipelines CI/CD GitLab. Expérience Terraform et Ansible indispensable. "
        "Stack AWS, supervision Datadog, astreinte légère. Télétravail 3j/semaine."
    )
    desc2 = (
        "Nous recherchons un ingénieur DevOps pour superviser nos clusters Kubernetes "
        "et pipelines CI/CD GitLab. Expérience avec Terraform et Ansible requise. "
        "Environnement AWS, monitoring Datadog, astreintes. Poste en télétravail 3j."
    )
    existing = _job(
        job_id=7,
        title="Ingénieur DevOps H/F",
        company="Acme SAS",
        description=desc1,
        url="https://example.com/job/1",
    )
    new_job = _job(
        job_id=None,
        title="Ingénieur DevOps",
        company="Acme SAS",
        description=desc2,
        url="https://example.com/job/2",
    )
    result = engine.check(new_job, [], [existing])
    assert result.is_duplicate
    assert result.reason == "fuzzy"


def test_thresholds_from_settings():
    # Very strict thresholds → no fuzzy match for moderately-similar jobs
    strict = DedupEngine(_settings(fuzzy_title_threshold=0.99, fuzzy_desc_threshold=0.99))
    existing = _job(
        job_id=2,
        title="DevOps Engineer",
        description="We need a DevOps engineer with Kubernetes and Terraform skills.",
    )
    new_job = _job(
        job_id=None,
        title="Cloud Infrastructure Engineer",
        description="Looking for a cloud engineer to manage AWS and GCP environments.",
    )
    result = strict.check(new_job, [], [existing])
    assert not result.is_duplicate
