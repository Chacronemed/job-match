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
from job_match.normalization.location import department_of
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
            company_n = normalize_company(job.company)
            # Block on the company alone, not (company, contract): the same offer on
            # another source often has UNKNOWN contract, and a contract-keyed block
            # would never compare them.
            exact = _other_postings(job, job_repo.get_by_fingerprint(fp))
            fuzzy = _other_postings(job, job_repo.list_by_company(company_n, window))
            dedup_result = dedup_engine.check(job, exact, fuzzy)

            if dedup_result.is_duplicate:
                duplicates += 1
                counts["duplicates"] += 1
                job = replace(job, eligibility=Eligibility.ELIGIBLE)
                if not dry_run:
                    saved = _save(job, company_repo, job_repo)
                    if saved.id is not None and dedup_result.canonical_id is not None:
                        dup_repo.save_link(
                            dedup_result.canonical_id,
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
    is what the current rules say about the data we already have. Dedup is not redone:
    the links are already stored. Self-links left by older runs are dropped first,
    because they hide otherwise-canonical jobs from the digest.

    `notified_at` is never touched, so a job already emailed is not emailed twice.
    """
    started_at = datetime.now(UTC)
    job_repo = JobRepository(db.conn)
    company_repo = CompanyRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)
    scoring_engine = ScoringEngine([NativeRuleScorer(aliases)])

    self_links = 0
    if not dry_run:
        self_links = dup_repo.delete_self_links()
        if self_links:
            logger.info("dropped %d self-referential duplicate links", self_links)

    fetched = 0
    rejected_jobs = 0
    rejected_by_reason: dict[str, int] = {}
    eligible = 0
    strong = 0
    errors = 0

    for stored in job_repo.list_all(since):
        fetched += 1
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
        except Exception as exc:
            logger.warning("reprocess failed for %s: %s", stored.source_job_id, exc)
            errors += 1

    summary = RunSummary(
        pipeline="jobs_reprocess",
        fetched=fetched,
        normalized=fetched,
        rejected_jobs=rejected_jobs,
        rejected_by_reason=rejected_by_reason,
        duplicates=self_links,  # self-links removed, not duplicates found
        eligible=eligible,
        strong=strong,
        errors=errors,
    )
    if not dry_run:
        RunRepository(db.conn).save(summary, started_at, datetime.now(UTC))
    return summary


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
