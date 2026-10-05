"""Digest-time lead selection (filters, order, cap) and min_score for jobs."""
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_match.config.schema import DigestConfig, FundingConfig, LeadFilterConfig, Settings
from job_match.domain.models import LeadDetail
from job_match.notification.assemble import build_digest
from job_match.notification.lead_filter import amount_eur, exclusion_reason, select_leads
from job_match.persistence.db import Database
from job_match.persistence.repositories import FundingEventRepository, LeadRepository

from ._seed import NOW, funding, job

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"


def _lead(i: int, *, priority="normal", amount=1e6, currency="EUR", country=None,
          title="Acme lève des fonds", evidence=None, age_days=0, round_=None,
          published_days_ago=None) -> LeadDetail:
    published = NOW - timedelta(days=published_days_ago) if published_days_ago is not None else None
    return LeadDetail(
        lead_id=i, company_id=i, company=f"Co{i}", priority=priority, reason="r",
        created_at=NOW - timedelta(days=age_days), source="maddyness",
        article_url=f"https://x.test/{i}", article_title=title, amount=amount,
        currency=currency if amount else None, country=country, evidence=evidence or {},
        round=round_, published_at=published,
    )


CFG = LeadFilterConfig(countries=["France"])


# ---------------------------------------------------------------------------
# exclusion_reason / amount_eur
# ---------------------------------------------------------------------------

def test_foreign_country_excluded_unknown_and_france_kept():
    assert exclusion_reason(_lead(1, country="Switzerland"), CFG) == "country"
    assert exclusion_reason(_lead(2, country=None), CFG) is None
    assert exclusion_reason(_lead(3, country="France"), CFG) is None


def test_empty_country_list_disables_country_filter():
    assert exclusion_reason(_lead(1, country="Germany"), LeadFilterConfig(countries=[])) is None


def test_min_amount_uses_fx_and_lets_unknown_pass():
    cfg = LeadFilterConfig(countries=[], min_amount_eur=1_000_000)
    assert exclusion_reason(_lead(1, amount=500_000), cfg) == "amount"
    assert exclusion_reason(_lead(2, amount=1_200_000, currency="USD"), cfg) is None  # 1.1 M€
    assert exclusion_reason(_lead(3, amount=1_000_000, currency="USD"), cfg) == "amount"
    assert exclusion_reason(_lead(4, amount=None), cfg) is None
    assert amount_eur(_lead(5, amount=1e6, currency="JPY"), cfg.fx_to_eur) is None


def test_sector_keyword_in_title_or_evidence():
    cfg = LeadFilterConfig(countries=[], exclude_sectors=["crypto", "immobilier"])
    assert exclusion_reason(_lead(1, title="Acme lève 5 M€ pour sa plateforme crypto"),
                            cfg) == "sector"
    assert exclusion_reason(_lead(2, evidence={"funding": "Acme, acteur de l'Immobilier"}),
                            cfg) == "sector"
    assert exclusion_reason(_lead(3, title="Acme lève 5 M€ pour le cloud"), cfg) is None


# ---------------------------------------------------------------------------
# select_leads: order + cap
# ---------------------------------------------------------------------------

def test_order_is_hiring_then_early_round_then_recency_never_amount():
    leads = [
        _lead(1, priority="normal", amount=1.2e9, round_="series d"),       # megadeal, late
        _lead(2, priority="high", round_=None, age_days=3),
        _lead(3, priority="high", round_="seed", age_days=5),
        _lead(4, priority="normal", amount=2e6, round_="pre-seed", age_days=2),
        _lead(5, priority="normal", amount=5e6, round_="series b", age_days=1),
        _lead(6, priority="normal", amount=None, round_=None),               # unknown round
        _lead(7, priority="normal", round_="seed", country="Germany"),       # filtered
    ]
    sel = select_leads(leads, CFG, max_leads=4)
    # high: early round (3) before unknown round (2); normal early rounds by recency: 5, 4
    assert [lead.lead_id for lead in sel.selected] == [3, 2, 5, 4]
    assert sel.filtered == {"country": 1}
    assert sel.overflow == 2  # the megadeal (1) and the unknown round (6) roll over


def test_recency_uses_publication_date_when_known():
    older_article = _lead(1, round_="seed", age_days=0, published_days_ago=10)
    newer_article = _lead(2, round_="seed", age_days=1, published_days_ago=1)
    sel = select_leads([older_article, newer_article], CFG, max_leads=2)
    assert [lead.lead_id for lead in sel.selected] == [2, 1]


# ---------------------------------------------------------------------------
# build_digest + CLI: only emailed items are marked
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _settings(max_leads: int = 1) -> Settings:
    return Settings(strong_threshold=70, digest=DigestConfig(min_score=60, max_leads=max_leads),
                    funding=FundingConfig(lead_filters=LeadFilterConfig(countries=["France"])))


def test_build_digest_applies_min_score_filters_and_cap(db):
    low = job(db.conn, "J1", "Acme", score=55)
    ok = job(db.conn, "J2", "Acme", score=61)
    funding(db.conn, "big", "Big", amount=50e6, round_="series d")
    funding(db.conn, "small", "Small", amount=1e6, round_="seed")  # early round ranks first
    event, _ = funding(db.conn, "swiss", "Swiss Co", amount=90e6)
    db.conn.execute("UPDATE funding_events SET country='Switzerland' WHERE id=?", (event.id,))
    db.conn.commit()

    batch = build_digest(db, _settings(max_leads=1), NOW)

    assert batch.job_ids == (ok.id,)
    assert low.id not in batch.job_ids
    assert batch.jobs_below_min_score == 1
    assert [lead.company for lead in batch.data.leads] == ["Small"]
    assert batch.leads_filtered == {"country": 1}
    assert batch.leads_overflow == 1


def test_event_country_round_trip(db):
    event, _ = funding(db.conn, "a", "Acme")
    repo = FundingEventRepository(db.conn)
    saved = repo.upsert(FundingEventRepository(db.conn).get(event.id).__class__(
        **{**{f: getattr(event, f) for f in event.__slots__}, "country": "France"}))
    assert repo.get(saved.id).country == "France"
    [detail] = LeadRepository(db.conn).list_unnotified_details(NOW)
    assert detail.country == "France"


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        "strong_threshold: 70\ndigest:\n  min_score: 60\n  max_leads: 1\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JOB_MATCH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("JOB_MATCH_DATA_DIR", raising=False)
    return tmp_path


def _send(capsys=None):
    from job_match.cli import _cmd_digest

    notifier = MagicMock()
    notifier.send.return_value = True
    with patch("job_match.notification.email_notifier.EmailNotifier") as cls:
        cls.from_env.return_value = notifier
        _cmd_digest(argparse.Namespace(dry_run=False, resend_since=None))
    return notifier.send.call_args.args[0]


def test_overflow_lead_rolls_over_to_next_digest_and_low_score_job_is_never_marked(tmp_project):
    db_path = str(tmp_project / "data" / "jobs.sqlite")
    with Database(path=db_path) as d:
        now = datetime.now(UTC)
        funding(d.conn, "early", "Early", round_="seed", created_at=now)
        funding(d.conn, "late", "Late", round_="series d", created_at=now)
        job(d.conn, "LOW", "Acme", score=40, collected_at=datetime.now(UTC))

    first = _send()
    second = _send()

    assert [lead.company for lead in first.leads] == ["Early"]
    assert [lead.company for lead in second.leads] == ["Late"]  # rolled over
    with Database(path=db_path) as d:
        low = d.conn.execute("SELECT notified_at FROM jobs WHERE source_job_id='LOW'").fetchone()
    assert low["notified_at"] is None
