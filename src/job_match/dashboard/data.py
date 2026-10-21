"""Build the dashboard's data snapshot from the database.

Everything the page shows comes from this one dict, so this module is the allow-list of what
leaves the DB: job descriptions, the profile's search keywords (`by_keyword`, `queries`), raw
payloads and anything personal never appear here. Two exceptions to "no description": the
"Pourquoi cette offre ?" panel's single sentence per finding, capped at `EVIDENCE_MAX` (ADR
0013), and the triage card's `description_excerpt`, plain text capped at `EXCERPT_MAX` (ADR
0014). Numbers are copied, never recomputed from
today's config: a job's required years are the parser's own number or the gate's own words.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from job_match.config.schema import Settings
from job_match.domain.models import (
    STRETCH_NOTE_PREFIX,
    Eligibility,
    Job,
    LeadDetail,
    RunRecord,
)
from job_match.normalization.company import normalize_company
from job_match.normalization.location import department_of
from job_match.normalization.title import normalize_title
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository, LeadRepository, RunRepository
from job_match.tracking.constants import job_key

RUN_PIPELINES: tuple[str, ...] = ("jobs", "jobs_reprocess")
RUN_LIMIT = 30

# Keys copied from a stored run summary. `by_keyword` and `queries` carry the profile's
# search keywords and are deliberately absent; `by_area`/`by_department` are noise here.
RUN_KEYS: tuple[str, ...] = (
    "fetched",
    "normalized",
    "rejected_by_reason",
    "duplicates",
    "self_links_dropped",
    "stale_links_dropped",
    "eligible",
    "strong",
    "stretch",
    "errors",
    "api_calls",
    "checked",
    "closed",
    "by_source",
)

_STRETCH_YEARS_RE = re.compile(r"requires (\d+(?:\.\d+)?)y")
EVIDENCE_MAX = 240
EXCERPT_MAX = 600
_TAG_RE = re.compile(r"<[^>]*>")
# Statuses a job keeps its place in the Candidatures board for, closed offer or not.
TRACKED_STATUSES: tuple[str, ...] = ("to_apply", "applied", "interview", "rejected")


def safe_url(url: str | None) -> str | None:
    """Only http(s) links reach the page; anything else (javascript:, data:, '') is dropped."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return url


def required_years(job: Job) -> float | None:
    """The years the posting asks for, or None when no number was ever stated.

    The parser's explicit minimum first; for a STRETCH job the gate's own note
    ("stretch: requires 3y, you have 2") carries the seniority-keyword minimum that gated it.
    The gate is never re-run here: today's keyword map may differ from the one that decided.
    A breakdown scored since M22 carries the gate's number directly.
    """
    detail = job.scoring_breakdown.experience_detail if job.scoring_breakdown else {}
    if "required_years" in detail:
        return detail["required_years"]
    if job.experience and job.experience.min_years is not None:
        return job.experience.min_years
    if job.eligibility is Eligibility.STRETCH and job.scoring_breakdown:
        for line in job.scoring_breakdown.explanations:
            if line.startswith(STRETCH_NOTE_PREFIX):
                m = _STRETCH_YEARS_RE.search(line)
                if m:
                    return float(m.group(1))
    return None


def section_of(job: Job, strong_threshold: int) -> str:
    """strong / eligible / stretch, the digest's split (a stretch job is never strong)."""
    if job.eligibility is Eligibility.STRETCH:
        return "stretch"
    if job.score is not None and job.score >= strong_threshold:
        return "strong"
    return "eligible"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def posted_at(job: Job) -> datetime:
    """The posting date the source gave, else the day we first saw the offer."""
    return job.published_at or job.collected_at


