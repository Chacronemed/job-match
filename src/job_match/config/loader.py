import base64
import os
from pathlib import Path

import yaml

from job_match.config.schema import (
    Candidate,
    ConfigError,
    Filters,
    FTSearch,
    JMSConfig,
    Profile,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType


def load_profile(path: Path) -> Profile:
    if not path.exists():
        env_val = os.environ.get("PROFILE_YAML")
        if env_val:
            return load_profile_from_env()
        raise ConfigError(
            f"Profile file not found: {path}\n"
            "Copy config/profile.example.yaml to config/profile.yaml and fill in your values."
        )
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return _parse_profile(raw, str(path))


def load_profile_from_env() -> Profile:
    encoded = os.environ.get("PROFILE_YAML")
    if not encoded:
        raise ConfigError("PROFILE_YAML env var is not set")
    try:
        text = base64.b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ConfigError(f"PROFILE_YAML is not valid base64: {exc}") from exc
    raw = yaml.safe_load(text)
    return _parse_profile(raw, "PROFILE_YAML env var")


def load_settings(path: Path) -> Settings:
    if not path.exists():
        raise ConfigError(f"Settings file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    scoring_raw = raw.get("scoring") or {}
    jms_raw = scoring_raw.get("jms") or {} if isinstance(scoring_raw, dict) else {}
    return Settings(
        strong_threshold=int(raw.get("strong_threshold", 70)),
        divergence_threshold=int(raw.get("divergence_threshold", 30)),
        dedup_window_days=int(raw.get("dedup_window_days", 30)),
        fuzzy_title_threshold=float(raw.get("fuzzy_title_threshold", 0.85)),
        fuzzy_desc_threshold=float(raw.get("fuzzy_desc_threshold", 0.80)),
        base_score=int(raw.get("base_score", 50)),
        title_bonus=int(raw.get("title_bonus", 10)),
        scoring=ScoringConfig(
            jms=JMSConfig(
                enabled=bool(jms_raw.get("enabled", False)),
                commit_sha=jms_raw.get("commit_sha"),
            )
        ),
    )


def _require_key(raw: dict, key: str, source: str) -> object:
    if key not in raw:
        raise ConfigError(f"missing required key: {key} (in {source})")
    return raw[key]


def _parse_profile(raw: object, source: str) -> Profile:
    if not isinstance(raw, dict):
        raise ConfigError(f"Profile must be a YAML mapping (in {source})")

    candidate_raw = _require_key(raw, "candidate", source)
    skills_raw = _require_key(raw, "skills", source)
    _require_key(raw, "ft_search", source)  # presence check; value used below

    if not isinstance(candidate_raw, dict) or "experience_years" not in candidate_raw:
        raise ConfigError(
            f"missing required key: candidate.experience_years (in {source})"
        )

    candidate = Candidate(experience_years=float(candidate_raw["experience_years"]))

    preferred = [
        SkillWeight(name=str(s["name"]), weight=int(s["weight"]))
        for s in (skills_raw.get("preferred") or [] if isinstance(skills_raw, dict) else [])
    ]
    negative = [
        SkillWeight(name=str(s["name"]), weight=int(s["weight"]))
        for s in (skills_raw.get("negative") or [] if isinstance(skills_raw, dict) else [])
    ]
    skills = Skills(preferred=preferred, negative=negative)

    filters_raw = raw.get("filters") or {}
    filters = Filters(
        contract_types=[
            ContractType(str(c))
            for c in (
                filters_raw.get("contract_types") or []
                if isinstance(filters_raw, dict)
                else []
            )
        ],
        locations=list(
            filters_raw.get("locations") or []
            if isinstance(filters_raw, dict)
            else []
        ),
    )

    ft_search_raw = raw["ft_search"]
    if not isinstance(ft_search_raw, dict):
        raise ConfigError(f"ft_search must be a mapping (in {source})")
    ft_search = FTSearch(
        rome_codes=[str(c) for c in (ft_search_raw.get("rome_codes") or [])],
        keywords=[str(k) for k in (ft_search_raw.get("keywords") or [])],
        departments=[str(d) for d in (ft_search_raw.get("departments") or [])],
    )

    scoring_raw = raw.get("scoring") or {}
    jms_raw = scoring_raw.get("jms") or {} if isinstance(scoring_raw, dict) else {}
    scoring = ScoringConfig(
        jms=JMSConfig(
            enabled=bool(jms_raw.get("enabled", False)),
            commit_sha=jms_raw.get("commit_sha"),
        )
    )

    return Profile(
        candidate=candidate,
        skills=skills,
        filters=filters,
        ft_search=ft_search,
        scoring=scoring,
    )
