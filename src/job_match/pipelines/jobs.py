import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from job_match.config.schema import Profile, Settings
from job_match.dedup.engine import DedupEngine
from job_match.dedup.fingerprint import compute_fingerprint
from job_match.domain.models import Company, Eligibility, Job, RunSummary
from job_match.eligibility import gate
from job_match.experience import parser as exp_parser
from job_match.normalization.company import normalize_company
from job_match.normalization.location import block_location, department_of
from job_match.normalization.title import normalize_title
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    CompanyRepository,
    JobDuplicateRepository,
    JobRepository,
    RunRepository,
)
from job_match.scoring.engine import ScoringEngine
from job_match.scoring.native import NativeRuleScorer

logger = logging.getLogger(__name__)


def run_jobs(
    sources,
    profile: Profile,
    settings: Settings,
    db: Database,
    aliases: dict[str, list[str]],
    *,
    dry_run: bool = False,
) -> RunSummary:
    """Fetch → normalize → experience gate → dedup → score → store.

    `sources` is one JobSource or a sequence of them. Sources are drained in order and
    share one dedup pass, so the same offer on France Travail and Jooble becomes a
    canonical row plus a duplicate link — whichever source was read first wins.

    Volume is capped by each source, per query. The pipeline never caps globally: a
    global cap starves every query after the first one.
    """
    started_at = datetime.now(UTC)
    source_list = _as_sources(sources)
    job_repo = JobRepository(db.conn)
    company_repo = CompanyRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)

    dedup_engine = DedupEngine(settings)
    scoring_engine = ScoringEngine([NativeRuleScorer(aliases)])

    window = datetime.now(UTC) - timedelta(days=settings.dedup_window_days)

    fetched = 0
    rejected_jobs = 0
    rejected_by_reason: dict[str, int] = {}
    duplicates = 0
    eligible = 0
    strong = 0
    errors = 0
    by_source: dict[str, dict[str, int]] = {}
    by_department: dict[str, int] = {}

    for source in source_list:
        counts = by_source.setdefault(
            source.name, {"fetched": 0, "eligible": 0, "duplicates": 0, "calls": 0}
        )
        try:
            items = list(source.fetch(since=None))
        except Exception as exc:
            # One dead source must not cost us the others.
            logger.warning("%s: fetch failed: %s", source.name, exc)
            errors += 1
            items = []
        finally:
            counts["calls"] = getattr(source, "api_calls_count", 0)

        for raw in items:
            try:
                job: Job = source.to_job(raw)
            except Exception as exc:
                logger.warning("%s: to_job failed: %s", source.name, exc)
                errors += 1
                continue

            fetched += 1
            counts["fetched"] += 1
            # Where the offer is, not where we searched: a national query reports
            # area "all". "?" means no single department (a region, or a place that
            # is not in fr_geo).
            offer_dept = department_of(job.location) or "?"
            by_department[offer_dept] = by_department.get(offer_dept, 0) + 1

            # Experience
            exp = exp_parser.parse(job.description)
            job = replace(job, experience=exp)

            # Fingerprint (computed before gate so rejected jobs are also deduped on re-run)
            fp = compute_fingerprint(job)
            job = replace(job, fingerprint=fp)

            # Eligibility gate
            elig = gate.evaluate(job, exp, profile, settings, aliases)
            # DEBUG only: query keywords come from the private profile; CI logs stay aggregate.
            logger.debug(
                "job %s query=%r eligible=%s reasons=%s",
                job.source_job_id, job.search_query, elig.eligible,
                ",".join(str(r) for r in elig.reasons) or "-",
            )
            if not elig.eligible:
                rejection = ", ".join(str(r) for r in elig.reasons)
                job = replace(job, eligibility=Eligibility.REJECTED, rejection_reason=rejection)
                rejected_jobs += 1  # one per job, regardless of how many reasons
                for r in elig.reasons:
                    rejected_by_reason[str(r)] = rejected_by_reason.get(str(r), 0) + 1
                if not dry_run:
                    _save(job, company_repo, job_repo)
                continue

            # Dedup
            exact, fuzzy = _candidate_blocks(job, job_repo, window)
            dedup_result = dedup_engine.check(job, exact, fuzzy)

            if dedup_result.is_duplicate:
                duplicates += 1
                counts["duplicates"] += 1
                job = replace(job, eligibility=Eligibility.ELIGIBLE)
                if not dry_run:
                    saved = _save(job, company_repo, job_repo)
                    if saved.id is not None and dedup_result.canonical_id is not None:
                        canonical_id = _canonical_of(dup_repo, dedup_result.canonical_id)
                        if canonical_id != saved.id:
                            dup_repo.save_link(
                                canonical_id,
                                saved.id,
                                dedup_result.reason or "unknown",
                                dedup_result.similarity,
                            )
                continue

            # Score
            breakdown = scoring_engine.score(job, profile, settings, elig, exp)
            job = replace(
                job,
                eligibility=Eligibility.ELIGIBLE,
                score=breakdown.score,
                scoring_breakdown=breakdown,
            )

            eligible += 1
            counts["eligible"] += 1
            if breakdown.score is not None and breakdown.score >= settings.strong_threshold:
                strong += 1

            if not dry_run:
                _save(job, company_repo, job_repo)

    api_calls = sum(c["calls"] for c in by_source.values())
    stats = tuple(
        stat
        for source in source_list
        for stat in getattr(source, "query_stats", ())
    )
    by_area: dict[str, int] = {}
    by_keyword: dict[str, int] = {}
    for stat in stats:
        by_area[stat.area] = by_area.get(stat.area, 0) + stat.fetched
        by_keyword[stat.query] = by_keyword.get(stat.query, 0) + stat.fetched

    summary = RunSummary(
        pipeline="jobs",
        fetched=fetched,
        normalized=fetched,
        rejected_jobs=rejected_jobs,
        rejected_by_reason=rejected_by_reason,
        duplicates=duplicates,
        eligible=eligible,
        strong=strong,
        errors=errors,
        api_calls=api_calls,
        by_area=by_area,
        by_keyword=by_keyword,
        by_department=by_department,
        by_source=by_source,
        queries=len(stats),
    )

    if not dry_run:
        RunRepository(db.conn).save(summary, started_at, datetime.now(UTC))

    return summary


