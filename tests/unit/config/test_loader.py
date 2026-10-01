import base64
from pathlib import Path

import pytest

from job_match.config.loader import load_profile, load_profile_from_env, load_settings
from job_match.config.schema import ConfigError
from job_match.domain.models import ContractType

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent.parent
SETTINGS_FILE = REPO_ROOT / "config" / "settings.yaml"


class TestLoadProfile:
    def test_example_profile_loads(self):
        profile = load_profile(FIXTURES / "profile.example.yaml")
        assert profile.candidate.experience_years == 5.0
        names = [s.name for s in profile.skills.preferred]
        assert "kubernetes" in names
        neg_names = [s.name for s in profile.skills.negative]
        assert "SAP" in neg_names
        assert ContractType.CDI in profile.filters.contract_types
        assert "M1809" in profile.ft_search.rome_codes

    def test_missing_file_raises_config_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PROFILE_YAML", raising=False)
        with pytest.raises(ConfigError, match="Profile file not found"):
            load_profile(tmp_path / "nonexistent.yaml")

    def test_missing_candidate_field_raises(self, tmp_path):
        bad = tmp_path / "profile.yaml"
        bad.write_text("skills:\n  preferred: []\nft_search:\n  rome_codes: []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="missing required key: candidate"):
            load_profile(bad)

    def test_missing_ft_search_raises(self, tmp_path):
        bad = tmp_path / "profile.yaml"
        bad.write_text(
            "candidate:\n  experience_years: 3\nskills:\n  preferred: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="missing required key: ft_search"):
            load_profile(bad)

    def test_jms_disabled_by_default(self):
        profile = load_profile(FIXTURES / "profile.example.yaml")
        assert profile.scoring.jms.enabled is False


class TestLoadProfileFromEnv:
    def test_loads_from_base64_env(self, monkeypatch):
        fixture = (FIXTURES / "profile.example.yaml").read_text(encoding="utf-8")
        encoded = base64.b64encode(fixture.encode()).decode()
        monkeypatch.setenv("PROFILE_YAML", encoded)
        profile = load_profile_from_env()
        assert profile.candidate.experience_years == 5.0

    def test_missing_env_raises(self, monkeypatch):
        monkeypatch.delenv("PROFILE_YAML", raising=False)
        with pytest.raises(ConfigError, match="PROFILE_YAML env var is not set"):
            load_profile_from_env()


class TestLoadSettings:
    def test_happy_path(self):
        settings = load_settings(SETTINGS_FILE)
        assert settings.strong_threshold == 70
        assert settings.divergence_threshold == 30
        assert settings.fuzzy_title_threshold == pytest.approx(0.85)
        assert settings.scoring.jms.enabled is False

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="Settings file not found"):
            load_settings(tmp_path / "nonexistent.yaml")
