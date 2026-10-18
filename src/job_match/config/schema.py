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
    """What we search for, and where.

    `departments` is the parsed form of the profile's single `location_scope` key: a list of
    department codes for a restricted search, and **empty for the whole country**. Every
    source and the location gate read it, so there is one geography setting, not two.
    """

    rome_codes: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    use_rome_search: bool = False

    @property
    def national(self) -> bool:
        """No department list = search and accept the whole country."""
        return not self.departments


@dataclass
class SourceLimits:
    """Per-source knobs. `max_calls_per_run` caps the quota-light sources (Jooble, Adzuna);
    `published_since_days` is France Travail's publication window (1, 3, 7, 14 or 31, None =
    no window); `radius_km` widens a Jooble place query to the area around it."""

    max_calls_per_run: int = 10
    published_since_days: int | None = None
    radius_km: int | None = None


@dataclass
class SourcesConfig:
    """Which job sources run, and the geography/quota they run with.

    `regions` drives the quota-light sources: one query per keyword x region, never the
    keyword x department fan-out used for France Travail. Keywords stay in the profile
    (`ft_search.keywords`) — they are personal, regions are not.
    """

    enabled: list[str] = field(default_factory=lambda: ["france_travail"])
    regions: list[str] = field(default_factory=list)
    limits: dict[str, SourceLimits] = field(default_factory=dict)

    def is_enabled(self, name: str) -> bool:
        return name in self.enabled

    def max_calls(self, name: str, default: int = 10) -> int:
        limit = self.limits.get(name)
        return limit.max_calls_per_run if limit else default

    def published_since_days(self, name: str) -> int | None:
        limit = self.limits.get(name)
        return limit.published_since_days if limit else None

    def radius_km(self, name: str) -> int | None:
        limit = self.limits.get(name)
        return limit.radius_km if limit else None


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
    # Title veto: a dev_title in the title rejects the job unless a role_title is there too.
    # Both empty = veto off.
    role_titles: list[str] = field(default_factory=list)
    dev_titles: list[str] = field(default_factory=list)


@dataclass
class ExperienceConfig:
    """`stretch_years`: a job whose required years exceed the candidate's by at most this
    much is STRETCH instead of rejected (every other gate still applies). 0 = no stretch
    tier. Above the band the experience gate rejects as it always did."""

    stretch_years: float = 0


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
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    funding: FundingConfig = field(default_factory=FundingConfig)
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)
    experience: ExperienceConfig = field(default_factory=ExperienceConfig)
