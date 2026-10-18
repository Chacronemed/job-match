"""build_sources: enabled list x credentials present. A missing key skips one source only."""
import logging

import pytest

from job_match.adapters.jobs.factory import build_sources, missing_env
from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    ScoringConfig,
    Settings,
    Skills,
    SourceLimits,
    SourcesConfig,
)

ALL_VARS = (
    "FT_CLIENT_ID", "FT_CLIENT_SECRET",
    "JOOBLE_API_KEY",
    "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)


def _profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=2),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(keywords=["devops"], departments=["75"]),
        scoring=ScoringConfig(),
    )


def _settings(enabled: list[str], **kwargs) -> Settings:
    return Settings(
        sources=SourcesConfig(
            enabled=enabled,
            regions=kwargs.pop("regions", ["Île-de-France"]),
            limits=kwargs.pop("limits", {}),
        )
    )


def _with_keys(monkeypatch, *names: str) -> None:
    creds = {
        "france_travail": {"FT_CLIENT_ID": "id", "FT_CLIENT_SECRET": "secret"},
        "jooble": {"JOOBLE_API_KEY": "jkey"},
        "adzuna": {"ADZUNA_APP_ID": "aid", "ADZUNA_APP_KEY": "akey"},
    }
    for name in names:
        for var, value in creds[name].items():
            monkeypatch.setenv(var, value)


# ---------------------------------------------------------------------------
# Enabled x credentials
# ---------------------------------------------------------------------------

def test_builds_every_enabled_source_that_has_credentials(monkeypatch):
    _with_keys(monkeypatch, "france_travail", "jooble")
    sources = build_sources(_profile(), _settings(["france_travail", "jooble"]))
    assert [s.name for s in sources] == ["france_travail", "jooble"]


def test_a_source_not_in_enabled_is_not_built(monkeypatch):
    """Adzuna is off until the plan is paid, even with credentials in the environment."""
    _with_keys(monkeypatch, "france_travail", "jooble", "adzuna")
    sources = build_sources(_profile(), _settings(["france_travail", "jooble"]))
    assert "adzuna" not in [s.name for s in sources]


def test_enabled_order_is_preserved(monkeypatch):
    """France Travail first means its rows win the canonical slot in cross-source dedup."""
    _with_keys(monkeypatch, "france_travail", "jooble")
    sources = build_sources(_profile(), _settings(["jooble", "france_travail"]))
    assert [s.name for s in sources] == ["jooble", "france_travail"]


# ---------------------------------------------------------------------------
# Missing credentials skip one source, never the run
# ---------------------------------------------------------------------------

def test_missing_key_skips_only_that_source(monkeypatch, caplog):
    _with_keys(monkeypatch, "france_travail")  # no JOOBLE_API_KEY
    with caplog.at_level(logging.WARNING):
        sources = build_sources(_profile(), _settings(["france_travail", "jooble"]))

    assert [s.name for s in sources] == ["france_travail"]
    assert "jooble: skipped, missing JOOBLE_API_KEY" in caplog.text


def test_one_warning_per_skipped_source(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        build_sources(_profile(), _settings(["france_travail", "jooble", "adzuna"]))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3


def test_adzuna_needs_both_credentials(monkeypatch, caplog):
    monkeypatch.setenv("ADZUNA_APP_ID", "aid")  # key missing
    with caplog.at_level(logging.WARNING):
        sources = build_sources(_profile(), _settings(["adzuna"]))
    assert sources == []
    assert "ADZUNA_APP_KEY" in caplog.text


def test_no_credentials_at_all_returns_an_empty_list(monkeypatch):
    assert build_sources(_profile(), _settings(["france_travail", "jooble"])) == []


def test_unknown_source_name_warns_and_is_skipped(monkeypatch, caplog):
    _with_keys(monkeypatch, "france_travail")
    with caplog.at_level(logging.WARNING):
        sources = build_sources(_profile(), _settings(["france_travail", "linkedin"]))
    assert [s.name for s in sources] == ["france_travail"]
    assert "unknown source 'linkedin'" in caplog.text


def test_missing_env_lists_only_the_unset_vars(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "id")
    assert missing_env("france_travail") == ["FT_CLIENT_SECRET"]
    assert missing_env("jooble") == ["JOOBLE_API_KEY"]
    assert missing_env("unknown") == []


def test_empty_env_var_counts_as_missing(monkeypatch):
    monkeypatch.setenv("JOOBLE_API_KEY", "")
    assert missing_env("jooble") == ["JOOBLE_API_KEY"]


# ---------------------------------------------------------------------------
# Config is passed through
# ---------------------------------------------------------------------------

def test_quota_cap_comes_from_settings(monkeypatch):
    _with_keys(monkeypatch, "jooble")
    settings = _settings(["jooble"], limits={"jooble": SourceLimits(max_calls_per_run=3)})
    (jooble,) = build_sources(_profile(), settings)
    assert jooble._max_calls == 3


def test_regions_come_from_settings(monkeypatch):
    _with_keys(monkeypatch, "jooble")
    settings = _settings(["jooble"], regions=["Lyon", "Rennes"])
    (jooble,) = build_sources(_profile(), settings)
    assert jooble._regions == ["Lyon", "Rennes"]


def test_limit_is_applied_per_query_to_every_source(monkeypatch):
    _with_keys(monkeypatch, "france_travail", "jooble")
    ft, jooble = build_sources(_profile(), _settings(["france_travail", "jooble"]), limit=10)
    assert ft._max_results == 10
    assert jooble._max_results == 10


def test_without_limit_sources_keep_their_own_defaults(monkeypatch):
    _with_keys(monkeypatch, "france_travail", "jooble")
    ft, jooble = build_sources(_profile(), _settings(["france_travail", "jooble"]))
    assert ft._max_results > 10  # France Travail's MAX_RESULTS
    assert jooble._max_results is None  # no per-region cap: the call budget is the ceiling


# ---------------------------------------------------------------------------
# location_scope drives the quota-light sources too
# ---------------------------------------------------------------------------

def _national_profile() -> Profile:
    """`location_scope: france` reaches the factory as an empty department list."""
    return Profile(
        candidate=Candidate(experience_years=2),
        skills=Skills(),
        filters=Filters(),
        ft_search=FTSearch(keywords=["devops"], departments=[]),
        scoring=ScoringConfig(),
    )


def test_a_national_scope_makes_jooble_walk_the_configured_regions(monkeypatch):
    """Never an empty location: on jooble.org that is the whole world (0% French, measured),
    and "France" is a literal filter that matches ~16 offers. The regions are the country."""
    _with_keys(monkeypatch, "jooble")
    (jooble,) = build_sources(
        _national_profile(), _settings(["jooble"], regions=["Bretagne", "Corse"])
    )

    assert jooble._regions == ["Bretagne", "Corse"]
    assert "" not in jooble._regions


def test_a_restricted_scope_keeps_the_configured_regions(monkeypatch):
    _with_keys(monkeypatch, "jooble")
    (jooble,) = build_sources(
        _profile(), _settings(["jooble"], regions=["Lyon", "Toulouse"])
    )
    assert jooble._regions == ["Lyon", "Toulouse"]


def test_a_national_scope_leaves_france_travail_without_departments(monkeypatch):
    _with_keys(monkeypatch, "france_travail")
    (ft,) = build_sources(_national_profile(), _settings(["france_travail"]))
    assert ft._profile.ft_search.national is True
