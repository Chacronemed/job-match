"""`location_scope` is the one geography setting: it drives the queries and the gate.

Parsed into `FTSearch.departments`, where an empty list means "the whole country" — the
form every source and the location gate already understood.
"""
import logging

import pytest
import yaml

from job_match.config.loader import ConfigError, _parse_location_scope, load_profile

BASE = {
    "candidate": {"experience_years": 2},
    "skills": {"preferred": [{"name": "kubernetes", "weight": 3}]},
    "filters": {"contract_types": ["CDI"]},
    "ft_search": {"keywords": ["devops"]},
}


def _write(tmp_path, extra: dict, ft_extra: dict | None = None):
    raw = {**BASE, **extra}
    raw["ft_search"] = {**BASE["ft_search"], **(ft_extra or {})}
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return load_profile(path)


# ---------------------------------------------------------------------------
# The national forms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["france", "FRANCE", "France", "fr", "national", "all", ""])
def test_a_national_scope_means_no_department_list(value):
    assert _parse_location_scope({"location_scope": value}, {}, "test") == []


def test_a_national_scope_is_national_on_the_profile(tmp_path):
    profile = _write(tmp_path, {"location_scope": "france"})
    assert profile.ft_search.departments == []
    assert profile.ft_search.national is True


# ---------------------------------------------------------------------------
# The restricted form
# ---------------------------------------------------------------------------

def test_a_list_restricts_the_scope(tmp_path):
    profile = _write(tmp_path, {"location_scope": ["75", "92", "2a"]})
    assert profile.ft_search.departments == ["75", "92", "2A"]  # codes normalized
    assert profile.ft_search.national is False


def test_numeric_yaml_values_become_strings():
    assert _parse_location_scope({"location_scope": [75, 92]}, {}, "test") == ["75", "92"]


def test_a_single_code_as_a_string_is_a_restricted_scope():
    assert _parse_location_scope({"location_scope": "75"}, {}, "test") == ["75"]


def test_blank_entries_are_dropped():
    assert _parse_location_scope({"location_scope": ["75", "", "  "]}, {}, "test") == ["75"]


def test_a_nonsense_scope_is_a_config_error():
    with pytest.raises(ConfigError, match="location_scope"):
        _parse_location_scope({"location_scope": {"departments": ["75"]}}, {}, "test")


# ---------------------------------------------------------------------------
# One key, read from either level, with the old list as a fallback
# ---------------------------------------------------------------------------

def test_the_key_is_also_accepted_inside_ft_search(tmp_path):
    profile = _write(tmp_path, {}, {"location_scope": ["33"]})
    assert profile.ft_search.departments == ["33"]


def test_the_top_level_key_wins_over_the_nested_one():
    scope = _parse_location_scope(
        {"location_scope": "france"}, {"location_scope": ["75"]}, "test"
    )
    assert scope == []


def test_a_legacy_departments_list_still_loads(tmp_path, caplog):
    """An older profile (or an un-updated PROFILE_YAML secret) keeps working."""
    with caplog.at_level(logging.DEBUG):
        profile = _write(tmp_path, {}, {"departments": ["75", "92"]})

    assert profile.ft_search.departments == ["75", "92"]
    assert profile.ft_search.national is False
    assert "deprecated" in caplog.text


def test_location_scope_wins_over_a_legacy_departments_list(tmp_path):
    profile = _write(tmp_path, {"location_scope": "france"}, {"departments": ["75"]})
    assert profile.ft_search.departments == []


def test_no_geography_at_all_is_national(tmp_path):
    profile = _write(tmp_path, {})
    assert profile.ft_search.national is True


def test_the_committed_example_profile_is_national(tmp_path):
    from pathlib import Path
    profile = load_profile(Path("config/profile.example.yaml"))
    assert profile.ft_search.national is True
    assert profile.filters.locations == []  # geography lives in location_scope only
