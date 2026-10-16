import pytest

from job_match.normalization.location import (
    departments_for,
    normalize_location,
    parse_department,
)


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


# ---------------------------------------------------------------------------
# departments_for — Jooble and Adzuna send names, not "NN - City"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("92 - Nanterre", {"92"}),          # the prefix wins, no lookup needed
        ("Nanterre", {"92"}),               # bare city (Jooble)
        ("Nanterre, Hauts-de-Seine", {"92"}),   # city + department (Adzuna)
        ("NANTERRE", {"92"}),               # case folded
        ("Boulogne-Billancourt", {"92"}),
        ("Boulogne-sur-Mer", {"62"}),       # longest name wins over the shorter one
        ("Saint-Quentin-en-Yvelines", {"78"}),
        ("Sophia Antipolis", {"06"}),
        ("Marseille", {"13"}),
        ("Melun", {"77"}),
        ("Paris 15e", {"75"}),      # an arrondissement is still Paris
        ("Cesson-Sévigné", {"35"}),
    ],
)
def test_departments_for_resolves_a_place_name(location, expected):
    assert departments_for(location) == expected


def test_departments_for_a_region_returns_all_its_departments():
    assert departments_for("Île-de-France") == {"75", "77", "78", "91", "92", "93", "94", "95"}


def test_departments_for_folds_accents_in_a_region_name():
    assert departments_for("ile de france") == departments_for("Île-de-France")


def test_departments_for_collects_every_place_mentioned():
    assert departments_for("Lyon ou Toulouse") == {"69", "31"}


@pytest.mark.parametrize(
    "location",
    [
        "France",            # a country is not a place we can gate on
        "",
        "Télétravail",
        "Zurich",            # not in the table
        "Remote - Europe",
    ],
)
def test_departments_for_is_empty_when_unresolvable(location):
    """Empty means "cannot tell". The gate keeps those jobs."""
    assert departments_for(location) == frozenset()
