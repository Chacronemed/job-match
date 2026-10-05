"""M12: Lead ↔ Company ↔ Job links and the funding-leads section of the digest."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from job_match.config.schema import FundingConfig, Settings
from job_match.domain.models import Eligibility
from job_match.notification.assemble import build_digest
from job_match.notification.digest import DigestData, evidence_lines, render_html, render_text
from job_match.persistence.db import Database
from job_match.persistence.repositories import (
    FundingEventRepository,
    JobDuplicateRepository,
    LeadRepository,
)

from ._seed import NOW, company, funding, job

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _settings(job_link_days: int = 180) -> Settings:
    return Settings(strong_threshold=70, dedup_window_days=30,
                    funding=FundingConfig(job_link_days=job_link_days))


# ---------------------------------------------------------------------------
# Repository: FundingEventRepository.latest_by_company
# ---------------------------------------------------------------------------

def test_latest_by_company_picks_newest_event_in_window(db):
    funding(db.conn, "old", "Inbolt", date="2026-03-01", amount=2e6, with_lead=False)
    funding(db.conn, "new", "Inbolt", date="2026-10-02", amount=1.1e7, with_lead=False)
    c = company(db.conn, "Inbolt")

    got = FundingEventRepository(db.conn).latest_by_company([c.id], date(2026, 1, 1))

    assert got[c.id].amount == 1.1e7
    assert got[c.id].date == "2026-10-02"
    assert got[c.id].article_url == "https://www.maddyness.com/new"


def test_latest_by_company_excludes_events_outside_window(db):
    funding(db.conn, "old", "Inbolt", date="2025-01-01", with_lead=False)
    c = company(db.conn, "Inbolt")
    assert FundingEventRepository(db.conn).latest_by_company([c.id], date(2026, 4, 1)) == {}


def test_latest_by_company_falls_back_to_collection_date(db):
    funding(db.conn, "nodate", "Inbolt", date=None, with_lead=False)  # collected NOW
    c = company(db.conn, "Inbolt")
    got = FundingEventRepository(db.conn).latest_by_company([c.id], date(2026, 10, 1))
    assert got[c.id].date == NOW.date().isoformat()


def test_latest_by_company_empty_input(db):
    assert FundingEventRepository(db.conn).latest_by_company([], date(2026, 1, 1)) == {}


# ---------------------------------------------------------------------------
# Repository: LeadRepository digest read model + notification state
# ---------------------------------------------------------------------------

def test_unnotified_details_high_priority_first_then_newest(db):
    funding(db.conn, "a", "Alpha", priority="normal", created_at=NOW)
    funding(db.conn, "b", "Beta", priority="high", hiring="recruter 20 personnes",
            created_at=NOW - timedelta(days=2))
    funding(db.conn, "c", "Gamma", priority="normal", created_at=NOW - timedelta(days=1))

    leads = LeadRepository(db.conn).list_unnotified_details(NOW - timedelta(days=30))

    assert [lead.company for lead in leads] == ["Beta", "Alpha", "Gamma"]
    beta = leads[0]
    assert beta.priority == "high"
    assert beta.hiring == "recruter 20 personnes"
    assert beta.investors == ("Shift4Good",)
    assert beta.article_url == "https://www.maddyness.com/b"
    assert beta.source == "maddyness"
    assert "amount" in beta.evidence


def test_open_jobs_counts_only_eligible_canonical_recent_jobs_of_same_company(db):
    funding(db.conn, "a", "Inbolt")
    job(db.conn, "J1", "INBOLT SAS")  # same normalized company → counted
    canonical = job(db.conn, "J2", "Inbolt")  # counted
    dup = job(db.conn, "J3", "Inbolt")  # duplicate → not counted
    JobDuplicateRepository(db.conn).save_link(canonical.id, dup.id, "exact", 1.0)
    job(db.conn, "J4", "Inbolt", eligibility=Eligibility.REJECTED)  # rejected → not counted
    job(db.conn, "J5", "Inbolt", collected_at=NOW - timedelta(days=60))  # stale → not counted
    job(db.conn, "J6", "Other Co")  # other company → not counted

    [lead] = LeadRepository(db.conn).list_unnotified_details(NOW - timedelta(days=30))
    assert lead.open_jobs == 2


def test_lead_mark_notified_and_reset(db):
    _, lead = funding(db.conn, "a", "Inbolt")
    repo = LeadRepository(db.conn)
    repo.mark_notified([lead.id], NOW)
    assert repo.list_unnotified_details(NOW) == []
    assert repo.get(lead.id).notified_at == NOW

    assert repo.reset_notified_since(NOW.date()) == 1
    assert len(repo.list_unnotified_details(NOW)) == 1


# ---------------------------------------------------------------------------
# build_digest: the Lead ↔ Company ↔ Job link
# ---------------------------------------------------------------------------

def test_build_digest_flags_job_whose_company_recently_raised(db):
    funding(db.conn, "inbolt", "Inbolt", date="2026-10-02")
    funded_job = job(db.conn, "J1", "INBOLT")  # FT spelling, same normalized company
    other_job = job(db.conn, "J2", "Acme", score=65)  # >= digest.min_score (60)

    batch = build_digest(db, _settings(), NOW)

    assert funded_job.company_id in batch.data.company_funding
    assert other_job.company_id not in batch.data.company_funding
    assert set(batch.job_ids) == {funded_job.id, other_job.id}
    [lead] = batch.data.leads
    assert lead.open_jobs == 1  # reverse link: the lead knows its company has a job
    assert batch.lead_ids == (lead.lead_id,)


def test_build_digest_does_not_flag_old_funding(db):
    funding(db.conn, "inbolt", "Inbolt", date="2025-01-01", with_lead=False)
    funded_job = job(db.conn, "J1", "Inbolt")
    batch = build_digest(db, _settings(job_link_days=180), NOW)
    assert funded_job.company_id not in batch.data.company_funding


def test_build_digest_empty(db):
    batch = build_digest(db, _settings(), NOW)
    assert batch.is_empty
    assert batch.data.leads == ()


def test_lead_is_never_listed_as_a_job(db):
    funding(db.conn, "inbolt", "Inbolt")
    batch = build_digest(db, _settings(), NOW)
    assert batch.job_ids == ()
    assert batch.data.strong == () and batch.data.eligible == ()
    assert len(batch.data.leads) == 1


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _digest(db) -> DigestData:
    funding(db.conn, "n", "Alpha", priority="normal")
    funding(db.conn, "h", "Beta", priority="high", hiring="recruter 20 personnes")
    job(db.conn, "J1", "Beta")
    return build_digest(db, _settings(), NOW).data


def test_html_has_separate_leads_section_high_priority_first(db):
    out = render_html(_digest(db))
    assert "Funding Leads (2)" in out
    leads_part = out.split("Funding Leads (2)")[1]
    assert leads_part.index("Beta") < leads_part.index("Alpha")
    assert "HIGH · hiring" in leads_part
    assert "href='https://www.maddyness.com/h'" in leads_part
    assert "Beta lève 11 millions d&#x27;euros." in leads_part  # evidence, escaped
    assert "1 eligible job at this company" in leads_part
    assert "2 funding leads" in out  # subtitle


def test_html_job_card_shows_company_funding_badge(db):
    out = render_html(_digest(db))
    jobs_part = out.split("Funding Leads")[0]
    assert "Company funding:" in jobs_part
    assert "Raised 11 M€ series a (2026-10-02)" in jobs_part


def test_html_escapes_evidence_and_article_title(db):
    funding(db.conn, "x", "Evil", evidence={"amount": "<script>alert(1)</script> lève 1 M€"})
    out = render_html(build_digest(db, _settings(), NOW).data)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_html_empty_leads_section(db):
    out = render_html(build_digest(db, _settings(), NOW).data)
    assert "Funding Leads (0)" in out
    assert "No new funding leads." in out


def test_text_render_lists_leads_with_evidence_and_link(db):
    out = render_text(_digest(db))
    assert "=== Funding Leads (2) ===" in out
    section = out.split("=== Funding Leads (2) ===")[1]
    assert section.index("[HIGH] Beta") < section.index("[norm] Alpha")
    assert "hiring: recruter 20 personnes" in section
    assert "> amount, company: Beta lève 11 millions d'euros." in section
    assert "https://www.maddyness.com/h" in section
    assert "$ Company funding: Raised 11 M€ series a (2026-10-02)" in out


def test_evidence_lines_group_shared_sentences_and_cap():
    ev = {"funding": "S1", "company": "S1", "amount": "S1", "round": "S2", "hiring": "S3",
          "investors": "S4"}
    lines = evidence_lines(ev)
    assert lines[0] == ("amount, company, funding", "S1")
    assert len(lines) == 3
