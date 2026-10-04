from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ExperienceStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    NOT_MENTIONED = "NOT_MENTIONED"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"


class RejectionReason(StrEnum):
    EXPERIENCE = "EXPERIENCE"
    CONTRACT = "CONTRACT"
    LOCATION = "LOCATION"
    TITLE = "TITLE"


class WorkplaceType(StrEnum):
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"
    UNKNOWN = "UNKNOWN"


class ContractType(StrEnum):
    CDI = "CDI"
    CDD = "CDD"
    INTERIM = "INTERIM"
    ALTERNANCE = "ALTERNANCE"
    STAGE = "STAGE"
    FREELANCE = "FREELANCE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExperienceRequirement:
    status: ExperienceStatus
    min_years: float | None = None
    max_years: float | None = None
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[RejectionReason, ...] = ()


@dataclass(frozen=True, slots=True)
class ScoreResult:
    engine: str
    available: bool
    score: int | None = None
    positive_matches: tuple[str, ...] = ()
    negative_matches: tuple[str, ...] = ()
    missing_preferences: tuple[str, ...] = ()
    explanations: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoringBreakdown:
    eligible: bool
    experience: ExperienceStatus
    score: int | None = None
    positive_matches: tuple[str, ...] = ()
    negative_matches: tuple[str, ...] = ()
    missing_preferences: tuple[str, ...] = ()
    explanations: tuple[str, ...] = ()
    engines: dict[str, ScoreResult] = field(default_factory=dict)
    divergence: int | None = None
    needs_review: bool = False


@dataclass(frozen=True, slots=True)
class Job:
    source: str
    source_job_id: str
    title: str
    company: str
    location: str
    workplace_type: WorkplaceType
    contract_type: ContractType
    description: str
    url: str
    collected_at: datetime
    id: int | None = None
    company_id: int | None = None
    published_at: datetime | None = None
    fingerprint: str | None = None
    eligibility: Eligibility | None = None
    rejection_reason: str | None = None
    experience: ExperienceRequirement | None = None
    score: int | None = None
    scoring_breakdown: ScoringBreakdown | None = None


@dataclass(frozen=True, slots=True)
class RawPayload:
    source: str
    source_id: str
    fetched_at: datetime
    payload_json: str


@dataclass(frozen=True, slots=True)
class Company:
    name: str
    normalized_name: str
    id: int | None = None
    website: str | None = None
    location: str | None = None


@dataclass(frozen=True, slots=True)
class Article:
    source: str
    url: str
    title: str
    collected_at: datetime
    published_at: datetime | None = None
    extract: str | None = None  # short head of the body only; full text is never stored
    id: int | None = None


@dataclass(frozen=True, slots=True)
class FundingEvent:
    company_id: int
    source: str
    article_url: str
    collected_at: datetime
    amount: float | None = None
    currency: str | None = None
    round: str | None = None
    date: str | None = None
    investors: tuple[str, ...] | None = None
    sector: str | None = None
    location: str | None = None
    recruiting_signal: str | None = None


@dataclass(frozen=True, slots=True)
class Lead:
    company_id: int
    funding_event_id: int
    reason: str
    created_at: datetime
    status: str = "new"
    notified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunSummary:
    pipeline: str
    fetched: int = 0
    normalized: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    eligible: int = 0
    strong: int = 0
    articles: int = 0
    leads: int = 0
    errors: int = 0
    api_calls: int = 0
    rejected_jobs: int = 0
    feeds: int = 0
