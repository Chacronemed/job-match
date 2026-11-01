"""The master CV (M26): parsing, the validator's rules and the JSON the Worker reads."""
import json

import pytest

from job_match.config.schema import ConfigError, DocumentsConfig
from job_match.documents.master import parse_contact, parse_master, to_json
from job_match.documents.validate import validate_master

VOCAB = ("kubernetes", "terraform", "python", "aws")
ALIASES = {"kubernetes": ["k8s"], "ci/cd": ["cicd"]}
PROFILE_SKILLS = ("gcp",)


def _errors(master_raw, contact_raw, config=None):
    return validate_master(
        parse_master(master_raw), parse_contact(contact_raw), config or DocumentsConfig(),
        VOCAB, ALIASES, PROFILE_SKILLS,
    )


def test_a_clean_master_has_no_error(master_raw, contact_raw):
    assert _errors(master_raw, contact_raw) == []


def test_skills_resolve_through_aliases_the_profile_or_a_tool(master_raw, contact_raw):
    master_raw["skills"] += [{"id": "cobol", "label": "COBOL"},
                             {"id": "helm", "label": "Helm again"}]
    errs = _errors(master_raw, contact_raw)
    assert len(errs) == 2
    assert any("'cobol'" in e and "nor a tool" in e for e in errs)
    assert "skills: duplicate id 'helm'" in errs  # helm is a tool of exp1.b1, listed twice


def test_available_from_is_a_day(master_raw, contact_raw):
    master_raw["available_from"] = "2027-01"
    assert "available_from must be YYYY-MM-DD" in _errors(master_raw, contact_raw)
    with pytest.raises(ConfigError, match="missing available_from"):
        parse_master({k: v for k, v in master_raw.items() if k != "available_from"})


def test_forbidden_phrases_are_found_whatever_the_case_or_accents(master_raw, contact_raw):
    bullet = master_raw["experiences"][0]["bullets"][0]
    bullet["text"] = "Mises en production SANS REGRESSION sur 12 mois."
    master_raw["skill_groups"][0]["items"].append("audit 63 Dimensions")
    errs = _errors(master_raw, contact_raw)
    assert any("exp1.b1: forbidden phrase 'sans regression'" in e for e in errs)
    assert any("skill_groups.Cloud: forbidden phrase '63 dimensions'" in e for e in errs)
    assert len(errs) == 2


def test_contact_details_inside_the_master_are_refused(master_raw, contact_raw):
    master_raw["headline"] = "Jean Trapmarker, DevOps"
    master_raw["extras"].append("Me joindre : jean.trap@example.com ou +33 6 12 34 56 78")
    master_raw["experiences"][1]["bullets"][0]["text"] = "Voir https://trap.example.com/cv"
    errs = _errors(master_raw, contact_raw)
    assert any("headline: contains the candidate's name" in e for e in errs)
    assert any("extras[1]: contains an email" in e for e in errs)
    assert any("extras[1]: contains a phone" in e for e in errs)
    assert any("exp2.b1: contains a URL" in e for e in errs)


def test_dates_and_ids_are_checked(master_raw, contact_raw):
    master_raw["experiences"][1]["start"] = "2024-13"
    master_raw["experiences"][0]["end"] = "2024-12"
    master_raw["projects"][0]["bullets"][0]["id"] = "exp1.b1"
    errs = _errors(master_raw, contact_raw)
    assert "exp2: start must be YYYY-MM" in errs
    assert "exp1: end before start" in errs
    assert "duplicate id 'exp1.b1'" in errs


def test_parse_errors_name_the_place(master_raw, contact_raw):
    del master_raw["experiences"][0]["bullets"][1]["text"]
    with pytest.raises(ConfigError, match="exp1.b2: missing text"):
        parse_master(master_raw)
    with pytest.raises(ConfigError, match="unknown keys: city"):
        parse_contact({**contact_raw, "city": "Lyon"})
    with pytest.raises(ConfigError, match="at least one experience"):
        parse_master({**master_raw, "experiences": []})


def test_the_json_for_r2_is_sorted_and_the_master_carries_no_contact(master_raw, contact_raw):
    text = to_json(parse_master(master_raw))
    data = json.loads(text)
    assert list(data) == sorted(data)
    ids = [b["id"] for e in data["experiences"] for b in e["bullets"]]
    assert ids == ["exp1.b1", "exp1.b2", "exp2.b1"]
    assert data["skills"][0] == {"id": "kubernetes", "label": "Kubernetes"}
    assert data["available_from"] == "2027-01-15"
    for value in contact_raw.values():
        assert value not in text
    assert json.loads(to_json(parse_contact(contact_raw)))["email"] == "jean.trap@example.com"
