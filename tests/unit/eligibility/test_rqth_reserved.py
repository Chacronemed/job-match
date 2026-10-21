"""Offers reserved for RQTH / BOETH holders are rejected; inclusive wording never is.

The inclusive sentences are the forms measured on the local DB (2026-10-21: 122 of 337
eligible/stretch jobs carry one, none carries a restrictive one), company names removed.
"""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.config.loader import load_settings
from job_match.config.schema import (
    Candidate,
    ConfigError,
    EligibilityConfig,
    Filters,
    FTSearch,
    Profile,
    ScoringConfig,
    Settings,
    Skills,
)
from job_match.domain.models import (
    ContractType,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RejectionReason,
    WorkplaceType,
)
from job_match.eligibility.gate import evaluate
from job_match.eligibility.reserved import rqth_reserved

REPO = Path(__file__).resolve().parents[3]

RESTRICTIVE = [
    "Poste réservé aux travailleurs handicapés (RQTH).",
    "Ce poste est réservé aux personnes en situation de handicap.",
    "Profil recherché : Bac+3 en informatique. RQTH obligatoire.",
    "La RQTH est exigée pour ce recrutement.",
    "Candidature recevable uniquement pour les titulaires d'une RQTH.",
    "Vous êtes titulaire de la RQTH et justifiez d'une première expérience.",
    "Recrutement ouvert uniquement aux bénéficiaires de l'obligation d'emploi (BOETH).",
    "Dans le cadre de notre politique handicap, ce poste réservé est accessible sur "
    "présentation de la RQTH.",
    "- Poste réservé RQTH",
]

INCLUSIVE = [
    "Nos postes sont ouverts aux personnes en situation de handicap.",
    "Nos recrutements sont fondés sur les compétences, sans distinction d'origine, d'âge ou de "
    "genre, et tous nos postes sont ouverts aux personnes en situation de handicap.",
    "L'ensemble des postes à pourvoir sont accessibles aux personnes en situation de handicap.",
    "Le groupe encourage une culture inclusive dans un cadre multiculturel et handi-accueillant.",
    "En tant qu'organisateur de forums de recrutement, Talents Handicap accompagne de très "
    "nombreuses entreprises & organisations en France dans leurs recrutements de "
    "collaborateurs en situation de handicap.",
    "Parce que nous sommes persuadés que chaque talent compte, nous valorisons et encourageons "
    "les candidatures de personnes en situation de handicap pour nos opportunités d'emploi.",
    "Une référente handicap vous accompagne lors de votre intégration.",
    "Nous sommes une entreprise Handi-accueillante, signataire de la Charte de la diversité.",
]

GUARDS = [
    "Ce poste n'est pas réservé aux travailleurs handicapés.",
    "Aide au recrutement réservée uniquement aux bénéficiaires du RSA.",
    "Poste réservé aux alternants. Nos postes sont ouverts aux personnes en situation de "
    "handicap.",
    "Accès au parking réservé aux salariés.",
]


@pytest.mark.parametrize("sentence", RESTRICTIVE)
def test_restrictive_wording_is_detected(sentence):
    assert rqth_reserved(f"Ingénieur DevOps H/F. Vous gérez Kubernetes. {sentence}")


@pytest.mark.parametrize("sentence", INCLUSIVE + GUARDS)
def test_inclusive_wording_and_guards_never_match(sentence):
    assert rqth_reserved(f"Ingénieur DevOps H/F. Vous gérez Kubernetes. {sentence}") is None


def test_the_matching_sentence_is_returned():
    text = "Mission DevOps sur AWS. Poste réservé aux travailleurs handicapés. Télétravail."
    assert rqth_reserved(text) == "Poste réservé aux travailleurs handicapés"


def _job(description: str) -> Job:
    return Job(
        source="france_travail", source_job_id="1", title="Ingénieur DevOps H/F",
        company="Acme", location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI, description=description,
        url="https://example.test/1", collected_at=datetime(2026, 10, 21, tzinfo=UTC),
    )


PROFILE = Profile(
    candidate=Candidate(experience_years=2), skills=Skills(), filters=Filters(),
    ft_search=FTSearch(keywords=[]), scoring=ScoringConfig(),
)
REQ = ExperienceRequirement(status=ExperienceStatus.NOT_MENTIONED)


def test_gate_rejects_a_reserved_offer_when_the_setting_is_on():
    settings = Settings(eligibility=EligibilityConfig(exclude_rqth_reserved=True))
    result = evaluate(_job(RESTRICTIVE[0]), REQ, PROFILE, settings)
    assert not result.eligible
    assert RejectionReason.RESERVED_RQTH in result.reasons


@pytest.mark.parametrize("sentence", INCLUSIVE)
def test_gate_keeps_inclusive_offers(sentence):
    settings = Settings(eligibility=EligibilityConfig(exclude_rqth_reserved=True))
    result = evaluate(_job(sentence), REQ, PROFILE, settings)
    assert RejectionReason.RESERVED_RQTH not in result.reasons


def test_setting_off_by_default_keeps_the_offer():
    result = evaluate(_job(RESTRICTIVE[0]), REQ, PROFILE, Settings())
    assert RejectionReason.RESERVED_RQTH not in result.reasons


def test_committed_settings_turn_it_on_and_the_value_must_be_a_bool(tmp_path):
    assert load_settings(REPO / "config" / "settings.yaml").eligibility.exclude_rqth_reserved
    path = tmp_path / "settings.yaml"
    path.write_text("eligibility:\n  exclude_rqth_reserved: \"yes\"\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="exclude_rqth_reserved"):
        load_settings(path)
    path.write_text("strong_threshold: 70\n", encoding="utf-8")
    assert load_settings(path).eligibility.exclude_rqth_reserved is False
