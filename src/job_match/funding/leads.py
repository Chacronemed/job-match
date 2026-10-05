"""Lead rule: a Lead exists only for a stored FundingEvent. Pure functions, no I/O."""
from datetime import datetime

from job_match.domain.models import FundingEvent, Lead
from job_match.funding.extractor import FundingExtraction, format_amount

PRIORITY_HIGH = "high"
PRIORITY_NORMAL = "normal"
_MAX_REASON = 200


def lead_priority(extraction: FundingExtraction) -> str:
    """A hiring signal is the only thing that raises priority."""
    return PRIORITY_HIGH if extraction.hiring else PRIORITY_NORMAL


def lead_reason(extraction: FundingExtraction) -> str:
    amount = format_amount(extraction.amount, extraction.currency) or "amount unknown"
    parts = [f"funding {amount}"]
    if extraction.round:
        parts.append(extraction.round)
    reason = " ".join(parts)
    if extraction.hiring:
        reason += f"; hiring: {extraction.hiring}"
    return reason[:_MAX_REASON]


def build_lead(event: FundingEvent, extraction: FundingExtraction, now: datetime) -> Lead:
    if event.id is None:
        raise ValueError("build_lead needs a stored FundingEvent (id is None)")
    return Lead(
        company_id=event.company_id,
        funding_event_id=event.id,
        reason=lead_reason(extraction),
        created_at=now,
        priority=lead_priority(extraction),
    )
