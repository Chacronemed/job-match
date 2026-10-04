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
    use_rome_search: bool = False


@dataclass
class JMSConfig:
    enabled: bool = False
    commit_sha: str | None = None


@dataclass
class ScoringConfig:
    jms: JMSConfig = field(default_factory=JMSConfig)


@dataclass
class FundingConfig:
    requests_per_second: float = 1.0
    extract_max_chars: int = 600
    sources: list[str] = field(default_factory=lambda: ["maddyness", "frenchweb"])


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
    base_score: int = 50
    title_bonus: int = 10
    ft_requests_per_second: float = 3.0
    seniority_min_years: dict[str, int] = field(default_factory=dict)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    funding: FundingConfig = field(default_factory=FundingConfig)
