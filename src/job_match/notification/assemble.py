"""Assemble the digest content from the database. Read-only: marking is the caller's job,
and only after a successful send."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from job_match.config.schema import Settings
from job_match.notification.digest import DigestData
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    FundingEventRepository,
    JobRepository,
    LeadRepository,
)


@dataclass(frozen=True, slots=True)
class DigestBatch:
    data: DigestData
    job_ids: tuple[int, ...]
    lead_ids: tuple[int, ...]

    @property
    def is_empty(self) -> bool:
        return not self.job_ids and not self.lead_ids


def build_digest(db: Database, settings: Settings, now: datetime) -> DigestBatch:
    jobs = JobRepository(db.conn).list_unnotified()
    strong = tuple(
        j for j in jobs if j.score is not None and j.score >= settings.strong_threshold
    )
    eligible = tuple(j for j in jobs if j not in strong)

    # Job -> company -> recent funding. Same `companies.id`, i.e. same normalized name.
    funding_since = (now - timedelta(days=settings.funding.job_link_days)).date()
    company_ids = [j.company_id for j in jobs if j.company_id is not None]
    company_funding = FundingEventRepository(db.conn).latest_by_company(
        company_ids, funding_since
    )

    # Lead -> company -> open jobs (jobs collected within the dedup window count as live).
    jobs_since = now - timedelta(days=settings.dedup_window_days)
    leads = tuple(LeadRepository(db.conn).list_unnotified_details(jobs_since))

    data = DigestData(
        strong=strong,
        eligible=eligible,
        leads=leads,
        company_funding=company_funding,
        generated_at=now,
    )
    return DigestBatch(
        data=data,
        job_ids=tuple(j.id for j in jobs if j.id is not None),
        lead_ids=tuple(lead.lead_id for lead in leads),
    )
