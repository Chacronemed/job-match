import pytest

from job_match.normalization.company import normalize_company


@pytest.mark.parametrize("inp,expected", [
    ("Acme Corp", "acme"),
    ("Acme SAS", "acme"),
    ("DataCo S.A.S.", "dataco"),  # dots become spaces, then suffix stripped
    ("OpenAI Inc.", "openai"),
    ("Google LLC", "google"),
    ("Société GmbH", "societe"),
    ("Startup", "startup"),     # no suffix → unchanged
    ("TotalEnergies SA", "totalenergies"),
])
def test_normalize_company(inp, expected):
    assert normalize_company(inp) == expected


def test_same_company_different_suffixes():
    assert normalize_company("Acme SAS") == normalize_company("Acme SA")


def test_accent_folding():
    assert normalize_company("Société Générale SA") == "societe generale"
