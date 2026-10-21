from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class ExperienceStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    NOT_MENTIONED = "NOT_MENTIONED"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    # Passed every gate but asks for more experience than the candidate has, within
    # `settings.experience.stretch_years`. Scored like any eligible job, its own digest
    # section, never a strong match.
    STRETCH = "STRETCH"


STRETCH_NOTE_PREFIX = "stretch:"
EXCLUDES_APPRENTICESHIP_NOTE = "experience: internships/work-study excluded from required years"


def format_years(years: float) -> str:
    """3.0 -> "3", 2.5 -> "2.5"."""
    return str(int(years)) if float(years).is_integer() else str(years)


def stretch_note(required_years: float, candidate_years: float) -> str:
    """The explanation line a stretch job carries, e.g. "stretch: requires 3y, you have 2"."""
    return (
        f"{STRETCH_NOTE_PREFIX} requires {format_years(required_years)}y, "
        f"you have {format_years(candidate_years)}"
    )


class ExperienceBasis(StrEnum):
    """Where the gate's required years came from, i.e. how much to trust them."""

    EXPLICIT = "explicit"  # a number in the text ("3 ans d'expérience", "up to 2 years")
    SENIORITY = "seniority"  # no number, a seniority keyword ("senior", "confirmé")
    UNKNOWN = "unknown"  # vague wording only ("première expérience", "solid experience")
    NOT_MENTIONED = "not_mentioned"


class RejectionReason(StrEnum):
    EXPERIENCE = "EXPERIENCE"
    CONTRACT = "CONTRACT"
    LOCATION = "LOCATION"
    TITLE = "TITLE"
    NOT_RELEVANT = "NOT_RELEVANT"  # no preferred skill and no target-role title keyword
    RESERVED_RQTH = "RESERVED_RQTH"  # reserved for RQTH / BOETH holders


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
    # "hors stage et alternance": internships / work-study years do not count. Reported
    # in explanations only; the gate does not use it (yet).
    excludes_apprenticeship: bool = False
    # The sentence the evidence came from, for display. Not stored in its own column: the
    # scoring breakdown carries it (`ScoringBreakdown.experience_detail`).
    sentence: str | None = None


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[RejectionReason, ...] = ()
    # `stretch`: eligible, but only thanks to the stretch band (see Eligibility.STRETCH).
    # `required_years`: the minimum the gate compared against (explicit number, else the
    # seniority-keyword minimum), None when the text says nothing usable.
    stretch: bool = False
    required_years: float | None = None
    # How `required_years` was found, and the sentence that says so (the parser's sentence,
    # or the one holding the seniority keyword).
    basis: ExperienceBasis = ExperienceBasis.NOT_MENTIONED
    basis_evidence: str | None = None


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
    # Per matched skill (preferred or negative): the sentence it was found in and the
    # weight it carried. `unlisted`: vocabulary skills the offer names that are neither in
    # the profile nor overridden, with their sentence.
    evidence: dict[str, str] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)
    unlisted: dict[str, str] = field(default_factory=dict)


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
    evidence: dict[str, str] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)
    unlisted: dict[str, str] = field(default_factory=dict)
    # {"required_years", "basis", "sentence", "excludes_apprenticeship"}, from the gate and
    # the parser at scoring time. Empty for rows scored before it existed.
    experience_detail: dict = field(default_factory=dict)


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
    search_query: str | None = None  # source query (keyword) that returned the job


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
    is_funding: bool = False
    processed_at: datetime | None = None  # None = funding extraction never ran (M10 rows)


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
    id: int | None = None
    article_id: int | None = None
    evidence: dict[str, str] = field(default_factory=dict)  # field -> sentence it came from
    country: str | None = None  # explicit only ("startup suisse", "based in London")


@dataclass(frozen=True, slots=True)
class Lead:
    company_id: int
    funding_event_id: int
    reason: str
    created_at: datetime
    status: str = "new"
    notified_at: datetime | None = None
    id: int | None = None
    priority: str = "normal"  # "high" when the article carries a hiring signal


@dataclass(frozen=True, slots=True)
class CompanyFunding:
    """Read model: the latest funding event of a company, used to flag its jobs.

    It links Job and FundingEvent through `companies.id` only. A Job never becomes a Lead.
    """

    company_id: int
    company: str
    article_url: str
    article_title: str
    amount: float | None = None
    currency: str | None = None
    round: str | None = None
    date: str | None = None  # publication date (ISO) or collection date when unknown


@dataclass(frozen=True, slots=True)
class LeadDetail:
    """Read model: a Lead joined with its company, funding event and source article."""

    lead_id: int
    company_id: int
    company: str
    priority: str
    reason: str
    created_at: datetime
    source: str
    article_url: str
    article_title: str
    published_at: datetime | None = None
    amount: float | None = None
    currency: str | None = None
    round: str | None = None
    investors: tuple[str, ...] | None = None
    hiring: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    open_jobs: int = 0  # eligible, canonical, recent jobs at the same company
    country: str | None = None


@dataclass(frozen=True, slots=True)
class FollowUp:
    """Read model: an application whose follow-up date has come, with its offer if still stored.

    The note and CV link are not part of it: they never leave the dashboard.
    """

    job_key: str
    status: str
    follow_up_at: date
    title: str | None = None
    company: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Read model: one stored run, with its summary as the dict `RunRepository.save` wrote."""

    id: int
    pipeline: str
    started_at: datetime
    finished_at: datetime | None
    summary: dict


@dataclass(frozen=True, slots=True)
class RunSummary:
    pipeline: str
    fetched: int = 0
    normalized: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    eligible: int = 0
    strong: int = 0
    stretch: int = 0  # jobs kept by the experience stretch band; not in eligible or strong
    # Closure check after collection: stored offers asked at the source, and how many it
    # said were gone. A check that got no clear answer counts in `errors`, never in `closed`.
    checked: int = 0
    closed: int = 0
    # Raw source payloads written this run (new or changed only) and rows pruned by age.
    raw_stored: int = 0
    raw_pruned: int = 0
    articles: int = 0
    leads: int = 0
    errors: int = 0
    api_calls: int = 0
    rejected_jobs: int = 0
    feeds: int = 0
    funding_articles: int = 0
    funding_events: int = 0
    funding_no_company: int = 0
    leads_deduped: int = 0
    # Reprocess only: links removed, not duplicates found. `self_links_dropped` counts
    # corrupt self-references, `stale_links_dropped` links the current rules no longer make.
    self_links_dropped: int = 0
    stale_links_dropped: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    by_area: dict[str, int] = field(default_factory=dict)  # queried area → fetched
    # Where the offers actually are, parsed from each offer's own location: the only
    # geographic breakdown left once the search is national and by_area is just "all".
    by_department: dict[str, int] = field(default_factory=dict)
    by_keyword: dict[str, int] = field(default_factory=dict)     # query label → items fetched
    queries: int = 0  # source queries executed (keyword × department)
