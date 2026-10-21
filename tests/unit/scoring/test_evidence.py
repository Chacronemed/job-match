"""What the "Pourquoi cette offre ?" panel reads: evidence sentences, weights, unlisted
skills and the experience basis, all fixed at scoring time and kept in the breakdown JSON."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from job_match.config.loader import (
    apply_skill_overrides,
    load_settings,
    load_skill_vocabulary,
)
from job_match.config.schema import (
    Candidate,
    ConfigError,
    Filters,
    FTSearch,
    Profile,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import (
    ContractType,
    ExperienceBasis,
    ExperienceStatus,
    Job,
    WorkplaceType,
)
from job_match.eligibility.gate import evaluate
from job_match.experience.parser import parse
from job_match.normalization.skills import SNIPPET_MAX, find_skill, snippet
from job_match.persistence.repositories import _breakdown_from_json, _breakdown_to_json
from job_match.scoring.engine import ScoringEngine
from job_match.scoring.native import NativeRuleScorer

ALIASES = {"kubernetes": ["k8s"], "gitlab ci": ["gitlab-ci"]}
SETTINGS = Settings(base_score=50, title_bonus=10, seniority_min_years={"senior": 5})
REPO = Path(__file__).resolve().parents[3]


def _job(title: str = "Ingénieur DevOps", description: str = "") -> Job:
    return Job(
        source="france_travail", source_job_id="1", title=title, company="ACME",
        location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI, description=description,
        url="https://example.com/1", collected_at=datetime(2026, 10, 1),
    )


def _profile(preferred=(("kubernetes", 3),), negative=(("sap", -5),), years=2) -> Profile:
    return Profile(
        candidate=Candidate(experience_years=years),
        skills=Skills(
            preferred=[SkillWeight(n, w) for n, w in preferred],
            negative=[SkillWeight(n, w) for n, w in negative],
        ),
        filters=Filters(),
        ft_search=FTSearch(keywords=[]),
        scoring=ScoringConfig(),
    )


# --- find_skill / snippet ---------------------------------------------------------

def test_find_skill_returns_the_earliest_form_whole_word():
    text = "Vous gérez du K8s puis du kubernetes."
    m = find_skill(text, "kubernetes", ALIASES)
    assert m is not None and m.group(0) == "K8s"
    assert find_skill("javascript only", "java", {}) is None


def test_snippet_is_the_sentence_and_keeps_dotted_names_whole():
    text = "Nous recrutons. Stack: node.js et K8s sur AWS; bonus Terraform.\n- Docker"
    m = find_skill(text, "kubernetes", ALIASES)
    assert snippet(text, m.start(), m.end()) == "Stack: node.js et K8s sur AWS"


def test_snippet_caps_a_long_sentence_around_the_match():
    text = "mot " * 100 + "kubernetes " + "fin " * 100
    m = find_skill(text, "kubernetes", {})
    out = snippet(text, m.start(), m.end())
    assert len(out) <= SNIPPET_MAX
    assert "kubernetes" in out and out.startswith("…") and out.endswith("…")


# --- scorer ------------------------------------------------------------------------

def test_scorer_records_evidence_weights_and_unlisted_skills():
    job = _job(description="Cluster K8s. Pipelines GitLab-CI et Helm. Un peu de SAP.")
    scorer = NativeRuleScorer(ALIASES, ("kubernetes", "gitlab ci", "helm", "sap", "kafka"))
    r = scorer.score(job, _profile(), SETTINGS)
    assert r.weights == {"kubernetes": 3, "sap": -5}
    assert r.evidence["kubernetes"] == "Cluster K8s"
    assert r.evidence["sap"] == "Un peu de SAP"
    # Profile skills (preferred or negative) are never "unlisted"; absent ones neither.
    assert r.unlisted == {
        "gitlab ci": "Pipelines GitLab-CI et Helm",
        "helm": "Pipelines GitLab-CI et Helm",
    }
    assert r.score == 50 + 3 - 5


def test_unlisted_skills_never_change_the_score():
    job = _job(description="Kafka, Helm, Kubernetes.")
    with_vocab = NativeRuleScorer({}, ("kafka", "helm")).score(job, _profile(), SETTINGS)
    without = NativeRuleScorer({}).score(job, _profile(), SETTINGS)
    assert with_vocab.score == without.score
    assert set(with_vocab.unlisted) == {"kafka", "helm"}


# --- experience basis --------------------------------------------------------------

@pytest.mark.parametrize("title, description, basis, years, sentence", [
    ("DevOps", "Profil recherché. Au moins 3 ans d'expérience en production.",
     ExperienceBasis.EXPLICIT, 3.0, "Au moins 3 ans d'expérience en production"),
    ("DevOps Senior", "Vous aimez Linux.",
     ExperienceBasis.SENIORITY, 5.0, "DevOps Senior"),
    ("DevOps", "Une première expérience réussie est un plus.",
     ExperienceBasis.UNKNOWN, None, "Une première expérience réussie est un plus"),
    ("DevOps", "Vous aimez Linux.", ExperienceBasis.NOT_MENTIONED, None, None),
])
def test_gate_reports_where_required_years_came_from(title, description, basis, years,
                                                      sentence):
    job = _job(title, description)
    result = evaluate(job, parse(description), _profile(years=10), SETTINGS)
    assert (result.basis, result.required_years, result.basis_evidence) == (
        basis, years, sentence
    )


def test_an_explicit_number_beats_a_seniority_keyword():
    description = "Poste senior. Minimum 2 ans d'expérience."
    result = evaluate(_job("DevOps", description), parse(description), _profile(), SETTINGS)
    assert result.basis is ExperienceBasis.EXPLICIT and result.required_years == 2.0


def test_parser_keeps_the_sentence_from_the_original_text():
    req = parse("Société fondée en 2010. Vous avez 3 ans d'expérience (hors stage).")
    assert req.status is ExperienceStatus.ELIGIBLE
    assert req.sentence == "Vous avez 3 ans d'expérience (hors stage)"
    assert req.excludes_apprenticeship


# --- engine + persistence ----------------------------------------------------------

def test_breakdown_carries_the_panel_data_and_survives_the_json_round_trip():
    description = "Minimum 3 ans d'expérience hors stage. Cluster K8s, Helm."
    job = _job(description=description)
    req = parse(description)
    profile = _profile()
    elig = evaluate(job, req, profile, SETTINGS)
    engine = ScoringEngine([NativeRuleScorer(ALIASES, ("helm",))])
    bd = engine.score(job, profile, SETTINGS, elig, req)
    assert bd.experience_detail == {
        "required_years": 3.0,
        "basis": "explicit",
        "sentence": "Minimum 3 ans d'expérience hors stage",
        "excludes_apprenticeship": True,
    }
    back = _breakdown_from_json(_breakdown_to_json(bd))
    assert back == bd


def test_an_old_breakdown_without_the_new_keys_still_loads():
    old = json.dumps({"eligible": True, "experience": "ELIGIBLE", "score": 60})
    bd = _breakdown_from_json(old)
    assert (bd.evidence, bd.weights, bd.unlisted, bd.experience_detail) == ({}, {}, {}, {})


# --- overrides and vocabulary ------------------------------------------------------

def test_apply_skill_overrides_adds_preferred_skills_once():
    profile = _profile()
    merged = apply_skill_overrides(profile, ["helm", "Helm", "kubernetes", "sap"], 2)
    assert [(s.name, s.weight) for s in merged.skills.preferred] == [
        ("kubernetes", 3), ("helm", 2)
    ]
    assert [s.name for s in merged.skills.negative] == ["sap"]
    assert [s.name for s in profile.skills.preferred] == ["kubernetes"]  # copy, not mutated
    assert apply_skill_overrides(profile, [], 2) is profile


def test_an_override_is_scored_and_leaves_the_unlisted_set():
    job = _job(description="Helm charts.")
    scorer = NativeRuleScorer({}, ("helm",))
    before = scorer.score(job, _profile(), SETTINGS)
    after = scorer.score(job, apply_skill_overrides(_profile(), ["helm"], 2), SETTINGS)
    assert "helm" in before.unlisted and "helm" not in after.unlisted
    assert after.score == before.score + 2 and after.weights["helm"] == 2


def test_committed_vocabulary_loads_lowercase_and_unique():
    vocab = load_skill_vocabulary(REPO / "config" / "skill_vocabulary.yaml")
    assert len(vocab) >= 30 and len(set(vocab)) == len(vocab)
    assert all(v == v.lower() for v in vocab)
    assert "chef" not in vocab and "go" not in vocab  # everyday words, see the file header


def test_vocabulary_must_be_a_list_of_strings(tmp_path):
    path = tmp_path / "v.yaml"
    path.write_text("helm: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_skill_vocabulary(path)
    assert load_skill_vocabulary(tmp_path / "missing.yaml") == ()


def test_override_weight_is_read_and_validated(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("scoring:\n  override_weight: 4\n", encoding="utf-8")
    assert load_settings(path).scoring.override_weight == 4
    path.write_text("scoring:\n  override_weight: 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="override_weight"):
        load_settings(path)
    assert load_settings(REPO / "config" / "settings.yaml").scoring.override_weight == 2


def test_no_vocabulary_term_is_another_terms_alias():
    from job_match.config.loader import load_aliases
    from job_match.normalization.skills import skill_forms

    aliases = load_aliases(REPO / "config" / "aliases.yaml")
    vocab = load_skill_vocabulary(REPO / "config" / "skill_vocabulary.yaml")
    for term in vocab:
        others = {f for v in vocab if v != term for f in skill_forms(v, aliases)}
        assert term not in others, term  # e.g. "kibana" is an alias of elk, not a term


def test_gitlab_ci_and_kibana_resolve_to_the_profile_spelling():
    from job_match.config.loader import load_aliases

    aliases = load_aliases(REPO / "config" / "aliases.yaml")
    assert find_skill("Pipelines GitLab-CI et GitLab CI/CD", "gitlab", aliases)
    assert find_skill("Dashboards Kibana", "elk", aliases)
