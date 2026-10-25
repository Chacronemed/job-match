"""The weekly disagreement report (ADR 0016 §8): where the model and the Python score part
ways, next to my own Tri verdicts, turned into a correction prompt for Claude Code.

Pure functions over the mirrored rows (`AiRepository.list_disagreements`). The report only
*asks* for rule changes: nothing here writes to `config/`, and the file it feeds is local,
never committed, never in the CI log (it names offers and skills).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from job_match.config.schema import Settings
from job_match.persistence.repositories import AiRun, Disagreement
from job_match.scoring.title import title_family

TOP = 10
# Published Claude Haiku 5.5 prices (USD per million tokens, prompts up to 100K), checked
# 2026-10-25. Cache reads are cheaper than this, so the line is an upper bound.
HAIKU_IN_PER_M = 0.10
HAIKU_OUT_PER_M = 0.50

# What my verdict says, when I gave one, in the language of the disagreement.
_AGREES_WITH_AI = {
    "gap": {"good_fit": "ai_higher", "off_topic": "ai_lower", "too_senior": "ai_lower",
            "missing_skill": "ai_lower", "location": None},
}


@dataclass(frozen=True, slots=True)
class Ranked:
    row: Disagreement
    gap: int             # |ai - python|
    family: str          # title family, "?" when the offer is gone
    sides_with: str | None  # "ia", "python" or None: whom my Tri verdict agrees with


@dataclass(frozen=True, slots=True)
class AiReport:
    since: date
    today: date
    total: int
    with_decision: int
    by_kind: dict[str, int]
    by_family: dict[str, int]
    sides: dict[str, int]  # ia / python / none
    skills: tuple[tuple[str, int], ...]  # profile skills most often on disagreeing offers
    top: tuple[Ranked, ...]
    usage: dict[str, dict[str, int]]
    estimated_usd: float
    prompt_version: str
    gap_threshold: int
    notes: tuple[str, ...] = field(default=())
    runs: tuple[AiRun, ...] = field(default=())  # the cron passes of the period, newest first


def _sides_with(row: Disagreement) -> str | None:
    """Whom my verdict sides with. A keep (good_fit) backs the higher score, a drop backs
    the lower one; the AI "hors_sujet" on a strong offer is backed by any drop."""
    if row.decision is None:
        return None
    ai_higher = row.ai_score > row.python_score
    if row.kind == "off_topic_strong":
        return "python" if row.decision == "good_fit" else "ia"
    if row.decision == "good_fit":
        return "ia" if ai_higher else "python"
    if row.decision in ("off_topic", "too_senior", "missing_skill"):
        return "python" if ai_higher else "ia"
    return None  # a location verdict says nothing about relevance


def rank(rows: list[Disagreement], settings: Settings) -> list[Ranked]:
    out = []
    for r in rows:
        family = title_family(r.title, settings.title_relevance).family if r.title else "?"
        out.append(Ranked(row=r, gap=abs(r.ai_score - r.python_score), family=family,
                          sides_with=_sides_with(r)))
    # Largest gap first; a strong offer the AI dismisses outranks a plain gap of the same size.
    out.sort(key=lambda x: (x.row.kind != "off_topic_strong", -x.gap, x.row.job_key))
    return out


def build_report(
    rows: list[Disagreement], usage: dict[str, dict[str, int]], settings: Settings,
    since: date, today: date, runs: list[AiRun] | tuple[AiRun, ...] = (),
) -> AiReport:
    ranked = rank(rows, settings)
    skills: Counter[str] = Counter()
    for r in rows:
        skills.update(set(r.positive))
    anthropic = usage.get("anthropic", {})
    usd = (anthropic.get("tokens_in", 0) * HAIKU_IN_PER_M
           + anthropic.get("tokens_out", 0) * HAIKU_OUT_PER_M) / 1_000_000
    sides = Counter(x.sides_with or "none" for x in ranked)
    notes = []
    if not rows:
        notes.append("Aucun désaccord sur la période : rien à corriger.")
    gone = sum(1 for r in rows if r.title is None)
    if gone:
        notes.append(f"{gone} offre(s) ne sont plus en base (fermées ou trop anciennes).")
    bad = [r for r in runs if r.outcome in ("stopped", "failed")]
    if bad:
        codes = ", ".join(
            f"{r.started_at[:16]} {r.outcome}" + (f" HTTP {r.http_status}" if r.http_status else "")
            for r in bad
        )
        notes.append(f"{len(bad)} passage(s) de l'IA en échec : {codes}.")
    return AiReport(
        since=since, today=today, total=len(rows),
        with_decision=sum(1 for r in rows if r.decision is not None),
        by_kind=dict(Counter(r.kind for r in rows)),
        by_family=dict(Counter(x.family for x in ranked)),
        sides={k: sides.get(k, 0) for k in ("ia", "python", "none")},
        skills=tuple(skills.most_common(8)),
        top=tuple(ranked[:TOP]),
        usage=usage, estimated_usd=round(usd, 4),
        prompt_version=settings.ai.prompt_version,
        gap_threshold=settings.ai.disagreement_gap,
        notes=tuple(notes),
        runs=tuple(runs),
    )


def _title(r: Disagreement) -> str:
    if r.title is None:
        return f"(offre {r.job_key}, plus en base)"
    return f"{r.title} — {r.company or 'employeur masqué'}"


def format_report(report: AiReport) -> str:
    """Markdown: the figures, then the prompt to hand to Claude Code, unchanged."""
    lines = [
        f"# Rapport IA — du {report.since.isoformat()} au {report.today.isoformat()}",
        "",
        f"Désaccords : {report.total} ({report.with_decision} avec un verdict Tri)."
        f" Seuil d'écart : {report.gap_threshold} points. Prompt v{report.prompt_version}.",
        "",
    ]
    for note in report.notes:
        lines.append(f"> {note}")
    if report.notes:
        lines.append("")
    if report.by_kind:
        lines.append("Par type : " + ", ".join(
            f"{k} {n}" for k, n in sorted(report.by_kind.items())))
    if report.by_family:
        lines.append("Par famille de titre : " + ", ".join(
            f"{k} {n}" for k, n in sorted(report.by_family.items())))
    s = report.sides
    lines.append(f"Mon verdict donne raison à : l'IA {s['ia']}, Python {s['python']},"
                 f" sans verdict {s['none']}.")
    if report.skills:
        lines.append("Compétences du profil les plus présentes dans ces offres : "
                     + ", ".join(f"{name} ({n})" for name, n in report.skills))
    calls = ", ".join(
        f"{p} {u.get('calls', 0)} appels ({u.get('tokens_in', 0)} tokens entrés,"
        f" {u.get('tokens_out', 0)} sortis)" for p, u in sorted(report.usage.items())
    ) or "aucun appel"
    lines += ["", f"Usage : {calls}. Coût Claude estimé (plafond) : "
              f"{report.estimated_usd:.4f} $.", ""]
    if report.runs:
        passes = ", ".join(
            f"{r.started_at[:16]} {r.outcome} ({r.counters.get('scored', 0)} jugées"
            + (f", HTTP {r.http_status}" if r.http_status else "") + ")"
            for r in report.runs
        )
        lines += [f"Passages : {passes}.", ""]

    lines += ["## Prompt de correction (à relire, puis à donner à Claude Code)", "", "```text",
              "Voici les 10 plus gros désaccords de la semaine entre le score Python"
              " (config/settings.yaml, title_relevance et poids des compétences) et le"
              " verdict IA, avec mon verdict Tri quand j'en ai donné un.", ""]
    for i, x in enumerate(report.top, 1):
        r = x.row
        mine = "pas de verdict Tri" if r.decision is None else f"verdict Tri : {r.decision}"
        who = {"ia": "je suis d'accord avec l'IA",
               "python": "je suis d'accord avec Python"}.get(x.sides_with, mine)
        lines.append(f"{i}. {_title(r)}")
        lines.append(f"   Python {r.python_score} ({r.python_section}) · IA {r.ai_score}"
                     f" ({r.ai_level}) · famille {x.family} · {who}")
        for reason in r.reasons:
            lines.append(f"   - IA : {reason}")
        for flag in r.red_flags:
            lines.append(f"   - IA, vigilance : {flag}")
        if r.positive:
            lines.append("   - compétences comptées : " + ", ".join(r.positive))
    lines += ["",
              "Question : quelles listes ou quels poids de `title_relevance` (core, near, other,"
              " off_domain, off_domain_sectors, core_overrides) ou des compétences du profil"
              " expliquent ces écarts ? Propose un diff de config/settings.yaml avec un test"
              " qui le couvre. Ne l'applique pas : je relis et je décide.",
              "```", ""]
    return "\n".join(lines)
