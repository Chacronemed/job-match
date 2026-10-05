from datetime import UTC, datetime

import pytest

from job_match.domain.models import FundingEvent
from job_match.funding.extractor import FundingExtraction
from job_match.funding.leads import PRIORITY_HIGH, PRIORITY_NORMAL, build_lead, lead_reason

_NOW = datetime(2026, 10, 4, 9, 0, 0, tzinfo=UTC)


def _event(event_id: int | None = 7) -> FundingEvent:
    return FundingEvent(
        company_id=3, source="maddyness", article_url="https://x.test/a",
        collected_at=_NOW, id=event_id, article_id=11,
    )


def test_hiring_signal_raises_priority():
    with_hiring = FundingExtraction(is_funding=True, company="Acme", hiring="recruter 30 personnes")
    without = FundingExtraction(is_funding=True, company="Acme")
    assert build_lead(_event(), with_hiring, _NOW).priority == PRIORITY_HIGH
    assert build_lead(_event(), without, _NOW).priority == PRIORITY_NORMAL


def test_reason_formats():
    full = FundingExtraction(is_funding=True, company="Acme", amount=1e7, currency="EUR",
                             round="series a", hiring="recruter une trentaine de personnes")
    assert lead_reason(full) == (
        "funding 10 M€ series a; hiring: recruter une trentaine de personnes"
    )
    unknown = FundingExtraction(is_funding=True, company="Acme")
    assert lead_reason(unknown) == "funding amount unknown"
    usd = FundingExtraction(is_funding=True, company="Acme", amount=5e6, currency="USD",
                            round="seed")
    assert lead_reason(usd) == "funding $5M seed"


def test_reason_is_bounded():
    ex = FundingExtraction(is_funding=True, company="Acme", hiring="x" * 500)
    assert len(lead_reason(ex)) <= 200


def test_build_lead_links_event_and_company():
    lead = build_lead(_event(), FundingExtraction(is_funding=True, company="Acme"), _NOW)
    assert (lead.company_id, lead.funding_event_id) == (3, 7)
    assert lead.status == "new"
    assert lead.created_at == _NOW
    assert lead.notified_at is None


def test_build_lead_requires_stored_event():
    with pytest.raises(ValueError):
        build_lead(_event(event_id=None), FundingExtraction(is_funding=True), _NOW)
