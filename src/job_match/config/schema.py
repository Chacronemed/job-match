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
    # Weight of a skill marked "je maîtrise" on the dashboard (D1 `skill_overrides`): it
    # joins the preferred skills with this weight on the next run.
    override_weight: int = 2
    # A preferred skill the offer asks for in its profile / skills section (normalization/
    # sections.py) counts its weight times this; found only elsewhere, times 1. 1 = off.
    profile_section_multiplier: float = 1.0


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
class TitleRelevanceConfig:
    """What the title says the job is (scoring/title.py), checked in this order:

    * `core`: the target family (DevOps, SRE, cloud, platform, infrastructure) ->
      `core_points`; a core term protects the title from the off-domain lists, unless the
      title also names a `core_overrides` role (sales, product owner, project manager,
      recruiter…): then it is `other` ("Ingénieur commercial Cloud" sells, it does not run);
    * `off_domain`: another trade (recruitment, mechanics, hardware, data management…) ->
      vetoed at the gate, RejectionReason.TITLE, even when a near term is there too;
    * `near`: an adjacent IT role (systems, networks, IT operations) -> `near_points`;
    * `off_domain_sectors`: a sector rather than a trade (transport, marketing, hotels…) ->
      vetoed only when no core or near term is in the title ("Data engineer - marketing"
      is near, "Chargé marketing" is out);
    * none of them -> `other_points`, a penalty, not a veto: the recall stays wide.

    Prefix matching, accent- and case-insensitive ("infra" matches "Infrastructure"), except
    `core_overrides`: whole words, so "sales" never matches "Salesforce".
    Empty `core` = feature off: the legacy `title_bonus` keyword bonus applies instead.
    """

    core: list[str] = field(default_factory=list)
    near: list[str] = field(default_factory=list)
    off_domain: list[str] = field(default_factory=list)
    off_domain_sectors: list[str] = field(default_factory=list)
    core_overrides: list[str] = field(default_factory=list)
    core_points: int = 20
    near_points: int = 0
    other_points: int = -15

    @property
    def enabled(self) -> bool:
        return bool(self.core)


@dataclass
class ExperienceConfig:
    """`stretch_years`: a job whose required years exceed the candidate's by at most this
    much is STRETCH instead of rejected (every other gate still applies). 0 = no stretch
    tier. Above the band the experience gate rejects as it always did."""

    stretch_years: float = 0


@dataclass
class EligibilityConfig:
    """`exclude_rqth_reserved`: reject offers reserved for RQTH / BOETH holders (a hard
    gate, reason RESERVED_RQTH). Inclusive wording ("ouvert aux personnes en situation de
    handicap") never rejects."""

    exclude_rqth_reserved: bool = False
    # Recruiters whose job is placing RQTH candidates (a Talents Handicap forum offer never
    # says "réservé"). Matched on the company name or on their own boilerplate sentence; same
    # RESERVED_RQTH rejection, only while `exclude_rqth_reserved` is on.
    rqth_recruiters: list[str] = field(default_factory=list)


@dataclass
class DigestConfig:
    min_score: int = 60  # eligible jobs below this stay in the DB but are not emailed
    max_leads: int = 10  # leads beyond this roll over to the next digest


@dataclass
class JobsConfig:
    """`max_age_days`: a job whose posting date (collection date when unknown) is older than
    this is hidden from the digest and the dashboard even if its source was never asked
    whether it is still open. The closure check is the primary mechanism; this is the net."""

    max_age_days: int = 45


@dataclass
class RawPayloadsConfig:
    """`retention_days`: raw source payloads (private DB only) older than this are pruned at
    the end of each jobs run."""

    retention_days: int = 60


@dataclass
class AiConfig:
    """The AI rerank (ADR 0016) as the Python side sees it. The calls run in the Worker
    (worker/src/ai.js), whose constants these repeat: a test keeps them equal. `daily_limit`
    is the cap on calls per day, `disagreement_gap` the score gap that makes a disagreement,
    `prompt_version` the version whose verdicts count."""

    daily_limit: int = 100
    disagreement_gap: int = 25
    prompt_version: str = "1"


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
    title_relevance: TitleRelevanceConfig = field(default_factory=TitleRelevanceConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)
    experience: ExperienceConfig = field(default_factory=ExperienceConfig)
    eligibility: EligibilityConfig = field(default_factory=EligibilityConfig)
    jobs: JobsConfig = field(default_factory=JobsConfig)
    raw_payloads: RawPayloadsConfig = field(default_factory=RawPayloadsConfig)
    ai: AiConfig = field(default_factory=AiConfig)
