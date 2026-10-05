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
class LeadFilterConfig:
    countries: list[str] = field(default_factory=lambda: ["France"])  # empty = no filter
    min_amount_eur: float | None = None  # unknown amounts always pass
    exclude_sectors: list[str] = field(default_factory=list)  # keywords in title/evidence
    fx_to_eur: dict[str, float] = field(default_factory=lambda: {"USD": 0.92, "GBP": 1.17})


@dataclass
class RelevanceConfig:
    # A job must match >=1 preferred skill or have one of these in its title. Empty = off.
    target_title_keywords: list[str] = field(default_factory=list)


@dataclass
class DigestConfig:
    min_score: int = 60  # eligible jobs below this stay in the DB but are not emailed
    max_leads: int = 10  # leads beyond this roll over to the next digest


@dataclass
class FundingConfig:
    requests_per_second: float = 1.0
    extract_max_chars: int = 600
    sources: list[str] = field(default_factory=lambda: ["maddyness", "frenchweb"])
    lead_dedup_days: int = 30  # no second Lead for the same company within this window
    job_link_days: int = 180  # a job is flagged when its company raised within this window
    lead_filters: LeadFilterConfig = field(default_factory=LeadFilterConfig)


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
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)
