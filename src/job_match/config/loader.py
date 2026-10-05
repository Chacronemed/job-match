import base64
import os
from pathlib import Path

import yaml

from job_match.config.schema import (
    Candidate,
    ConfigError,
    DigestConfig,
    Filters,
    FTSearch,
    FundingConfig,
    JMSConfig,
    LeadFilterConfig,
    Profile,
    RelevanceConfig,
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


def load_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Aliases file must be a YAML mapping: {path}")
    return {
        str(k): [str(v) for v in vs]
        for k, vs in raw.items()
        if isinstance(vs, list)
    }


def load_settings(path: Path) -> Settings:
    if not path.exists():
        raise ConfigError(f"Settings file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    scoring_raw = raw.get("scoring") or {}
    jms_raw = scoring_raw.get("jms") or {} if isinstance(scoring_raw, dict) else {}
    funding_raw = raw.get("funding") or {}
    if not isinstance(funding_raw, dict):
        raise ConfigError(f"funding must be a mapping (in {path})")
    funding_defaults = FundingConfig()
    sources_raw = funding_raw.get("sources", funding_defaults.sources)
    if not isinstance(sources_raw, list) or not all(isinstance(s, str) for s in sources_raw):
        raise ConfigError(f"funding.sources must be a list of strings (in {path})")
    return Settings(
        strong_threshold=int(raw.get("strong_threshold", 70)),
        divergence_threshold=int(raw.get("divergence_threshold", 30)),
        dedup_window_days=int(raw.get("dedup_window_days", 30)),
        fuzzy_title_threshold=float(raw.get("fuzzy_title_threshold", 0.85)),
        fuzzy_desc_threshold=float(raw.get("fuzzy_desc_threshold", 0.80)),
        base_score=int(raw.get("base_score", 50)),
        title_bonus=int(raw.get("title_bonus", 10)),
        ft_requests_per_second=float(raw.get("ft_requests_per_second", 3.0)),
        seniority_min_years={
            str(k): int(v) for k, v in (raw.get("seniority_min_years") or {}).items()
        },
        scoring=ScoringConfig(
            jms=JMSConfig(
                enabled=bool(jms_raw.get("enabled", False)),
                commit_sha=jms_raw.get("commit_sha"),
            )
        ),
        funding=FundingConfig(
            requests_per_second=float(
                funding_raw.get("requests_per_second", funding_defaults.requests_per_second)
            ),
            extract_max_chars=int(
                funding_raw.get("extract_max_chars", funding_defaults.extract_max_chars)
            ),
            sources=list(sources_raw),
            lead_dedup_days=int(
                funding_raw.get("lead_dedup_days", funding_defaults.lead_dedup_days)
            ),
            job_link_days=int(
                funding_raw.get("job_link_days", funding_defaults.job_link_days)
            ),
            lead_filters=_parse_lead_filters(funding_raw.get("lead_filters"), path),
        ),
        relevance=_parse_relevance(raw.get("relevance"), path),
        digest=_parse_digest(raw.get("digest"), path),
    )


def _str_list(value: object, key: str, path: Path) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of strings (in {path})")
    return list(value)


def _mapping(value: object, key: str, path: Path) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping (in {path})")
    return value


def _parse_lead_filters(value: object, path: Path) -> LeadFilterConfig:
    raw = _mapping(value, "funding.lead_filters", path)
    d = LeadFilterConfig()
    min_amount = raw.get("min_amount_eur", d.min_amount_eur)
    fx = _mapping(raw.get("fx_to_eur"), "funding.lead_filters.fx_to_eur", path) or d.fx_to_eur
    return LeadFilterConfig(
        countries=_str_list(
            raw.get("countries", d.countries), "funding.lead_filters.countries", path
        ),
        min_amount_eur=float(min_amount) if min_amount is not None else None,
        exclude_sectors=_str_list(
            raw.get("exclude_sectors"), "funding.lead_filters.exclude_sectors", path
        ),
        fx_to_eur={str(k).upper(): float(v) for k, v in fx.items()},
    )


def _parse_relevance(value: object, path: Path) -> RelevanceConfig:
    raw = _mapping(value, "relevance", path)
    return RelevanceConfig(
        target_title_keywords=_str_list(
            raw.get("target_title_keywords"), "relevance.target_title_keywords", path
        )
    )


def _parse_digest(value: object, path: Path) -> DigestConfig:
    raw = _mapping(value, "digest", path)
    d = DigestConfig()
    return DigestConfig(
        min_score=int(raw.get("min_score", d.min_score)),
        max_leads=int(raw.get("max_leads", d.max_leads)),
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
        use_rome_search=bool(ft_search_raw.get("use_rome_search", False)),
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
