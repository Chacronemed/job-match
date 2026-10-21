import base64
import logging
import os
from dataclasses import replace
from pathlib import Path

import yaml

from job_match.config.schema import (
    Candidate,
    ConfigError,
    DigestConfig,
    EligibilityConfig,
    ExperienceConfig,
    Filters,
    FTSearch,
    FundingConfig,
    JMSConfig,
    JobsConfig,
    LeadFilterConfig,
    Profile,
    RawPayloadsConfig,
    RelevanceConfig,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
    SourceLimits,
    SourcesConfig,
)
from job_match.domain.models import ContractType

logger = logging.getLogger(__name__)


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


def load_skill_vocabulary(path: Path) -> tuple[str, ...]:
    """Skills worth naming when an offer asks for them and the profile does not list them.

    A YAML list of canonical names, lowercased and de-duplicated in file order. Their
    aliases live in `aliases.yaml`, like the profile's. Missing file: empty vocabulary.
    """
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise ConfigError(f"Skill vocabulary must be a YAML list of strings: {path}")
    return tuple(dict.fromkeys(v.strip().lower() for v in raw if v.strip()))


def apply_skill_overrides(profile: Profile, overrides: list[str], weight: int) -> Profile:
    """A copy of `profile` where each override is one more preferred skill.

    An override the profile already lists (preferred or negative) changes nothing: a
    negative skill is a choice the profile made on purpose, and the dashboard never offers
    "je maîtrise" for one anyway.
    """
    listed = {s.name.lower() for s in (*profile.skills.preferred, *profile.skills.negative)}
    added = [
        SkillWeight(name=name, weight=weight)
        for name in dict.fromkeys(o.lower() for o in overrides)
        if name not in listed
    ]
    if not added:
        return profile
    skills = Skills(preferred=[*profile.skills.preferred, *added], negative=profile.skills.negative)
    return replace(profile, skills=skills)


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
        sources=_parse_sources(raw.get("sources"), path),
        experience=_parse_experience(raw.get("experience"), path),
        eligibility=_parse_eligibility(raw.get("eligibility"), path),
        scoring=ScoringConfig(
            jms=JMSConfig(
                enabled=bool(jms_raw.get("enabled", False)),
                commit_sha=jms_raw.get("commit_sha"),
            ),
            override_weight=_positive_int(
                scoring_raw.get("override_weight", ScoringConfig().override_weight)
                if isinstance(scoring_raw, dict) else ScoringConfig().override_weight,
                "scoring.override_weight",
                path,
            ),
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
        jobs=_parse_jobs(raw.get("jobs"), path),
        raw_payloads=_parse_raw_payloads(raw.get("raw_payloads"), path),
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


# The only windows France Travail's `publieeDepuis` accepts.
PUBLISHED_SINCE_DAYS = (1, 3, 7, 14, 31)


def _parse_sources(value: object, path: Path) -> SourcesConfig:
    """Parse the `sources` block.

    `enabled` and `regions` are lists; every other key is a source name carrying that
    source's limits, so adding a source needs no schema change.
    """
    raw = _mapping(value, "sources", path)
    d = SourcesConfig()
    if not raw:
        return d
    limits: dict[str, SourceLimits] = {}
    for key, sub in raw.items():
        if key in ("enabled", "regions"):
            continue
        sub_raw = _mapping(sub, f"sources.{key}", path)
        limits[str(key)] = SourceLimits(
            max_calls_per_run=int(
                sub_raw.get("max_calls_per_run", SourceLimits().max_calls_per_run)
            ),
            published_since_days=_published_since_days(
                sub_raw.get("published_since_days"), f"sources.{key}", path
            ),
            radius_km=_optional_positive_int(
                sub_raw.get("radius_km"), f"sources.{key}.radius_km", path
            ),
        )
    return SourcesConfig(
        enabled=_str_list(raw.get("enabled", d.enabled), "sources.enabled", path),
        regions=_str_list(raw.get("regions"), "sources.regions", path),
        limits=limits,
    )


def _published_since_days(value: object, key: str, path: Path) -> int | None:
    """None, or one of the windows the API accepts; a typo must not silently widen the run."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value not in PUBLISHED_SINCE_DAYS:
        allowed = ", ".join(str(d) for d in PUBLISHED_SINCE_DAYS)
        raise ConfigError(
            f"{key}.published_since_days must be one of {allowed} (in {path})"
        )
    return value


def _positive_int(value: object, key: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key} must be a positive integer (in {path})")
    return value


def _optional_positive_int(value: object, key: str, path: Path) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key} must be a positive integer (in {path})")
    return value


def _parse_relevance(value: object, path: Path) -> RelevanceConfig:
    raw = _mapping(value, "relevance", path)
    return RelevanceConfig(
        target_title_keywords=_str_list(
            raw.get("target_title_keywords"), "relevance.target_title_keywords", path
        ),
        role_titles=_str_list(raw.get("role_titles"), "relevance.role_titles", path),
        dev_titles=_str_list(raw.get("dev_titles"), "relevance.dev_titles", path),
    )


def _parse_experience(value: object, path: Path) -> ExperienceConfig:
    raw = _mapping(value, "experience", path)
    d = ExperienceConfig()
    years = raw.get("stretch_years", d.stretch_years)
    if isinstance(years, bool) or not isinstance(years, int | float) or years < 0:
        raise ConfigError(f"experience.stretch_years must be a number >= 0 (in {path})")
    return ExperienceConfig(stretch_years=float(years))


def _parse_eligibility(value: object, path: Path) -> EligibilityConfig:
    raw = _mapping(value, "eligibility", path)
    flag = raw.get("exclude_rqth_reserved", EligibilityConfig().exclude_rqth_reserved)
    if not isinstance(flag, bool):
        raise ConfigError(f"eligibility.exclude_rqth_reserved must be true or false (in {path})")
    return EligibilityConfig(exclude_rqth_reserved=flag)


def _parse_digest(value: object, path: Path) -> DigestConfig:
    raw = _mapping(value, "digest", path)
    d = DigestConfig()
    return DigestConfig(
        min_score=int(raw.get("min_score", d.min_score)),
        max_leads=int(raw.get("max_leads", d.max_leads)),
    )


def _parse_jobs(value: object, path: Path) -> JobsConfig:
    raw = _mapping(value, "jobs", path)
    d = JobsConfig()
    days = raw.get("max_age_days", d.max_age_days)
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ConfigError(f"jobs.max_age_days must be a positive integer (in {path})")
    return JobsConfig(max_age_days=days)


def _parse_raw_payloads(value: object, path: Path) -> RawPayloadsConfig:
    raw = _mapping(value, "raw_payloads", path)
    d = RawPayloadsConfig()
    days = raw.get("retention_days", d.retention_days)
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ConfigError(f"raw_payloads.retention_days must be a positive integer (in {path})")
    return RawPayloadsConfig(retention_days=days)


def _require_key(raw: dict, key: str, source: str) -> object:
    if key not in raw:
        raise ConfigError(f"missing required key: {key} (in {source})")
    return raw[key]


_NATIONAL_SCOPES = {"france", "fr", "national", "all", "nationwide", "*"}


def _parse_location_scope(raw: dict, ft_search_raw: dict, source: str) -> list[str]:
    """The profile's one geography setting -> a department list (empty = whole country).

    `location_scope: france` (or fr / national / all) searches and accepts all of France.
    `location_scope: ["75", "92"]` restricts both the queries and the gate to those
    departments. The key is read from the top level, or from inside `ft_search` for
    convenience; the legacy `ft_search.departments` list is still accepted when neither is
    set, so an older profile keeps working.
    """
    scope = raw.get("location_scope", ft_search_raw.get("location_scope"))
    if scope is None:
        legacy = [str(d) for d in (ft_search_raw.get("departments") or [])]
        if legacy:
            logger.debug(
                "%s: ft_search.departments is deprecated, use location_scope", source
            )
        return legacy
    if isinstance(scope, str):
        if scope.strip().lower() in _NATIONAL_SCOPES or not scope.strip():
            return []
        return [scope.strip().upper()]  # a single department code
    if isinstance(scope, list):
        return [str(d).strip().upper() for d in scope if str(d).strip()]
    raise ConfigError(
        f"location_scope must be 'france' or a list of department codes (in {source})"
    )


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
        departments=_parse_location_scope(raw, ft_search_raw, source),
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
