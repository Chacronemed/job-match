import pytest

from job_match.domain.models import ContractType
from job_match.normalization.contract import parse_contract_type


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CDI", ContractType.CDI),
        ("Contrat à durée indéterminée", ContractType.CDI),
        ("Permanent", ContractType.CDI),
        ("CDD", ContractType.CDD),
        ("Contrat à durée déterminée de 6 mois", ContractType.CDD),
        ("Fixed-term contract", ContractType.CDD),
        ("Stage de fin d'études", ContractType.STAGE),
        ("Internship", ContractType.STAGE),
        ("Alternance", ContractType.ALTERNANCE),
        ("Contrat de professionnalisation", ContractType.ALTERNANCE),
        ("Apprenticeship", ContractType.ALTERNANCE),
        ("Intérim", ContractType.INTERIM),
        ("Temporary", ContractType.INTERIM),
        ("Freelance", ContractType.FREELANCE),
        ("Indépendant", ContractType.FREELANCE),
        ("Portage salarial", ContractType.FREELANCE),
    ],
)
def test_recognised_forms(text, expected):
    assert parse_contract_type(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "Full-time",        # working time, not a contract type
        "Temps plein",
        "Part-time",
        "Contract",         # Adzuna's label: ambiguous in France, so no guess
        "",
        None,
        "Poste de DevOps",
    ],
)
def test_unrecognised_forms_stay_unknown(text):
    assert parse_contract_type(text) is ContractType.UNKNOWN


def test_first_text_wins():
    """Call order encodes trust: the source's own field beats the body text."""
    assert parse_contract_type("CDI", "ancien poste en CDD") is ContractType.CDI


def test_falls_through_to_the_next_text_when_the_first_says_nothing():
    assert parse_contract_type("Full-time", "Ce poste est un CDI") is ContractType.CDI


def test_skips_empty_texts():
    assert parse_contract_type(None, "", "stage") is ContractType.STAGE


def test_matching_is_whole_word():
    """"cdi" must not match inside another word."""
    assert parse_contract_type("Expert en cdiscount") is ContractType.UNKNOWN


def test_accents_and_case_do_not_matter():
    assert parse_contract_type("INTÉRIM") is ContractType.INTERIM
