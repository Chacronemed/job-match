"""The "Pourquoi cette offre ?" panel data: copied from the breakdown, never recomputed."""
from datetime import datetime

from job_match.dashboard.data import EVIDENCE_MAX, why_entry
from job_match.domain.models import (
    ContractType,
    Eligibility,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    ScoringBreakdown,
    WorkplaceType,
)


def _job(bd: ScoringBreakdown | None, **kw) -> Job:
    return Job(
        source="france_travail", source_job_id="1", title="DevOps", company="Acme",
        location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI, description="never exported",
        url="https://example.test/1", collected_at=datetime(2026, 10, 20),
        eligibility=Eligibility.ELIGIBLE, scoring_breakdown=bd, **kw,
    )


def _bd(**kw) -> ScoringBreakdown:
    return ScoringBreakdown(eligible=True, experience=ExperienceStatus.ELIGIBLE, score=60, **kw)


def test_why_lists_skills_unlisted_lowered_and_experience():
    bd = _bd(
        positive_matches=("kubernetes",), negative_matches=("sap",),
        missing_preferences=("aws",),
        evidence={"kubernetes": "Cluster K8s", "sap": "Un peu de SAP"},
        weights={"kubernetes": 3, "sap": -5},
        unlisted={"kafka": "Kafka en prod", "helm": "Charts Helm"},
        experience_detail={"required_years": 3.0, "basis": "explicit",
                           "sentence": "Minimum 3 ans", "excludes_apprenticeship": True},
    )
    why = why_entry(_job(bd))
    assert why == {
        "skills": [{"name": "kubernetes", "weight": 3, "snippet": "Cluster K8s"}],
        "unlisted": [{"name": "helm", "snippet": "Charts Helm"},
                     {"name": "kafka", "snippet": "Kafka en prod"}],
        "lowered": [{"name": "sap", "weight": -5, "snippet": "Un peu de SAP"}],
        "experience": {"required_years": 3.0, "basis": "explicit",
                       "sentence": "Minimum 3 ans", "excludes_apprenticeship": True},
    }
    assert "never exported" not in str(why)


def test_an_old_row_has_no_basis_and_falls_back_on_the_parser():
    exp = ExperienceRequirement(status=ExperienceStatus.ELIGIBLE, min_years=2.0,
                                evidence="2 ans", excludes_apprenticeship=True)
    why = why_entry(_job(_bd(positive_matches=("docker",)), experience=exp))
    assert why["skills"] == [{"name": "docker", "weight": None, "snippet": None}]
    assert why["experience"] == {"required_years": 2.0, "basis": None, "sentence": None,
                                 "excludes_apprenticeship": True}


def test_evidence_is_capped():
    bd = _bd(positive_matches=("docker",), evidence={"docker": "x" * 500})
    snippet = why_entry(_job(bd))["skills"][0]["snippet"]
    assert len(snippet) == EVIDENCE_MAX and snippet.endswith("…")


def test_no_breakdown_gives_an_empty_panel():
    assert why_entry(_job(None)) == {"skills": [], "unlisted": [], "lowered": [],
                                     "experience": None}
