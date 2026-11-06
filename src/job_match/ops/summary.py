"""What the daily run tells the person who did not read the log.

- `append_step_summary` writes Markdown to `$GITHUB_STEP_SUMMARY` (the job summary GitHub
  shows on the run page); outside Actions it does nothing. Aggregates only: the log is public.
- `jobs_markdown`, `digest_markdown`, `failure_markdown`: the blocks the CLI commands append.
- `silent_sources`: the sources that returned nothing in each of the last N jobs runs, the
  condition for the alert email (`job-match ops check-sources`).
- `outage_alerts`: the sources the latest run read as down (ADR 0027) and not yet announced
  today, the condition for the second alert email of the same command.
"""
from __future__ import annotations

import os
from pathlib import Path

from job_match.domain.models import RunRecord, RunSummary
from job_match.pipelines.outage import SourceOutage, banner, outages_of

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
        "| Source | Fetched | Eligible | Duplicates | API calls | Checked | Closed | Suspended |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    down = {o["source"] for o in summary.outages if not o.get("boards")}
    for name in sorted(summary.by_source):
        c = summary.by_source[name]
        flag = " ⚠️ down" if name in down else (" ⚠️ 0" if c.get("fetched", 0) == 0 else "")
        lines.append(
            f"| {name}{flag} | {c.get('fetched', 0)} | {c.get('eligible', 0)} | "
            f"{c.get('duplicates', 0)} | {c.get('calls', 0)} | {c.get('checked', 0)} | "
            f"{c.get('closed', 0)} | {c.get('suspended', 0)} |"
        )
    if not summary.by_source:
        lines.append("| (no source ran) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
    if summary.outages:
        lines.append("")
        for o in summary.outages:
            lines.append(f"⚠️ **{banner(SourceOutage.from_dict(o))}**")
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
        f"{summary.checked} re-checked, {summary.closed} closed"
        + (f", {summary.suspended} closures suspended" if summary.suspended else ""),
    ]
    return "\n".join(lines)


def funding_markdown(summary: RunSummary, elapsed_s: float) -> str:
    return (
        f"## Funding run\n\n{summary.feeds} feeds · {summary.funding_articles} articles · "
        f"{summary.funding_events} events · **{summary.leads} leads** in {elapsed_s:.0f} s"
        + (f" · ⚠️ {summary.errors} error(s)" if summary.errors else "")
    )


def digest_markdown(
    *, jobs: int, strong: int, leads: int, followups: int, sent: bool,
    outages: tuple[str, ...] | list[str] = (),
) -> str:
    """`outages`: the labels of the sources down today (ADR 0027): an empty digest then says
    so instead of « 0 jobs »."""
    state = "**Emailed**" if sent else "Nothing to send"
    text = f"## Digest\n\n{state}: {jobs} jobs ({strong} strong), {leads} leads, "
    text += f"{followups} follow-ups due"
    if outages:
        names = ", ".join(outages)
        text += f"\n\n⚠️ **{names} indisponible aujourd'hui** : clôtures suspendues, "
        text += "aucune nouvelle offre de cette source n'était attendue."
    return text


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


def outage_alerts(runs: list[RunRecord]) -> list[SourceOutage]:
    """The outages of the newest jobs run that no earlier jobs run of the same UTC day already
    carried: one alert per source and per day, however many times the run is replayed.
    `runs` newest first, as `RunRepository.list_recent` returns them."""
    jobs_runs = [r for r in runs if r.pipeline == "jobs"]
    if not jobs_runs:
        return []
    latest = jobs_runs[0]
    today = latest.started_at.date()
    announced = {
        (o.source, o.boards)
        for r in jobs_runs[1:]
        if r.started_at.date() == today
        for o in outages_of(r.summary)
    }
    return [o for o in outages_of(latest.summary) if (o.source, o.boards) not in announced]


def outage_alert_text(outages: list[SourceOutage], day: str) -> tuple[str, str]:
    """Subject and body of the outage alert email (ADR 0027)."""
    names = ", ".join(sorted({o.label for o in outages}))
    subject = f"[job-match] {names} indisponible — clôtures suspendues ({day})"
    lines = [
        f"Le run du {day} a lu une ou plusieurs sources comme indisponibles. Aucune offre de "
        "ces sources n'a été fermée aujourd'hui et aucune candidature n'est passée « Expirée » "
        "à cause d'elles ; les autres sources ont tourné normalement.",
        "",
    ]
    for o in outages:
        lines.append(f"- {banner(o)}")
    lines += [
        "",
        "Si des offres ont été fermées à tort pendant une panne (un run antérieur à la garde, "
        "ou au-delà du seuil), les rouvrir avec :",
        f"  job-match ops reopen --since {day} --source <source>        (dry-run)",
        f"  job-match ops reopen --since {day} --source <source> --apply",
        "",
        "Détail : Actions → Daily run → résumé du job, et la page Exécutions du site.",
    ]
    return subject, "\n".join(lines) + "\n"
