"""Compare my verdicts on the dashboard with the scores the jobs had when I gave them.

Pure functions over `DecidedJob` rows (the mirrored D1 `decisions`, latest per job, joined
to the stored breakdown). The report only *suggests* threshold and weight changes: nothing
here writes to `config/`. Below `MIN_DECISIONS` it makes no suggestion at all, because a
handful of verdicts says more about the week than about the rules.
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from job_match.tracking.constants import LABELS

MIN_DECISIONS = 10
MIN_SUPPORT = 3  # a rule must be on at least this many off_topic jobs to be ranked
LIFT_SUGGEST = 2.0
TARGET_RECALL = 0.5
BUCKET = 10


@dataclass(frozen=True, slots=True)
class DecidedJob:
    label: str
    score: int | None  # score_at_decision
    positive: tuple[str, ...] = ()
    negative: tuple[str, ...] = ()
    unlisted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LabelStats:
    label: str
    n: int
    scored: int
    min: int | None
    median: float | None
    max: int | None
    buckets: tuple[int, ...]  # counts per 10-point band, 0-9 … 90-100


@dataclass(frozen=True, slots=True)
class RuleLift:
    rule: str  # "+kubernetes" (preferred) or "-sap" (negative)
    off_topic: int
    good_fit: int
    lift: float


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    total: int
    by_label: dict[str, int]
    strong_threshold: int
    strong_decided: int
    strong_good: int
    labels: tuple[LabelStats, ...]
    off_topic_rules: tuple[RuleLift, ...]
    missing_skills: tuple[tuple[str, int], ...]
    suggestions: tuple[str, ...] = field(default=())

    @property
    def strong_precision(self) -> float | None:
        return self.strong_good / self.strong_decided if self.strong_decided else None


def label_stats(label: str, rows: list[DecidedJob]) -> LabelStats:
    scores = sorted(r.score for r in rows if r.score is not None)
    buckets = [0] * BUCKET
    for s in scores:
        buckets[min(s // BUCKET, BUCKET - 1)] += 1
    return LabelStats(
        label=label,
        n=len(rows),
        scored=len(scores),
        min=scores[0] if scores else None,
        median=statistics.median(scores) if scores else None,
        max=scores[-1] if scores else None,
        buckets=tuple(buckets),
    )


def _rules(row: DecidedJob) -> set[str]:
    return {f"+{s}" for s in row.positive} | {f"-{s}" for s in row.negative}


def rule_lifts(rows: list[DecidedJob]) -> list[RuleLift]:
    """Rules more frequent on off_topic than on good_fit jobs, most suspicious first.

    Lift = share of off_topic jobs carrying the rule / share of good_fit jobs carrying it,
    both smoothed (+0.5 / +1) so a rule never seen on a good_fit job does not divide by 0.
    """
    off = [r for r in rows if r.label == "off_topic"]
    good = [r for r in rows if r.label == "good_fit"]
    off_counts = Counter(rule for r in off for rule in _rules(r))
    good_counts = Counter(rule for r in good for rule in _rules(r))
    out = []
    for rule, c_off in off_counts.items():
        if c_off < MIN_SUPPORT:
            continue
        c_good = good_counts.get(rule, 0)
        lift = ((c_off + 0.5) / (len(off) + 1)) / ((c_good + 0.5) / (len(good) + 1))
        out.append(RuleLift(rule=rule, off_topic=c_off, good_fit=c_good, lift=round(lift, 2)))
    return sorted(out, key=lambda r: (-r.lift, -r.off_topic, r.rule))


def best_threshold(rows: list[DecidedJob]) -> int | None:
    """The threshold (multiple of 5) with the best good_fit precision at recall >= 0.5.

    Ties go to the lower threshold: same precision, more jobs shown.
    """
    scored = [r for r in rows if r.score is not None]
    good_total = sum(r.label == "good_fit" for r in scored)
    if not good_total:
        return None
    best: tuple[float, int] | None = None
    for t in range(0, 101, 5):
        picked = [r for r in scored if r.score >= t]
        hits = sum(r.label == "good_fit" for r in picked)
        if not picked or hits / good_total < TARGET_RECALL:
            continue
        precision = hits / len(picked)
        if best is None or precision > best[0]:
            best = (precision, t)
    return best[1] if best else None


def build_report(rows: list[DecidedJob], strong_threshold: int) -> CalibrationReport:
    by_label = {label: sum(r.label == label for r in rows) for label in LABELS}
    strong = [r for r in rows if r.score is not None and r.score >= strong_threshold]
    lifts = rule_lifts(rows)
    missing = Counter(s for r in rows if r.label == "missing_skill" for s in r.unlisted)
    report = CalibrationReport(
        total=len(rows),
        by_label=by_label,
        strong_threshold=strong_threshold,
        strong_decided=len(strong),
        strong_good=sum(r.label == "good_fit" for r in strong),
        labels=tuple(label_stats(label, [r for r in rows if r.label == label])
                     for label in LABELS),
        off_topic_rules=tuple(lifts),
        missing_skills=tuple(missing.most_common(10)),
    )
    if len(rows) < MIN_DECISIONS:
        return report
    return _with_suggestions(report, rows)


def _with_suggestions(report: CalibrationReport, rows: list[DecidedJob]) -> CalibrationReport:
    out: list[str] = []
    t = best_threshold(rows)
    if t is not None and t != report.strong_threshold:
        out.append(
            f"strong_threshold: {report.strong_threshold} -> {t} "
            f"(best good_fit precision with at least {TARGET_RECALL:.0%} of good_fit kept)"
        )
    for r in report.off_topic_rules:
        if r.lift < LIFT_SUGGEST:
            break
        skill = r.rule[1:]
        if r.rule.startswith("+"):
            out.append(
                f"lower the weight of preferred skill '{skill}': on {r.off_topic} off_topic "
                f"vs {r.good_fit} good_fit jobs (lift {r.lift})"
            )
    for skill, n in report.missing_skills:
        if n >= MIN_SUPPORT:
            out.append(
                f"consider adding '{skill}' to the profile (or the dashboard override): "
                f"named on {n} missing_skill jobs"
            )
    return CalibrationReport(**{**_fields(report), "suggestions": tuple(out)})


def _fields(report: CalibrationReport) -> dict:
    return {name: getattr(report, name) for name in report.__dataclass_fields__}


def format_report(report: CalibrationReport) -> str:
    lines = [f"Decisions: {report.total} ("
             + ", ".join(f"{k} {v}" for k, v in report.by_label.items()) + ")"]
    p = report.strong_precision
    lines.append(
        f"Precision of strong (score >= {report.strong_threshold}): "
        + (f"{p:.0%} ({report.strong_good}/{report.strong_decided} good_fit)"
           if p is not None else "no decided strong job")
    )
    lines.append("")
    lines.append("Score at decision, per label (n, min / median / max, 10-point bands 0..90+):")
    for s in report.labels:
        if not s.scored:
            lines.append(f"  {s.label:<13} n={s.n:<3} no score")
            continue
        median = f"{s.median:g}"
        bands = " ".join(str(b) for b in s.buckets)
        lines.append(f"  {s.label:<13} n={s.n:<3} {s.min} / {median} / {s.max}   [{bands}]")
    lines.append("")
    lines.append(f"Rules on off_topic jobs (on >= {MIN_SUPPORT} of them), by lift vs good_fit:")
    if report.off_topic_rules:
        for r in report.off_topic_rules[:10]:
            lines.append(f"  {r.rule:<24} off_topic {r.off_topic:<3} good_fit {r.good_fit:<3}"
                         f" lift {r.lift}")
    else:
        lines.append("  none")
    lines.append("")
    lines.append("Skills named on missing_skill jobs, not in the profile:")
    if report.missing_skills:
        lines.extend(f"  {skill:<24} {n}" for skill, n in report.missing_skills)
    else:
        lines.append("  none")
    lines.append("")
    if report.total < MIN_DECISIONS:
        lines.append(f"Not enough decisions ({report.total} < {MIN_DECISIONS}): no suggestion.")
    elif report.suggestions:
        lines.append("Suggestions (nothing is changed; edit config/ yourself):")
        lines.extend(f"  - {s}" for s in report.suggestions)
    else:
        lines.append("No change suggested.")
    return "\n".join(lines)
