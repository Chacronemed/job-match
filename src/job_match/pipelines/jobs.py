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
            exact = job_repo.get_by_fingerprint(fp)
            # Block on the company alone, not (company, contract): the same offer on
            # another source often has UNKNOWN contract, and a contract-keyed block
            # would never compare them.
            fuzzy = job_repo.list_by_company(company_n, window)
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
        by_source=by_source,
        queries=len(stats),
    )

    if not dry_run:
        RunRepository(db.conn).save(summary, started_at, datetime.now(UTC))

    return summary


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
