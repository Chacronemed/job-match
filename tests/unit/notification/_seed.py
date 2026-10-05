"""Shared DB seeding helpers for M12 digest tests (company, job, article, event, lead)."""
from datetime import UTC, datetime

from job_match.domain.models import (
    Article,
    Company,
    ContractType,
    Eligibility,
    FundingEvent,
    Job,
    Lead,
    WorkplaceType,
)
from job_match.normalization.company import normalize_company
from job_match.persistence.repositories import (
    ArticleRepository,
    CompanyRepository,
    FundingEventRepository,
    JobRepository,
    LeadRepository,
)

NOW = datetime(2026, 10, 5, 8, 0, 0, tzinfo=UTC)


def company(conn, name: str) -> Company:
    return CompanyRepository(conn).upsert(
        Company(name=name, normalized_name=normalize_company(name))
    )


def job(conn, sid: str, company_name: str, *, score: int = 80, collected_at=NOW,
        eligibility=Eligibility.ELIGIBLE) -> Job:
    c = company(conn, company_name)
    return JobRepository(conn).save(Job(
        source="france_travail", source_job_id=sid, title=f"DevOps {sid}",
        company=company_name, location="Paris", workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI, description="Kubernetes.", url=f"https://ft.test/{sid}",
        collected_at=collected_at, company_id=c.id, eligibility=eligibility, score=score,
    ))


def funding(conn, slug: str, company_name: str, *, date: str | None = "2026-10-02",
            amount: float | None = 1.1e7, round_: str | None = "series a",
            hiring: str | None = None, priority: str = "normal", created_at=NOW,
            evidence: dict | None = None, with_lead: bool = True):
    """Article + event (+ lead). Returns (event, lead_or_None)."""
    c = company(conn, company_name)
    article = ArticleRepository(conn).save(Article(
        source="maddyness", url=f"https://www.maddyness.com/{slug}",
        title=f"{company_name} lève des fonds", collected_at=created_at,
    ))
    event = FundingEventRepository(conn).upsert(FundingEvent(
        company_id=c.id, source="maddyness", article_url=article.url, article_id=article.id,
        collected_at=created_at, amount=amount, currency="EUR" if amount else None,
        round=round_, date=date, investors=("Shift4Good",), recruiting_signal=hiring,
        evidence=evidence if evidence is not None else
        {"amount": f"{company_name} lève 11 millions d'euros.", "company":
         f"{company_name} lève 11 millions d'euros."},
    ))
    lead = None
    if with_lead:
        lead = LeadRepository(conn).upsert(Lead(
            company_id=c.id, funding_event_id=event.id, reason="funding 11 M€ series a",
            created_at=created_at, priority=priority,
        ))
    return event, lead
