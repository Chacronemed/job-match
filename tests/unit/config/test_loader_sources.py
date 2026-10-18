from pathlib import Path

import pytest

from job_match.config.loader import load_settings
from job_match.config.schema import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_sources_defaults_to_france_travail_only(tmp_path):
    s = load_settings(_write(tmp_path, "strong_threshold: 70\n"))
    assert s.sources.enabled == ["france_travail"]
    assert s.sources.regions == []
    assert s.sources.limits == {}


def test_sources_parsed(tmp_path):
    s = load_settings(
        _write(
            tmp_path,
            "sources:\n"
            "  enabled: [france_travail, jooble]\n"
            "  regions: [Île-de-France, Lyon]\n"
            "  jooble:\n    max_calls_per_run: 15\n"
            "  adzuna:\n    max_calls_per_run: 20\n",
        )
    )
    assert s.sources.enabled == ["france_travail", "jooble"]
    assert s.sources.regions == ["Île-de-France", "Lyon"]
    assert s.sources.max_calls("jooble") == 15
    assert s.sources.max_calls("adzuna") == 20


def test_published_since_days_is_parsed_per_source(tmp_path):
    s = load_settings(
        _write(tmp_path, "sources:\n  france_travail:\n    published_since_days: 7\n")
    )
    assert s.sources.published_since_days("france_travail") == 7
    assert s.sources.published_since_days("jooble") is None


def test_published_since_days_defaults_to_no_window(tmp_path):
    s = load_settings(_write(tmp_path, "sources:\n  france_travail:\n    x: 1\n"))
    assert s.sources.published_since_days("france_travail") is None
    assert s.sources.max_calls("france_travail") == 10


@pytest.mark.parametrize("value", ["5", "'3'", "true", "0", "2.5"])
def test_published_since_days_must_be_a_window_the_api_accepts(tmp_path, value):
    """France Travail's publieeDepuis takes 1, 3, 7, 14 or 31; anything else is a typo."""
    with pytest.raises(ConfigError, match="sources.france_travail.published_since_days"):
        load_settings(
            _write(tmp_path, f"sources:\n  france_travail:\n    published_since_days: {value}\n")
        )


def test_radius_km_is_parsed_per_source(tmp_path):
    s = load_settings(_write(tmp_path, "sources:\n  jooble:\n    radius_km: 50\n"))
    assert s.sources.radius_km("jooble") == 50
    assert s.sources.radius_km("adzuna") is None


@pytest.mark.parametrize("value", ["0", "-5", "'50'", "true"])
def test_radius_km_must_be_a_positive_integer(tmp_path, value):
    with pytest.raises(ConfigError, match="sources.jooble.radius_km"):
        load_settings(_write(tmp_path, f"sources:\n  jooble:\n    radius_km: {value}\n"))


def test_experience_stretch_years_defaults_to_zero(tmp_path):
    s = load_settings(_write(tmp_path, "strong_threshold: 70\n"))
    assert s.experience.stretch_years == 0


def test_experience_stretch_years_is_parsed(tmp_path):
    s = load_settings(_write(tmp_path, "experience:\n  stretch_years: 1\n"))
    assert s.experience.stretch_years == 1.0


@pytest.mark.parametrize("value", ["-1", "'1'", "true"])
def test_experience_stretch_years_must_be_a_non_negative_number(tmp_path, value):
    with pytest.raises(ConfigError, match="experience.stretch_years"):
        load_settings(_write(tmp_path, f"experience:\n  stretch_years: {value}\n"))


def test_committed_settings_stretch_one_year():
    s = load_settings(Path("config/settings.yaml"))
    assert s.experience.stretch_years == 1


def test_limits_can_be_declared_for_a_disabled_source(tmp_path):
    """Adzuna's cap is configured before it is switched on."""
    s = load_settings(
        _write(tmp_path, "sources:\n  enabled: [jooble]\n  adzuna:\n    max_calls_per_run: 20\n")
    )
    assert s.sources.is_enabled("adzuna") is False
    assert s.sources.max_calls("adzuna") == 20


def test_unconfigured_source_falls_back_to_the_default_cap(tmp_path):
    s = load_settings(_write(tmp_path, "sources:\n  enabled: [jooble]\n"))
    assert s.sources.max_calls("jooble") == 10
    assert s.sources.max_calls("jooble", default=5) == 5


def test_is_enabled(tmp_path):
    s = load_settings(_write(tmp_path, "sources:\n  enabled: [france_travail, jooble]\n"))
    assert s.sources.is_enabled("france_travail") is True
    assert s.sources.is_enabled("adzuna") is False


def test_enabled_must_be_a_list_of_strings(tmp_path):
    with pytest.raises(ConfigError, match="sources.enabled"):
        load_settings(_write(tmp_path, "sources:\n  enabled: jooble\n"))


def test_sources_must_be_a_mapping(tmp_path):
    with pytest.raises(ConfigError, match="sources must be a mapping"):
        load_settings(_write(tmp_path, "sources: [jooble]\n"))


def test_committed_settings_run_france_travail_alone():
    """The real config: Jooble is off since its city/region probes returned 0 (2026-10-18),
    Adzuna stays out until the plan is paid. Their limits stay configured for a switch-on."""
    s = load_settings(Path("config/settings.yaml"))
    assert s.sources.enabled == ["france_travail"]
    assert s.sources.is_enabled("jooble") is False
    assert s.sources.is_enabled("adzuna") is False
    assert s.sources.max_calls("jooble") == 26
    assert s.sources.max_calls("adzuna") == 20
    assert "Île-de-France" in s.sources.regions


def test_committed_settings_window_france_travail_to_three_days():
    """The run is daily: 3 days covers a missed run without refetching the whole index."""
    s = load_settings(Path("config/settings.yaml"))
    assert s.sources.published_since_days("france_travail") == 3


def test_committed_regions_are_french_regions_and_afford_two_jooble_pages_each():
    """Jooble's national query is one query per region, so every region must resolve to
    French departments and the budget must cover at least page 1 of each."""
    from job_match.normalization.location import departments_for

    s = load_settings(Path("config/settings.yaml"))
    assert len(s.sources.regions) == 13
    assert all(departments_for(region) for region in s.sources.regions)
    assert s.sources.max_calls("jooble") // len(s.sources.regions) == 2
