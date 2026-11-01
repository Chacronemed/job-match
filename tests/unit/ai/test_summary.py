"""The anonymous skills summary (ADR 0016 §6): only the allow-listed keys, nothing personal."""
import json
import re

from job_match.ai.summary import KEYS, skills_summary
from job_match.config.loader import _parse_profile

# A profile full of traps: every personal value carries a marker that must not come out.
TRAP = {
    "name": "Jean Trapmarker",
    "email": "jean.trap@example.com",
    "phone": "+33 6 12 34 56 78",
    "city": "Lyon-Trapville",
    "notes": "https://cv.example.com/trap.pdf",
    "location_scope": ["69", "38"],
    "candidate": {"experience_years": 2, "name": "Trap Again", "email": "x@trap.io"},
    "skills": {
        "preferred": [
            {"name": "Terraform", "weight": 3},
            {"name": "kubernetes", "weight": 3},
            {"name": "python", "weight": 2},
            {"name": " ansible ", "weight": 1},
        ],
        "negative": [{"name": "SAP", "weight": -5}],
    },
    "filters": {"contract_types": ["CDI", "CDD"]},
    "ft_search": {"rome_codes": ["M1809"], "keywords": ["devops secret-keyword", "sre"]},
}
PERSONAL = re.compile(
    r"trap|@|\+33|\b0[1-9](?:[ .]?\d{2}){4}\b|https?://|\b(69|38|M1809)\b|secret-keyword|lyon",
    re.I,
)


def _profile(raw=TRAP):
    return _parse_profile(raw, "test")


def test_only_the_allow_listed_keys_and_nothing_personal():
    summary = skills_summary(_profile())
    assert tuple(sorted(summary)) == KEYS
    text = json.dumps(summary, ensure_ascii=False)
    assert PERSONAL.search(text) is None, text


def test_values_are_what_the_worker_prompt_expects():
    summary = skills_summary(_profile())
    assert summary["preferred"] == [
        {"name": "kubernetes", "band": "fort"},
        {"name": "terraform", "band": "fort"},
        {"name": "ansible", "band": "moyen"},
        {"name": "python", "band": "moyen"},
    ]
    assert summary["negative"] == [{"name": "sap"}]
    assert summary["experience_years"] == 2
    assert summary["contract_types"] == ["CDD", "CDI"]
    assert summary["mobility"] == "departements"  # which ones is never said


def test_a_national_scope_says_france_and_half_years_survive():
    raw = {**TRAP, "location_scope": "france", "candidate": {"experience_years": 2.5}}
    summary = skills_summary(_profile(raw))
    assert summary["mobility"] == "france"
    assert summary["experience_years"] == 2.5


def test_the_summary_is_deterministic():
    assert json.dumps(skills_summary(_profile())) == json.dumps(skills_summary(_profile()))
