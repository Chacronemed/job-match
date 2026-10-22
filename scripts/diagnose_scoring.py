"""How well the score tells offers apart, on a database (M24, docs/diagnostics/m24-scoring.md).

Aggregates only, safe to paste: score bands and quartiles per tier, the most frequent
normalised titles among the kept offers, the share per title family (scoring/title.py), the
volume above the digest and strong thresholds, and the mean score of the offers I kept vs the
ones I dropped (the D1 mirror: `job-match tracking import`). No company, URL, note or job key
is printed.

Run on a copy, never on the production file:
    JOB_MATCH_DATA_DIR=<dir with jobs.sqlite> .venv/Scripts/python scripts/diagnose_scoring.py
"""
from __future__ import annotations

import collections
import os
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from job_match.config.loader import load_settings  # noqa: E402
from job_match.normalization.title import normalize_title  # noqa: E402
from job_match.scoring.title import title_family  # noqa: E402

KEPT = ("ELIGIBLE", "STRETCH")
TOP_TITLES = 30


def _bands(scores: list[int]) -> str:
    counts = collections.Counter((s // 5) * 5 for s in scores)
    return " ".join(f"{b}:{counts[b]}" for b in sorted(counts))


def _quartiles(scores: list[int]) -> str:
    if len(scores) < 2:
        return "n/a"
    q1, q2, q3 = statistics.quantiles(scores, n=4)
    return (f"min {min(scores)}  Q1 {q1:g}  median {q2:g}  Q3 {q3:g}  max {max(scores)}"
            f"  IQR {q3 - q1:g}")


def main() -> None:
    data_dir = Path(os.environ.get("JOB_MATCH_DATA_DIR", ROOT / "data"))
    config_dir = Path(os.environ.get("JOB_MATCH_CONFIG_DIR", ROOT / "config"))
    settings = load_settings(config_dir / "settings.yaml")
    conn = sqlite3.connect(f"file:{(data_dir / 'jobs.sqlite').as_posix()}?mode=ro", uri=True)

    tiers = dict(conn.execute("SELECT eligibility, COUNT(*) FROM jobs GROUP BY 1").fetchall())
    print("Tiers:", ", ".join(f"{k} {v}" for k, v in sorted(tiers.items())))
    reasons = collections.Counter()
    for (r,) in conn.execute("SELECT rejection_reason FROM jobs WHERE eligibility = 'REJECTED'"):
        for part in (r or "").split(", "):
            reasons[part or "?"] += 1
    print("Rejection reasons (a job can fail several):",
          ", ".join(f"{k} {v}" for k, v in reasons.most_common()))

    kept = conn.execute(
        "SELECT title, score, eligibility FROM jobs"
        " WHERE eligibility IN (?, ?) AND score IS NOT NULL", KEPT
    ).fetchall()
    for tier in KEPT:
        scores = [s for _, s, e in kept if e == tier]
        print(f"\n{tier} (n={len(scores)}): {_quartiles(scores)}")
        print(f"  bands {_bands(scores)}")

    scores = [s for _, s, _ in kept]
    strong, digest = settings.strong_threshold, settings.digest.min_score
    print(f"\nThresholds: digest {digest}, strong {strong}")
    print(f"  kept offers >= digest: {sum(s >= digest for s in scores)} of {len(scores)}")
    print(f"  kept offers >= strong: {sum(s >= strong for s in scores)}")
    for q in (50, 67, 80, 85, 90):
        if len(scores) > 1:
            print(f"  p{q} of kept scores: {statistics.quantiles(scores, n=100)[q - 1]:g}")

    by_title: dict[str, list[int]] = collections.defaultdict(list)
    for title, score, _ in kept:
        by_title[normalize_title(title or "")].append(score)
    print(f"\nTop {TOP_TITLES} normalised titles among kept offers ({len(by_title)} distinct):")
    for title, ss in sorted(by_title.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_TITLES]:
        print(f"  {len(ss):4d}  mean {sum(ss) / len(ss):5.1f}  {title}")

    if settings.title_relevance.enabled:
        tr = settings.title_relevance
        fam = collections.Counter(title_family(t or "", tr).family for t, _, _ in kept)
        total = sum(fam.values()) or 1
        print("\nTitle families among kept offers:", ", ".join(
            f"{k} {v} ({100 * v / total:.0f} %)" for k, v in fam.most_common()))
        every = conn.execute("SELECT title FROM jobs").fetchall()
        off = sum(1 for (t,) in every if title_family(t or "", tr).family == "off_domain")
        print(f"Off-domain titles in the whole table: {off} of {len(every)}")

    # My verdicts (mirror tables), joined on the tracking key: aggregates only.
    signal = conn.execute(
        """SELECT COALESCE(d.label, a.status) AS verdict, j.score, j.eligibility
           FROM jobs j
           LEFT JOIN decisions d ON d.job_key = j.source_id || ':' || j.source_job_id
           LEFT JOIN applications a ON a.job_key = j.source_id || ':' || j.source_job_id
           WHERE d.label IS NOT NULL OR a.status IS NOT NULL"""
    ).fetchall()
    if signal:
        print("\nMy verdicts vs the current score (an offer with a decision counts by its label):")
        groups: dict[str, list[tuple[int | None, str]]] = collections.defaultdict(list)
        for verdict, score, elig in signal:
            groups[verdict].append((score, elig))
        for verdict, rows in sorted(groups.items()):
            vals = [s for s, _ in rows if s is not None]
            rejected = sum(1 for _, e in rows if e == "REJECTED")
            mean = f"{sum(vals) / len(vals):.1f}" if vals else "—"
            print(f"  {verdict:12} n={len(rows):3d}  mean score {mean:>5}  now rejected {rejected}")


if __name__ == "__main__":
    main()