def reprocess_jobs(
    profile: Profile,
    settings: Settings,
    db: Database,
    aliases: dict[str, list[str]],
    *,
    since: datetime | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Re-apply the gate and the scorer to jobs already in the DB. No network calls.

    For when the rules change — a new relevance veto, a new threshold — and the question
    is what the current rules say about the data we already have. Dedup is replayed in
    collection order: a pair the original run could not see is linked now (the employer was
    hidden on one side, or the two postings arrived in the same run), and a stored link the
    current rules no longer make is removed, which frees the job for the digest. Self-links
    left by older runs are dropped first, for the same reason.

    `notified_at` is never touched, so a job already emailed is not emailed twice.
    """
    started_at = datetime.now(UTC)
    job_repo = JobRepository(db.conn)
    company_repo = CompanyRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)
    scoring_engine = ScoringEngine([NativeRuleScorer(aliases)])
    dedup_engine = DedupEngine(settings)

    self_links = 0
    if not dry_run:
        self_links = dup_repo.delete_self_links()
        if self_links:
            logger.info("dropped %d self-referential duplicate links", self_links)

    already_duplicates = dup_repo.duplicate_ids()

    fetched = 0
    rejected_jobs = 0
    rejected_by_reason: dict[str, int] = {}
    eligible = 0
    strong = 0
    errors = 0
    new_links = 0
    removed_links = 0
    by_department: dict[str, int] = {}

    for stored in job_repo.list_all(since):
        fetched += 1
        offer_dept = department_of(stored.location) or "?"
        by_department[offer_dept] = by_department.get(offer_dept, 0) + 1
        try:
            exp = exp_parser.parse(stored.description)
            job = replace(stored, experience=exp, fingerprint=compute_fingerprint(stored))

            elig = gate.evaluate(job, exp, profile, settings, aliases)
            if not elig.eligible:
                rejection = ", ".join(str(r) for r in elig.reasons)
                job = replace(
                    job,
                    eligibility=Eligibility.REJECTED,
                    rejection_reason=rejection,
                    score=None,
                    scoring_breakdown=None,
                )
                rejected_jobs += 1
                for r in elig.reasons:
                    rejected_by_reason[str(r)] = rejected_by_reason.get(str(r), 0) + 1
            else:
                breakdown = scoring_engine.score(job, profile, settings, elig, exp)
                job = replace(
                    job,
                    eligibility=Eligibility.ELIGIBLE,
                    rejection_reason=None,
                    score=breakdown.score,
                    scoring_breakdown=breakdown,
                )
                eligible += 1
                if breakdown.score is not None and breakdown.score >= settings.strong_threshold:
                    strong += 1

            if not dry_run:
                _save(job, company_repo, job_repo)

            if elig.eligible and job.id is not None:
                written, removed = _sync_dedup(
                    job,
                    job_repo,
                    dup_repo,
                    dedup_engine,
                    settings,
                    linked_to=(
                        dup_repo.get_canonical_id(job.id)
                        if job.id in already_duplicates
                        else None
                    ),
                    dry_run=dry_run,
                )
                new_links += written
                removed_links += removed
        except Exception as exc:
            logger.warning("reprocess failed for %s: %s", stored.source_job_id, exc)
            errors += 1

    summary = RunSummary(
        pipeline="jobs_reprocess",
        fetched=fetched,
        normalized=fetched,
        rejected_jobs=rejected_jobs,
        rejected_by_reason=rejected_by_reason,
        duplicates=new_links,
        self_links_dropped=self_links,
        stale_links_dropped=removed_links,
        eligible=eligible,
        strong=strong,
        errors=errors,
        by_department=by_department,
    )
    if not dry_run:
        RunRepository(db.conn).save(summary, started_at, datetime.now(UTC))
    return summary


def _candidate_blocks(
    job: Job,
    job_repo: JobRepository,
    window: datetime,
    *,
    before: tuple[datetime, int] | None = None,
) -> tuple[list[Job], list[Job]]:
    """The (exact, fuzzy) blocks one posting is compared against.

    With an employer name: its company block in the same place -- one employer hiring in two
    departments is two offers -- plus the employer-hidden postings sharing its title and
    department, so whichever of the two arrives second can still find the other. The block is
    not keyed on the contract type: the same offer on another source often has UNKNOWN
    contract.

    With no employer name (France Travail hides some employers): the title and department
    block instead, any company. The company block cannot do that job, because every hidden
    employer shares the same empty name: it compares all of them to each other and ignores
    the location entirely.

    `before` keeps only postings strictly older than `(collected_at, id)`, so a replay over
    stored rows cannot turn a later posting into the canonical one.
    """
    title_n = normalize_title(job.title)
    location_key = block_location(job.location)
    company_n = normalize_company(job.company)

    if company_n:
        fuzzy = job_repo.list_by_company(company_n, location_key, window)
        fuzzy += job_repo.list_by_title_department(
            title_n, location_key, window, hidden_employer_only=True
        )
    else:
        fuzzy = job_repo.list_by_title_department(title_n, location_key, window)

    exact = job_repo.get_by_fingerprint(job.fingerprint or "")
    return _usable_candidates(job, exact, before), _usable_candidates(job, fuzzy, before)


def _usable_candidates(
    job: Job, candidates: list[Job], before: tuple[datetime, int] | None
) -> list[Job]:
    """Candidates worth comparing: not the job itself, not rejected, not listed twice.

    A rejected posting must never become a canonical: `list_unnotified` hides every
    duplicate, so an eligible job linked to a rejected one would vanish from the digest
    instead of being deduped.
    """
    seen: set[tuple[str, str]] = set()
    usable: list[Job] = []
    for c in _other_postings(job, candidates):
        if c.eligibility is Eligibility.REJECTED:
            continue
        if before is not None and (c.collected_at, c.id or 0) >= before:
            continue
        key = (c.source, c.source_job_id)
        if key in seen:
            continue
        seen.add(key)
        usable.append(c)
    return usable


def _canonical_of(dup_repo: JobDuplicateRepository, job_id: int) -> int:
    """The head of a duplicate group: linking to a duplicate would build a chain."""
    return dup_repo.get_canonical_id(job_id) or job_id


def _sync_dedup(
    job: Job,
    job_repo: JobRepository,
    dup_repo: JobDuplicateRepository,
    dedup_engine: DedupEngine,
    settings: Settings,
    *,
    linked_to: int | None,
    dry_run: bool,
) -> tuple[int, int]:
    """Make one stored job's duplicate link agree with the current rules.

    Returns (links written, links removed). A link the rules no longer make is removed, not
    kept: it hides an eligible job from the digest, which is the whole reason the digest was
    wrong in the first place. `linked_to` is the canonical already recorded for this job, if
    any.

    The window is measured from the job's own collection date, not from today, so the replay
    asks what the current rules would have said when the posting arrived.
    """
    window = job.collected_at - timedelta(days=settings.dedup_window_days)
    exact, fuzzy = _candidate_blocks(
        job, job_repo, window, before=(job.collected_at, job.id or 0)
    )
    result = dedup_engine.check(job, exact, fuzzy)

    canonical_id: int | None = None
    if result.is_duplicate and result.canonical_id is not None:
        canonical_id = _canonical_of(dup_repo, result.canonical_id)
        if canonical_id == job.id:
            canonical_id = None

    if linked_to == canonical_id:
        return 0, 0

    # ids only: the daily workflow runs reprocess in a public Actions log.
    written = removed = 0
    if linked_to is not None and (dry_run or dup_repo.delete_link(linked_to, job.id)):
        removed = 1
        logger.info("reprocess: job %d is no longer a duplicate of %d", job.id, linked_to)
    if canonical_id is not None and (
        dry_run
        or dup_repo.save_link(
            canonical_id, job.id, result.reason or "unknown", result.similarity
        )
    ):
        written = 1
        logger.info(
            "reprocess: job %d is a duplicate of %d (%s)", job.id, canonical_id, result.reason
        )
    return written, removed


def _other_postings(job: Job, candidates: list[Job]) -> list[Job]:
    """Dedup candidates minus the job's own stored row.

    `JobRepository.save` upserts on (source, source_job_id), so re-running a day twice
    re-reads the same posting. Without this, the row matched its own fingerprint, was
    saved over itself and then linked as a duplicate of itself — which the digest's
    canonical filter excludes, silently hiding every job.
    """
    return [
        c for c in candidates
        if not (c.source == job.source and c.source_job_id == job.source_job_id)
    ]


def _as_sources(sources) -> list:
    """Accept one source or a sequence of them — a single source is the common case."""
    if hasattr(sources, "fetch"):
        return [sources]
    return list(sources)


def _save(job: Job, company_repo: CompanyRepository, job_repo: JobRepository) -> Job:
    company = company_repo.upsert(
        Company(name=job.company, normalized_name=normalize_company(job.company))
    )
    return job_repo.save(replace(job, company_id=company.id))
