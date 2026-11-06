"""What the daily run tells the person who did not read the log.

- `append_step_summary` writes Markdown to `$GITHUB_STEP_SUMMARY` (the job summary GitHub
  shows on the run page); outside Actions it does nothing. Aggregates only: the log is public.
- `jobs_markdown`, `digest_markdown`, `failure_markdown`: the blocks the CLI commands append.
- `silent_sources`: the sources that returned nothing in each of the last N jobs runs, the
  condition for the alert email (`job-match ops check-sources`).
"""
from __future__ import annotations

import os
from pathlib import Path

from job_match.domain.models import RunRecord, RunSummary

DEFAULT_SILENT_DAYS = 3


def append_step_summary(markdown: str) -> bool:
    """Append to the job summary when running in GitHub Actions; False when not."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(markdown.rstrip("\n") + "\n\n")
    return True


def jobs_markdown(summary: RunSummary, elapsed_s: float) -> str:
    """The jobs run as a table: per source, per gate, scored, run time."""
    lines = [
        "## Jobs run",
        "",
        f"**{summary.fetched} fetched** in {elapsed_s:.0f} s · {summary.queries} queries · "
        f"{summary.api_calls} API calls"
        + (f" · ⚠️ {summary.errors} error(s)" if summary.errors else ""),
        "",
        "| Source | Fetched | Eligible | Duplicates | API calls |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in sorted(summary.by_source):
        c = summary.by_source[name]
        flag = " ⚠️ 0" if c.get("fetched", 0) == 0 else ""
        lines.append(
            f"| {name}{flag} | {c.get('fetched', 0)} | {c.get('eligible', 0)} | "
            f"{c.get('duplicates', 0)} | {c.get('calls', 0)} |"
        )
    if not summary.by_source:
        lines.append("| (no source ran) | 0 | 0 | 0 | 0 |")
    lines += [
        "",
        "| Gate | Rejected |",
        "|---|---:|",
    ]
    for reason, n in sorted(summary.rejected_by_reason.items()):
        lines.append(f"| {reason} | {n} |")
    lines.append(f"| **total rejected jobs** | **{summary.rejected_jobs}** |")
    scored = summary.eligible + summary.stretch
    lines += [
        "",
        f"**Scored: {scored}** ({summary.eligible} eligible of which {summary.strong} strong, "
        f"{summary.stretch} stretch) · {summary.duplicates} duplicates · "
        f"{summary.checked} re-checked, {summary.closed} closed",
    ]
    if summary.archived or summary.archived_today:
        n = summary.archived_today
        lines.append(
            f"\n**{n} candidature{'s' if n != 1 else ''} archivée{'s' if n != 1 else ''} "
            f"aujourd'hui** · {summary.archived} archivée"
            f"{'s' if summary.archived != 1 else ''} au total (ADR 0028)"
        )
    return "\n".join(lines)


def funding_markdown(summary: RunSummary, elapsed_s: float) -> str:
    return (
        f"## Funding run\n\n{summary.feeds} feeds · {summary.funding_articles} articles · "
        f"{summary.funding_events} events · **{summary.leads} leads** in {elapsed_s:.0f} s"
        + (f" · ⚠️ {summary.errors} error(s)" if summary.errors else "")
    )


def digest_markdown(*, jobs: int, strong: int, leads: int, followups: int, sent: bool) -> str:
    state = "**Emailed**" if sent else "Nothing to send"
    return (
        f"## Digest\n\n{state}: {jobs} jobs ({strong} strong), {leads} leads, "
        f"{followups} follow-ups due"
    )


def failure_markdown(step: str, exc: BaseException) -> str:
    """One loud line: the step, the exception type, its message. No traceback (public log)."""
    return f"## ❌ {step} failed\n\n`{type(exc).__name__}: {exc}`"


def silent_sources(runs: list[RunRecord], days: int = DEFAULT_SILENT_DAYS) -> list[str]:
    """Sources that fetched 0 in each of the last `days` jobs runs.

    A source absent from a run (not enabled, no key) does not count as silent that day:
    the alert is about a source that ran and found nothing, three times. Fewer runs than
    `days` stored means no alert yet.
    """
    recent = [r for r in runs if r.pipeline == "jobs"][:days]
    if len(recent) < days:
        return []
    names: set[str] = set.intersection(
        *[set((r.summary.get("by_source") or {}).keys()) for r in recent]
    ) if recent else set()
    return sorted(
        name for name in names
        if all((r.summary["by_source"][name] or {}).get("fetched", 0) == 0 for r in recent)
    )


def alert_text(names: list[str], days: int) -> tuple[str, str]:
    """Subject and body of the alert email."""
    subject = f"[job-match] {', '.join(names)}: 0 results for {days} days"
    body = (
        f"The daily run fetched nothing from {', '.join(names)} in each of the last {days} "
        "runs. The source ran (it is enabled and its key is set) and returned an empty list.\n\n"
        "Check the API's status, the query (config/settings.yaml, the profile keywords) and "
        "the run logs under Actions → Daily run.\n"
    )
    return subject, body
