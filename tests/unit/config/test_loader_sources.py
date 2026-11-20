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


def test_committed_settings_run_france_travail_and_the_ats_boards():
    """The real config: Jooble is off since its city/region probes returned 0 (2026-10-18),
    Adzuna stays out until the plan is paid. Their limits stay configured for a switch-on.
    The ATS boards (ADR 0020) need no key, so they are on."""
    s = load_settings(Path("config/settings.yaml"))
    assert s.sources.enabled == ["france_travail", "ats"]
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


def test_jobs_max_age_days_defaults_to_45(tmp_path):
    s = load_settings(_write(tmp_path, "strong_threshold: 70\n"))
    assert s.jobs.max_age_days == 45


def test_jobs_max_age_days_is_parsed(tmp_path):
    s = load_settings(_write(tmp_path, "jobs:\n  max_age_days: 30\n"))
    assert s.jobs.max_age_days == 30


@pytest.mark.parametrize("value", ["0", "-1", "'45'", "true", "4.5"])
def test_jobs_max_age_days_must_be_a_positive_integer(tmp_path, value):
    with pytest.raises(ConfigError, match="jobs.max_age_days"):
        load_settings(_write(tmp_path, f"jobs:\n  max_age_days: {value}\n"))


def test_committed_settings_hide_postings_older_than_45_days():
    s = load_settings(Path("config/settings.yaml"))
    assert s.jobs.max_age_days == 45


def test_raw_payloads_retention_defaults_to_60(tmp_path):
    s = load_settings(_write(tmp_path, "strong_threshold: 70\n"))
    assert s.raw_payloads.retention_days == 60


def test_raw_payloads_retention_is_parsed(tmp_path):
    s = load_settings(_write(tmp_path, "raw_payloads:\n  retention_days: 14\n"))
    assert s.raw_payloads.retention_days == 14


@pytest.mark.parametrize("value", ["0", "-1", "'60'", "true", "6.5"])
def test_raw_payloads_retention_must_be_a_positive_integer(tmp_path, value):
    with pytest.raises(ConfigError, match="raw_payloads.retention_days"):
        load_settings(_write(tmp_path, f"raw_payloads:\n  retention_days: {value}\n"))


def test_committed_settings_keep_raw_payloads_60_days():
    assert load_settings(Path("config/settings.yaml")).raw_payloads.retention_days == 60


# ---------------------------------------------------------------------- Workday pacing

def test_committed_settings_pace_workday():
    """config/settings.yaml → sources.ats.workday: the delay between two Workday calls and
    the retry policy are settings, not constants."""
    w = load_settings(Path("config/settings.yaml")).sources.workday
    assert w.request_delay_seconds == 1.5
    assert (w.max_retries, w.backoff_seconds, w.backoff_max_seconds) == (2, 5.0, 60.0)
    assert (w.retry_after_max_seconds, w.max_consecutive_failures) == (120.0, 2)


def test_workday_pacing_is_read_from_settings_and_defaults_apply(tmp_path):
    s = load_settings(_write(
        tmp_path,
        "sources:\n  ats:\n    workday:\n      request_delay_seconds: 4\n      max_retries: 0\n",
    ))
    assert s.sources.workday.request_delay_seconds == 4.0
    assert s.sources.workday.max_retries == 0
    assert s.sources.workday.backoff_seconds == 5.0  # untouched keys keep their default
    assert load_settings(_write(tmp_path, "sources: {}\n")).sources.workday.max_retries == 2


@pytest.mark.parametrize("body", [
    "request_delay_seconds: -1",
    "request_delay_seconds: fast",
    "backoff_seconds: true",
    "max_retries: 1.5",
    "max_retries: -1",
    "max_consecutive_failures: 0",
])
def test_invalid_workday_pacing_is_refused(tmp_path, body):
    with pytest.raises(ConfigError, match="sources.ats.workday"):
        load_settings(_write(tmp_path, f"sources:\n  ats:\n    workday:\n      {body}\n"))


# ---------------------------------------------------------------------- ATS search, caps

def test_ats_search_and_workday_caps_are_read_from_settings(tmp_path):
    s = load_settings(_write(
        tmp_path,
        "sources:\n  ats:\n    search_keywords: [devops, ' sre ']\n    title_prefilter: true\n"
        "    workday:\n      max_calls_per_run: 8\n      frequency_days: 3\n"
        "      skip_known: false\n",
    )).sources
    assert s.ats_search.search_keywords == ("devops", "sre")
    assert s.ats_search.title_prefilter is True
    assert (s.workday.max_calls_per_run, s.workday.frequency_days, s.workday.skip_known) == (
        8, 3, False)


def test_without_settings_workday_is_capped_and_weekly_and_nothing_is_searched(tmp_path):
    s = load_settings(_write(tmp_path, "sources: {}\n")).sources
    assert (s.workday.max_calls_per_run, s.workday.frequency_days, s.workday.skip_known) == (
        15, 7, True)
    assert s.ats_search.search_keywords == () and s.ats_search.title_prefilter is False


@pytest.mark.parametrize("body", [
    "search_keywords: devops",
    "search_keywords: [1, 2]",
    "title_prefilter: yes please",
    "workday: {max_calls_per_run: -1}",
    "workday: {frequency_days: 0}",
    "workday: {frequency_days: 1.5}",
    "workday: {skip_known: 1}",
])
def test_invalid_ats_search_or_caps_are_refused(tmp_path, body):
    with pytest.raises(ConfigError, match="sources.ats"):
        load_settings(_write(tmp_path, f"sources:\n  ats:\n    {body}\n"))
