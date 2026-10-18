"""Seed a small DB for the dashboard tests: three tiers, a duplicate, a rejected job, a lead
and a few runs. Titles carry markup on purpose: they come from external sources in production."""
from datetime import UTC, datetime

from job_match.domain.models import (
    Article,
    Company,
    ContractType,
    Eligibility,
    ExperienceRequirement,
    ExperienceStatus,
    FundingEvent,
    Job,
    Lead,
    RunSummary,
    ScoringBreakdown,
    WorkplaceType,
)
from job_match.normalization.company import normalize_company
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    ArticleRepository,
    CompanyRepository,
    FundingEventRepository,
    JobDuplicateRepository,
    JobRepository,
    LeadRepository,
    RunRepository,
)

NOW = datetime(2026, 10, 18, 7, 0, 0, tzinfo=UTC)
XSS_TITLE = '</script><script>alert(1)</script><img src=x onerror=alert(2)> <!-- x -->'
SECRET_KEYWORD = "my private search keyword"


def _breakdown(score, explanations=(), positive=(), negative=(), missing=()):
    return ScoringBreakdown(
        eligible=True,
        experience=ExperienceStatus.ELIGIBLE,
        score=score,
        positive_matches=tuple(positive),
        negative_matches=tuple(negative),
        missing_preferences=tuple(missing),
        explanations=tuple(explanations),
    )


def _job(sid, title, company_name, *, score, eligibility, location="75 - Paris",
         experience=None, breakdown=None, url=None, collected_at=NOW, rejection_reason=None,
         company_id=None):
    return Job(
        source="france_travail",
        source_job_id=sid,
        title=title,
        company=company_name,
        location=location,
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="Kubernetes, Terraform. Secret description text that must never leave the DB.",
        url=url if url is not None else f"https://example.test/{sid}",
        collected_at=collected_at,
        company_id=company_id,
        eligibility=eligibility,
        rejection_reason=rejection_reason,
        experience=experience,
        score=score,
        scoring_breakdown=breakdown,
        search_query=SECRET_KEYWORD,
    )


def seed(db: Database) -> dict:
    """Populate `db`; returns the ids the tests assert on."""
    conn = db.conn
    jobs = JobRepository(conn)
    companies = CompanyRepository(conn)

    acme = companies.upsert(Company(name="Acme", normalized_name=normalize_company("Acme")))

    strong = jobs.save(_job(
        "strong", XSS_TITLE, "Acme", score=85, eligibility=Eligibility.ELIGIBLE,
        company_id=acme.id,
        experience=ExperienceRequirement(ExperienceStatus.ELIGIBLE, 2, None, "2 ans"),
        breakdown=_breakdown(85, ["+15 kubernetes (title)", "+10 terraform"],
                             positive=["kubernetes", "terraform"], missing=["aws"]),
    ))

    eligible = jobs.save(_job(
        "eligible", "Ingénieur DevOps", "Beta <b>Corp</b>", score=65,
        eligibility=Eligibility.ELIGIBLE, location="Télétravail",
        breakdown=_breakdown(65, ["+15 docker"], positive=["docker"], negative=["php"]),
        url="javascript:alert(1)",
    ))
    stretch = jobs.save(_job(
        "stretch", "SRE confirmé", "Gamma", score=72, eligibility=Eligibility.STRETCH,
        location="69 - Lyon",
        experience=ExperienceRequirement(ExperienceStatus.UNKNOWN, None, None, None),
        breakdown=_breakdown(72, ["stretch: requires 3y, you have 2", "+12 kubernetes"],
                             positive=["kubernetes"]),
    ))
    duplicate = jobs.save(_job(
        "dup", "Ingénieur DevOps (H/F)", "Acme", score=90, eligibility=Eligibility.ELIGIBLE,
    ))
    JobDuplicateRepository(conn).save_link(strong.id, duplicate.id, "exact")
    rejected = jobs.save(_job(
        "rejected", "Senior DevOps", "Delta", score=None, eligibility=Eligibility.REJECTED,
        rejection_reason="EXPERIENCE",
    ))

    article = ArticleRepository(conn).save(Article(
        source="maddyness", url="https://www.maddyness.com/acme-leve",
        title="Acme lève 11 millions", collected_at=NOW, published_at=NOW,
    ))
    event = FundingEventRepository(conn).upsert(FundingEvent(
        company_id=acme.id, source="maddyness", article_url=article.url,
        article_id=article.id, collected_at=NOW, amount=1.1e7, currency="EUR",
        round="series a", date="2026-10-17", investors=("Shift4Good",),
        recruiting_signal="recruter 30 personnes",
        evidence={"amount": "Acme lève 11 millions d'euros.",
                  "hiring": "Acme veut recruter 30 personnes."},
        country="France",
    ))
    lead = LeadRepository(conn).upsert(Lead(
        company_id=acme.id, funding_event_id=event.id, reason="funding 11 M€ series a; hiring",
        created_at=NOW, priority="high", notified_at=NOW,
    ))

    runs = RunRepository(conn)
    run_ids = []
    for i in range(32):
        run_ids.append(runs.save(
            RunSummary(
                pipeline="jobs", fetched=100 + i, duplicates=5, eligible=20, strong=8,
                stretch=3, errors=1 if i == 0 else 0, api_calls=13,
                rejected_by_reason={"EXPERIENCE": 50, "CONTRACT": 30, "NOT_RELEVANT": 10},
                by_source={"france_travail": {"fetched": 100 + i, "eligible": 20, "calls": 13}},
                by_keyword={SECRET_KEYWORD: 40},
            ),
            started_at=datetime(2026, 9, 1 + i % 28, 7, 0, tzinfo=UTC) if i < 28
            else datetime(2026, 10, 1 + i - 28, 7, 0, tzinfo=UTC),
        ))
    runs.save(RunSummary(pipeline="funding", fetched=9, articles=9), started_at=NOW)
    runs.save(
        RunSummary(pipeline="jobs_reprocess", fetched=533, duplicates=2, eligible=85,
                   strong=28, stretch=43, rejected_by_reason={"EXPERIENCE": 197}),
        started_at=datetime(2026, 10, 18, 9, 0, tzinfo=UTC),
    )

    return {
        "strong": strong.id, "eligible": eligible.id, "stretch": stretch.id,
        "duplicate": duplicate.id, "rejected": rejected.id, "lead": lead.id,
        "company": acme.id,
    }

