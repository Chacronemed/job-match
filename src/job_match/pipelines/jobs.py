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
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    CompanyRepository,
    JobDuplicateRepository,
    JobRepository,
)
from job_match.scoring.engine import ScoringEngine
from job_match.scoring.native import NativeRuleScorer

logger = logging.getLogger(__name__)


def run_jobs(
    source,
    profile: Profile,
    settings: Settings,
    db: Database,
    aliases: dict[str, list[str]],
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> RunSummary:
    """Fetch → normalize → experience gate → dedup → score → store."""
    job_repo = JobRepository(db.conn)
    company_repo = CompanyRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)

    dedup_engine = DedupEngine(settings)
    scoring_engine = ScoringEngine([NativeRuleScorer(aliases)])

    window = datetime.now(UTC) - timedelta(days=settings.dedup_window_days)

    processed = 0
    fetched = 0
    rejected_jobs = 0
    rejected_by_reason: dict[str, int] = {}
    duplicates = 0
    eligible = 0
    strong = 0
    errors = 0

    for raw in source.fetch(since=None):
        if limit is not None and processed >= limit:
            break
        processed += 1

        try:
            job: Job = source.to_job(raw)
        except Exception as exc:
            logger.warning("to_job failed: %s", exc)
            errors += 1
            continue

        fetched += 1

        # Experience
        exp = exp_parser.parse(job.description)
        job = replace(job, experience=exp)

        # Fingerprint (computed before gate so rejected jobs are also deduped on re-run)
        fp = compute_fingerprint(job)
        job = replace(job, fingerprint=fp)

        # Eligibility gate
        elig = gate.evaluate(job, exp, profile, settings)
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
        exact = job_repo.get_by_fingerprint(fp)
        fuzzy = job_repo.list_by_block(company_n, job.contract_type, window)
        dedup_result = dedup_engine.check(job, exact, fuzzy)

        if dedup_result.is_duplicate:
            duplicates += 1
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
        if breakdown.score is not None and breakdown.score >= settings.strong_threshold:
            strong += 1

        if not dry_run:
            _save(job, company_repo, job_repo)

    api_calls = getattr(source, "api_calls_count", 0)
    return RunSummary(
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
    )


def _save(job: Job, company_repo: CompanyRepository, job_repo: JobRepository) -> Job:
    company = company_repo.upsert(
        Company(name=job.company, normalized_name=normalize_company(job.company))
    )
    return job_repo.save(replace(job, company_id=company.id))
