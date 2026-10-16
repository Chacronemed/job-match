"""French, foreign, or unreadable — the three answers a national scope needs.

With `location_scope: france` there is no department list to compare a location against,
so the gate asks a different question: can we see that this job is somewhere else?
"""
import pytest

from job_match.normalization.fr_geo import FRENCH_DEPARTMENTS
from job_match.normalization.location import (
    block_location,
    department_of,
    french_location,
    is_french_department,
)

# ---------------------------------------------------------------------------
# is_french_department
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["01", "06", "75", "95", "2A", "2b", "971", "976", "988"])
def test_real_codes_are_french(code):
    assert is_french_department(code) is True


@pytest.mark.parametrize("code", ["00", "20", "96", "98", "99", "100", "", "XX"])
def test_everything_else_is_not(code):
    """France Travail files offers abroad under 99, and 20 became 2A/2B in 1976."""
    assert is_french_department(code) is False


def test_the_table_covers_metropolitan_france_and_the_dom():
    assert len(FRENCH_DEPARTMENTS) == 108  # 94 + Corsica's two + 8 overseas + 4 collectivities


# ---------------------------------------------------------------------------
# french_location: clearly here
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "92 - Nanterre",          # France Travail, a department we used to query
        "13 - Marseille",         # one we did not
        "2A - Ajaccio",
        "971 - Pointe-à-Pitre",
        "Lyon",                   # Jooble / Adzuna style
        "Nanterre",
        "Île-de-France",
        "Bretagne",               # a region resolves to its departments
        "Paris 15e",
        "France",
        "Toulouse, France",
    ],
)
def test_clearly_in_france(location):
    assert french_location(location) is True


# ---------------------------------------------------------------------------
# french_location: clearly elsewhere
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "Bruxelles, Belgique",
        "Belgium",
        "99 - ALLEMAGNE",         # France Travail's abroad code
        "99 - ROYAUME UNI",
        "London, UK",
        "Genève",
        "Luxembourg",
        "Madrid, Espagne",
        "Montréal, Canada",
        "New York",
        "Lille, Belgique",        # the country wins over the French city name
    ],
)
def test_clearly_abroad(location):
    assert french_location(location) is False


# ---------------------------------------------------------------------------
# french_location: no idea — and that is not a rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    ["", "   ", "Télétravail", "Remote", "Saint-Machin-sur-Glane", "Siège social"],
)
def test_unknown_stays_unknown(location):
    assert french_location(location) is None


def test_a_foreign_marker_must_be_a_whole_word():
    """"Rome" is a country-level marker; "Romechamp" must not trip it."""
    assert french_location("Romechamp") is None
    assert french_location("Rome, Italie") is False


# ---------------------------------------------------------------------------
# department_of: for the run summary, not for gating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("92 - Nanterre", "92"),
        ("971 - Pointe-à-Pitre", "971"),
        ("2A - Ajaccio", "2A"),
        ("Lyon", "69"),
        ("Paris 15e", "75"),
        ("Bretagne", None),        # a region is several departments, so no single one
        ("Île-de-France", None),
        ("France", None),
        ("", None),
        ("Télétravail", None),
        ("Saint-Machin-sur-Glane", None),
    ],
)
def test_department_of(location, expected):
    assert department_of(location) == expected


# ---------------------------------------------------------------------------
# block_location: the dedup blocking key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("35 - Rennes", "35"),
        ("Rennes, France", "35"),      # same key across sources
        ("Rennes", "35"),
        ("75 - Paris", "75"),
        ("Paris 15e", "75"),
        ("Bretagne", "bretagne"),      # a region has no single department
        ("France", "france"),
        ("Teletravail", "teletravail"),
        ("", ""),
    ],
)
def test_block_location(location, expected):
    assert block_location(location) == expected


def test_two_departments_never_share_a_block():
    assert block_location("35 - Rennes") != block_location("75 - Paris")
