"""DigestData model and HTML/plain-text renderers."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from job_match.domain.models import Job


@dataclass(frozen=True, slots=True)
class DigestData:
    strong: tuple[Job, ...]
    eligible: tuple[Job, ...]  # non-strong eligible, unnotified
    run_stats: dict[str, int] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.now)


def _e(text: str | None) -> str:
    """HTML-escape external content (titles, companies, locations from APIs)."""
    return html.escape(text or "", quote=True)


def _top_matches(job: Job, n: int = 3) -> str:
    if job.scoring_breakdown and job.scoring_breakdown.positive_matches:
        return ", ".join(job.scoring_breakdown.positive_matches[:n])
    return "—"


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
        ".stats{background:#f9fafb;padding:12px 16px;border-radius:6px;"
        "font-size:.85rem;line-height:1.8}"
        ".empty{color:#888;font-style:italic}"
        "</style>"
        "</head><body>"
    )

    ts = data.generated_at.strftime("%Y-%m-%d %H:%M")
    total = len(data.strong) + len(data.eligible)
    parts.append(
        f"<h1>Job Match Digest</h1>"
        f"<p class='meta'>Generated {_e(ts)} — "
        f"{total} unnotified job{'s' if total != 1 else ''} "
        f"({len(data.strong)} strong)</p>"
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
        return (
            f"<div class='job'>"
            f"<div class='job-title'>"
            f"<a href='{_e(job.url)}'>{_e(job.title)}</a>"
            f"</div>"
            f"<div class='job-meta'>"
            f"<span class='{score_cls}'>{score_str}</span>"
            f"{_e(job.company)} · {_e(loc)} · {contract}"
            f"</div>"
            f"<div class='matches'>+ {_e(matches)}</div>"
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

    parts.append("</body></html>")
    return "".join(parts)


def render_text(data: DigestData) -> str:
    lines: list[str] = []
    ts = data.generated_at.strftime("%Y-%m-%d %H:%M")
    total = len(data.strong) + len(data.eligible)
    lines.append(f"Job Match Digest — {ts}")
    lines.append(f"{total} unnotified jobs ({len(data.strong)} strong)")
    lines.append("")

    if data.run_stats:
        lines.append("=== Last Run ===")
        for k, v in data.run_stats.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    lines.append(f"=== Strong Matches ({len(data.strong)}) ===")
    if data.strong:
        for job in data.strong:
            score = str(job.score) if job.score is not None else "?"
            matches = _top_matches(job)
            lines.append(f"  [{score:>3}] {job.title}")
            lines.append(f"         {job.company} · {job.location}")
            lines.append(f"         + {matches}")
            lines.append(f"         {job.url}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"=== Other Eligible ({len(data.eligible)}) ===")
    if data.eligible:
        for job in data.eligible:
            score = str(job.score) if job.score is not None else "?"
            matches = _top_matches(job)
            lines.append(f"  [{score:>3}] {job.title}")
            lines.append(f"         {job.company} · {job.location}")
            lines.append(f"         + {matches}")
            lines.append(f"         {job.url}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)
