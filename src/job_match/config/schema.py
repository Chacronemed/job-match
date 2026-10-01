from dataclasses import dataclass, field

from job_match.domain.models import ContractType


class ConfigError(ValueError):
    pass


@dataclass
class SkillWeight:
    name: str
    weight: int


@dataclass
class Candidate:
    experience_years: float


@dataclass
class Skills:
    preferred: list[SkillWeight] = field(default_factory=list)
    negative: list[SkillWeight] = field(default_factory=list)


@dataclass
class Filters:
    contract_types: list[ContractType] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)


@dataclass
class FTSearch:
    rome_codes: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)


@dataclass
class JMSConfig:
    enabled: bool = False
    commit_sha: str | None = None


@dataclass
class ScoringConfig:
    jms: JMSConfig = field(default_factory=JMSConfig)


@dataclass
class Profile:
    candidate: Candidate
    skills: Skills
    filters: Filters
    ft_search: FTSearch
    scoring: ScoringConfig = field(default_factory=ScoringConfig)


@dataclass
class Settings:
    strong_threshold: int = 70
    divergence_threshold: int = 30
    dedup_window_days: int = 30
    fuzzy_title_threshold: float = 0.85
    fuzzy_desc_threshold: float = 0.80
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
