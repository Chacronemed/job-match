"""DigestData model and HTML/plain-text renderers.

All external content (job titles, companies, article titles, evidence sentences) is
HTML-escaped. Leads are a separate section: a Lead is never rendered as a Job.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from job_match.domain.models import CompanyFunding, Job, LeadDetail
from job_match.funding.extractor import format_amount

_EVIDENCE_ORDER = ("amount", "round", "investors", "hiring", "company", "funding", "location")
_MAX_EVIDENCE = 3


@dataclass(frozen=True, slots=True)
class DigestData:
    strong: tuple[Job, ...]
    eligible: tuple[Job, ...]  # non-strong eligible, unnotified
    run_stats: dict[str, int] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.now)
    leads: tuple[LeadDetail, ...] = ()  # unnotified, high priority first
    company_funding: dict[int, CompanyFunding] = field(default_factory=dict)  # by company_id


def _e(text: str | None) -> str:
    """HTML-escape external content (titles, companies, locations from APIs)."""
    return html.escape(text or "", quote=True)


def _top_matches(job: Job, n: int = 3) -> str:
    if job.scoring_breakdown and job.scoring_breakdown.positive_matches:
        return ", ".join(job.scoring_breakdown.positive_matches[:n])
    return "—"


def _funding_of(job: Job, data: DigestData) -> CompanyFunding | None:
    return data.company_funding.get(job.company_id) if job.company_id is not None else None


def _funding_label(f: CompanyFunding) -> str:
    """e.g. "Raised 11 M€ series a (2026-10-02)"; unknown parts are simply left out."""
    parts = ["Raised"]
    parts.append(format_amount(f.amount, f.currency) or "funds")
    if f.round:
        parts.append(f.round)
    label = " ".join(parts)
    return f"{label} ({f.date})" if f.date else label


def _lead_headline(lead: LeadDetail) -> str:
    parts = [format_amount(lead.amount, lead.currency) or "amount unknown"]
    if lead.round:
        parts.append(lead.round)
    return " · ".join(parts)


def evidence_lines(evidence: dict[str, str]) -> list[tuple[str, str]]:
    """Group fields that share a sentence: [("amount, round", "<sentence>"), ...]."""
    grouped: dict[str, list[str]] = {}
    for key in _EVIDENCE_ORDER:
        sentence = evidence.get(key)
        if sentence:
            grouped.setdefault(sentence, []).append(key)
    for key, sentence in evidence.items():  # unknown keys, kept for completeness
        if key not in _EVIDENCE_ORDER and sentence:
            grouped.setdefault(sentence, []).append(key)
    return [(", ".join(keys), sentence) for sentence, keys in grouped.items()][:_MAX_EVIDENCE]


def _subtitle(data: DigestData) -> str:
    total = len(data.strong) + len(data.eligible)
    text = f"{total} unnotified job{'s' if total != 1 else ''} ({len(data.strong)} strong)"
    if data.leads:
        n = len(data.leads)
        text += f", {n} funding lead{'s' if n != 1 else ''}"
    return text


def render_html(data: DigestData) -> str:
    parts: list[str] = []
    parts.append(
        "<!doctype html><html lang='fr'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Job Match Digest</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;"
        "padding:24px 16px;color:#1a1a1a;background:#fff}"
        "h1{font-size:1.4rem;margin-bottom:4px}"
        "h2{font-size:1.1rem;margin-top:32px;margin-bottom:12px;"
        "border-bottom:2px solid #e5e5e5;padding-bottom:6px}"
        ".meta{color:#666;font-size:.85rem;margin-bottom:24px}"
        ".job{margin-bottom:18px;padding:14px;border:1px solid #e5e5e5;border-radius:6px}"
        ".job-title{font-weight:600;font-size:1rem}"
        ".job-title a{color:#1a56db;text-decoration:none}"
        ".job-title a:hover{text-decoration:underline}"
        ".job-meta{color:#555;font-size:.85rem;margin-top:4px}"
        ".score{display:inline-block;background:#dbeafe;color:#1e3a8a;"
        "font-weight:700;font-size:.8rem;padding:2px 7px;border-radius:4px;margin-right:6px}"
        ".score-strong{background:#bbf7d0;color:#14532d}"
        ".matches{font-size:.82rem;color:#444;margin-top:5px}"
        ".funded{font-size:.82rem;color:#92400e;margin-top:5px}"
        ".funded a{color:#92400e}"
        ".prio{display:inline-block;font-weight:700;font-size:.75rem;padding:2px 7px;"
        "border-radius:4px;margin-right:6px;background:#e5e7eb;color:#374151}"
        ".prio-high{background:#fde68a;color:#78350f}"
        ".evidence{font-size:.8rem;color:#555;margin:6px 0 0;padding-left:10px;"
        "border-left:3px solid #e5e5e5}"
        ".stats{background:#f9fafb;padding:12px 16px;border-radius:6px;"
        "font-size:.85rem;line-height:1.8}"
        ".empty{color:#888;font-style:italic}"
        "</style>"
        "</head><body>"
    )

    ts = data.generated_at.strftime("%Y-%m-%d %H:%M")
    parts.append(
        f"<h1>Job Match Digest</h1>"
        f"<p class='meta'>Generated {_e(ts)} — {_e(_subtitle(data))}</p>"
    )

    if data.run_stats:
        parts.append("<h2>Last Run</h2><div class='stats'>")
        for k, v in data.run_stats.items():
            parts.append(f"<b>{_e(str(k))}</b>: {v}<br>")
        parts.append("</div>")

    def _job_card(job: Job, strong: bool) -> str:
        score_cls = "score score-strong" if strong else "score"
        score_str = str(job.score) if job.score is not None else "?"
        matches = _top_matches(job)
        loc = job.location or ""
        contract = str(job.contract_type).upper()
        via = f" · via &quot;{_e(job.search_query)}&quot;" if job.search_query else ""
        funded = _funding_of(job, data)
        funded_html = ""
        if funded is not None:
            label = _e(_funding_label(funded))
            if funded.article_url:
                label = f"<a href='{_e(funded.article_url)}'>{label}</a>"
            funded_html = f"<div class='funded'>Company funding: {label}</div>"
        return (
            f"<div class='job'>"
            f"<div class='job-title'>"
            f"<a href='{_e(job.url)}'>{_e(job.title)}</a>"
            f"</div>"
            f"<div class='job-meta'>"
            f"<span class='{score_cls}'>{score_str}</span>"
            f"{_e(job.company)} · {_e(loc)} · {contract}"
            f"</div>"
            f"<div class='matches'>+ {_e(matches)}{via}</div>"
            f"{funded_html}"
            f"</div>"
        )

    def _lead_card(lead: LeadDetail) -> str:
        high = lead.priority == "high"
        prio = (
            "<span class='prio prio-high'>HIGH · hiring</span>" if high
            else "<span class='prio'>normal</span>"
        )
        meta: list[str] = [_e(_lead_headline(lead))]
        if lead.country:
            meta.append(_e(lead.country))
        if lead.investors:
            meta.append("investors: " + _e(", ".join(lead.investors)))
        if lead.hiring:
            meta.append("hiring: " + _e(lead.hiring))
        if lead.open_jobs:
            s = "s" if lead.open_jobs != 1 else ""
            meta.append(f"{lead.open_jobs} eligible job{s} at this company")
        article = _e(lead.article_title or lead.article_url)
        if lead.article_url:
            article = f"<a href='{_e(lead.article_url)}'>{article}</a>"
        source = f" ({_e(lead.source)})" if lead.source else ""
        evidence = "".join(
            f"<p class='evidence'><b>{_e(keys)}</b>: «{_e(sentence)}»</p>"
            for keys, sentence in evidence_lines(lead.evidence)
        )
        return (
            f"<div class='job'>"
            f"<div class='job-title'>{prio}{_e(lead.company)}</div>"
            f"<div class='job-meta'>{' · '.join(meta)}</div>"
            f"<div class='matches'>Source: {article}{source}</div>"
            f"{evidence}"
            f"</div>"
        )

    parts.append(f"<h2>Strong Matches ({len(data.strong)})</h2>")
    if data.strong:
        for job in data.strong:
            parts.append(_job_card(job, strong=True))
    else:
        parts.append("<p class='empty'>No strong matches this run.</p>")

    parts.append(f"<h2>Other Eligible ({len(data.eligible)})</h2>")
    if data.eligible:
        for job in data.eligible:
            parts.append(_job_card(job, strong=False))
    else:
        parts.append("<p class='empty'>No other eligible jobs.</p>")

    parts.append(f"<h2>Funding Leads ({len(data.leads)})</h2>")
    if data.leads:
        for lead in data.leads:
            parts.append(_lead_card(lead))
    else:
        parts.append("<p class='empty'>No new funding leads.</p>")

    parts.append("</body></html>")
    return "".join(parts)


def render_text(data: DigestData) -> str:
    lines: list[str] = []
    ts = data.generated_at.strftime("%Y-%m-%d %H:%M")
    lines.append(f"Job Match Digest — {ts}")
    lines.append(_subtitle(data))
    lines.append("")

    if data.run_stats:
        lines.append("=== Last Run ===")
        for k, v in data.run_stats.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    def _job_lines(job: Job) -> None:
        score = str(job.score) if job.score is not None else "?"
        lines.append(f"  [{score:>3}] {job.title}")
        lines.append(f"         {job.company} · {job.location}")
        via = f'  (via "{job.search_query}")' if job.search_query else ""
        lines.append(f"         + {_top_matches(job)}{via}")
        funded = _funding_of(job, data)
        if funded is not None:
            lines.append(f"         $ Company funding: {_funding_label(funded)}")
        lines.append(f"         {job.url}")

    lines.append(f"=== Strong Matches ({len(data.strong)}) ===")
    if data.strong:
        for job in data.strong:
            _job_lines(job)
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"=== Other Eligible ({len(data.eligible)}) ===")
    if data.eligible:
        for job in data.eligible:
            _job_lines(job)
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"=== Funding Leads ({len(data.leads)}) ===")
    if data.leads:
        for lead in data.leads:
            tag = "HIGH" if lead.priority == "high" else "norm"
            country = f" ({lead.country})" if lead.country else ""
            lines.append(f"  [{tag}] {lead.company}{country} — {_lead_headline(lead)}")
            if lead.investors:
                lines.append(f"         investors: {', '.join(lead.investors)}")
            if lead.hiring:
                lines.append(f"         hiring: {lead.hiring}")
            if lead.open_jobs:
                lines.append(f"         {lead.open_jobs} eligible job(s) at this company")
            for keys, sentence in evidence_lines(lead.evidence):
                lines.append(f"         > {keys}: {sentence}")
            lines.append(f"         {lead.article_url}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)
