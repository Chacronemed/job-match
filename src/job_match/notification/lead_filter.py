"""Digest-time lead selection: relevance filters, ordering (hiring, early round, recency)
and volume cap. Pure, no I/O.

Filtered and overflow leads are not deleted or marked: they stay in the DB, unnotified.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from job_match.config.schema import LeadFilterConfig
from job_match.domain.models import LeadDetail
from job_match.normalization.skills import title_keyword
from job_match.normalization.text import normalize_text


@dataclass(frozen=True, slots=True)
class LeadSelection:
    selected: tuple[LeadDetail, ...]
    filtered: dict[str, int] = field(default_factory=dict)  # reason -> count
    overflow: int = 0


def amount_eur(lead: LeadDetail, fx_to_eur: dict[str, float]) -> float | None:
    if lead.amount is None:
        return None
    if lead.currency in (None, "EUR"):
        return lead.amount
    rate = fx_to_eur.get(lead.currency.upper())
    return lead.amount * rate if rate is not None else None


def exclusion_reason(lead: LeadDetail, cfg: LeadFilterConfig) -> str | None:
    """Why a lead is not emailed, or None. Unknown country / unknown amount always pass."""
    allowed = {normalize_text(c) for c in cfg.countries}
    if allowed and lead.country and normalize_text(lead.country) not in allowed:
        return "country"
    if cfg.min_amount_eur is not None:
        eur = amount_eur(lead, cfg.fx_to_eur)
        if eur is not None and eur < cfg.min_amount_eur:
            return "amount"
    if cfg.exclude_sectors:
        haystack = " ".join([lead.article_title, *lead.evidence.values()])
        if title_keyword(haystack, cfg.exclude_sectors):
            return "sector"
    return None


# Early-stage rounds first: those companies are most likely to build a team from scratch.
EARLY_ROUNDS = frozenset({"pre-seed", "seed", "series a", "series b"})


def _sort_key(lead: LeadDetail) -> tuple:
    """Hiring signal first, then early rounds (later/unknown after), then most recent.
    Amount is deliberately not a criterion: it favours foreign megadeals."""
    when = lead.published_at or lead.created_at
    return (
        0 if lead.priority == "high" else 1,
        0 if lead.round in EARLY_ROUNDS else 1,
        -when.timestamp(),
        lead.lead_id,
    )


def select_leads(
    leads: list[LeadDetail] | tuple[LeadDetail, ...], cfg: LeadFilterConfig, max_leads: int
) -> LeadSelection:
    kept: list[LeadDetail] = []
    filtered: dict[str, int] = {}
    for lead in leads:
        reason = exclusion_reason(lead, cfg)
        if reason:
            filtered[reason] = filtered.get(reason, 0) + 1
        else:
            kept.append(lead)
    kept.sort(key=_sort_key)
    cap = max(0, max_leads)
    return LeadSelection(
        selected=tuple(kept[:cap]), filtered=filtered, overflow=max(0, len(kept) - cap)
    )
