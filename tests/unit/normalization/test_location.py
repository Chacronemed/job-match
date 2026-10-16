import pytest

from job_match.normalization.location import normalize_location, parse_department


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("92 - Nanterre", "92"),
        ("77 - Melun", "77"),
        ("75 - Paris", "75"),
        ("06 - Nice", "06"),
        ("75 - Paris 15e Arrondissement", "75"),
        ("75 - Paris (Dept.)", "75"),
        (" 69 - Lyon 1er", "69"),
        ("59-Lille", "59"),          # no spaces around the dash
        ("2A - Ajaccio", "2A"),      # Corsica
        ("2b - Bastia", "2B"),
        ("971 - Pointe-à-Pitre", "971"),  # overseas, 3 digits
    ],
)
def test_parse_department_reads_the_prefix(location, expected):
    assert parse_department(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        "Paris 15e",   # city with an arrondissement, no code
        "France",
        "Île-de-France",
        "remote",
        "",
        "75",          # code alone, no city
        "75 - ",       # dash but nothing after it
        "9 - Paris",   # single digit is not a department prefix
    ],
)
def test_parse_department_returns_none_when_unreadable(location):
    assert parse_department(location) is None


def test_normalize_location_folds_accents_and_case():
    assert normalize_location("Île-de-FRANCE") == normalize_location("ile-de-france")