def _evidence(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= EVIDENCE_MAX else text[: EVIDENCE_MAX - 1] + "…"


def why_entry(job: Job) -> dict:
    """The "Pourquoi cette offre ?" panel: what was found, where, and what it weighed.

    Rows scored before M22 have no evidence and no basis: the panel says so rather than
    guessing (basis None).
    """
    bd = job.scoring_breakdown
    if bd is None:
        return {"skills": [], "unlisted": [], "lowered": [], "experience": None}
    detail = bd.experience_detail
    exp = job.experience
    return {
        "skills": [
            {"name": n, "weight": bd.weights.get(n), "snippet": _evidence(bd.evidence.get(n))}
            for n in bd.positive_matches
        ],
        "unlisted": [
            {"name": n, "snippet": _evidence(s)} for n, s in sorted(bd.unlisted.items())
        ],
        # Only negative skills lower a score; a missing preferred skill adds nothing and
        # takes nothing away (it stays in `missing`).
        "lowered": [
            {"name": n, "weight": bd.weights.get(n), "snippet": _evidence(bd.evidence.get(n))}
            for n in bd.negative_matches
        ],
        "experience": {
            "required_years": required_years(job),
            "basis": detail.get("basis"),
            "sentence": _evidence(detail.get("sentence")),
            "excludes_apprenticeship": bool(
                detail.get("excludes_apprenticeship", exp.excludes_apprenticeship if exp else False)
            ),
        },
    }


def description_excerpt(text: str | None) -> str:
    """The start of the description as plain text: markup and entities removed, whitespace
    collapsed, at most `EXCERPT_MAX` characters, cut at a word with "…". The page sets it with
    textContent; this only keeps tags from showing up as text."""
    if not text:
        return ""
    plain = " ".join(html.unescape(_TAG_RE.sub(" ", text)).split())
    plain = _TAG_RE.sub(" ", plain)  # entities that decoded into tags
    plain = " ".join(plain.split())
    if len(plain) <= EXCERPT_MAX:
        return plain
    cut = plain[: EXCERPT_MAX - 1]
    space = cut.rfind(" ")
    if space > EXCERPT_MAX * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


def group_key(job: Job) -> str | None:
    """Same employer + same normalized title: the page shows one row when such postings sit in
    several departments. No employer name, no group (two hidden employers are not one)."""
    company = normalize_company(job.company or "")
    if not company:
        return None
    return f"{company}|{normalize_title(job.title or '')}"


def job_entry(job: Job, strong_threshold: int, now: datetime) -> dict:
    bd = job.scoring_breakdown
    posted = posted_at(job)
    return {
        "id": job.id,
        # The tracking key in D1 (`source:source_job_id`), stable across DB rebuilds.
        "key": job_key(job.source, job.source_job_id),
        "group": group_key(job),
        "section": section_of(job, strong_threshold),
        "title": job.title,
        "company": job.company,
        "department": department_of(job.location),
        "location": job.location,
        "contract": job.contract_type.value,
        "source": job.source,
        "score": job.score,
        "required_years": required_years(job),
        "experience_status": job.experience.status.value if job.experience else None,
        "collected_at": _iso(job.collected_at),
        "published_at": _iso(job.published_at),
        "posted_at": posted.isoformat(),
        "age_days": max((now - posted).days, 0),  # as of generated_at; the page is a snapshot
        "url": safe_url(job.url),
        "explanations": list(bd.explanations) if bd else [],
        "positive": list(bd.positive_matches) if bd else [],
        "negative": list(bd.negative_matches) if bd else [],
        "missing": list(bd.missing_preferences) if bd else [],
        "why": why_entry(job),
        "description_excerpt": description_excerpt(job.description),
    }


def lead_entry(lead: LeadDetail) -> dict:
    return {
        "id": lead.lead_id,
        "company": lead.company,
        "priority": lead.priority,
        "reason": lead.reason,
        "amount": lead.amount,
        "currency": lead.currency,
        "round": lead.round,
        "investors": list(lead.investors) if lead.investors else [],
        "hiring": lead.hiring,
        "country": lead.country,
        "source": lead.source,
        "published_at": _iso(lead.published_at),
        "created_at": _iso(lead.created_at),
        "article_url": safe_url(lead.article_url),
        "article_title": lead.article_title,
        "evidence": dict(lead.evidence),
        "open_jobs": lead.open_jobs,
    }


def run_entry(run: RunRecord) -> dict:
    s = run.summary
    entry: dict = {
        "id": run.id,
        "pipeline": run.pipeline,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }
    for key in RUN_KEYS:
        entry[key] = s.get(key, {} if key in ("rejected_by_reason", "by_source") else 0)
    # Unique rejected jobs are not stored (the per-reason map may count a job twice),
    # but the funnel is exact: everything fetched is rejected, a duplicate, eligible or stretch.
    entry["rejected"] = max(
        entry["fetched"] - entry["duplicates"] - entry["eligible"] - entry["stretch"], 0
    )
    return entry


def build_dashboard_data(db: Database, settings: Settings, now: datetime) -> dict:
    # Closed offers and postings older than jobs.max_age_days never reach the page.
    jobs = JobRepository(db.conn).list_canonical_scored(
        now=now, max_age_days=settings.jobs.max_age_days
    )
    jobs_since = now - timedelta(days=settings.dedup_window_days)
    leads = LeadRepository(db.conn).list_details(jobs_since)
    runs = RunRepository(db.conn).list_recent(RUN_PIPELINES, limit=RUN_LIMIT)
    listed = {j.id for j in jobs}
    return {
        "generated_at": now.isoformat(),
        "thresholds": {
            "strong": settings.strong_threshold,
            "min_score": settings.digest.min_score,
        },
        "jobs": [job_entry(j, settings.strong_threshold, now) for j in jobs],
        # Offers behind a Candidatures card that the job list no longer shows (closed or old).
        "tracked": [
            job_entry(j, settings.strong_threshold, now)
            for j in JobRepository(db.conn).list_tracked(TRACKED_STATUSES)
            if j.id not in listed
        ],
        "leads": [lead_entry(lead) for lead in leads],
        "runs": [run_entry(r) for r in runs],
    }
