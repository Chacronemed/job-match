"""
Diagnostic run — equivalent to job-match run --limit 50 --dry-run but prints:
  1. Every EXPERIENCE rejection: title | min/max yrs | evidence sentence
  2. Every eligible job: title | company | score | top-3 positive matches
  3. Full breakdown for the 3 strong matches
Run: .venv\Scripts\python scripts/diagnose.py
"""

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from job_match.adapters.jobs.france_travail import FranceTravailSource  # noqa: E402
from job_match.config.loader import load_aliases, load_profile, load_settings  # noqa: E402
from job_match.dedup.fingerprint import compute_fingerprint  # noqa: E402
from job_match.domain.models import Eligibility, RejectionReason  # noqa: E402
from job_match.eligibility import gate  # noqa: E402
from job_match.experience import parser as exp_parser  # noqa: E402
from job_match.scoring.engine import ScoringEngine  # noqa: E402
from job_match.scoring.native import NativeRuleScorer  # noqa: E402

LIMIT = 50
CONFIG = ROOT / "config"


def _trunc(s: str | None, n: int = 110) -> str:
    if not s:
        return "(none)"
    s = s.replace("\n", " ").strip()
    return s[:n] + "…" if len(s) > n else s


def main() -> None:
    profile = load_profile(CONFIG / "profile.yaml")
    settings = load_settings(CONFIG / "settings.yaml")
    aliases = load_aliases(CONFIG / "aliases.yaml")
    source = FranceTravailSource(profile, requests_per_second=settings.ft_requests_per_second)
    scoring_engine = ScoringEngine([NativeRuleScorer(aliases)])

    exp_rejections: list[dict] = []
    eligible_jobs: list[dict] = []
    processed = 0

    for raw in source.fetch(since=None):
        if processed >= LIMIT:
            break
        processed += 1

        try:
            job = source.to_job(raw)
        except Exception as exc:
            print(f"  [SKIP] to_job error: {exc}")
            continue

        exp = exp_parser.parse(job.description)
        job = replace(job, experience=exp)
        fp = compute_fingerprint(job)
        job = replace(job, fingerprint=fp)
        elig = gate.evaluate(job, exp, profile, settings)

        if not elig.eligible:
            if RejectionReason.EXPERIENCE in elig.reasons:
                exp_rejections.append({
                    "title": job.title,
                    "min": exp.min_years,
                    "max": exp.max_years,
                    "evidence": exp.evidence,
                })
            continue

        breakdown = scoring_engine.score(job, profile, settings, elig, exp)
        job = replace(
            job,
            eligibility=Eligibility.ELIGIBLE,
            score=breakdown.score,
            scoring_breakdown=breakdown,
        )
        eligible_jobs.append({
            "title": job.title,
            "company": job.company,
            "score": breakdown.score,
            "positive": list(breakdown.positive_matches[:3]),
            "negative": list(breakdown.negative_matches),
            "missing": list(breakdown.missing_preferences),
            "explanations": list(breakdown.explanations),
            "strong": breakdown.score is not None and breakdown.score >= settings.strong_threshold,
        })

    # -------------------------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"EXPERIENCE REJECTIONS  ({len(exp_rejections)} of {processed} processed)")
    print(f"{'='*70}")
    for r in exp_rejections:
        min_s = f"{r['min']}" if r["min"] is not None else "?"
        max_s = f"–{r['max']}" if r["max"] is not None else ""
        print(f"\n  {r['title']}")
        print(f"    required : {min_s}{max_s} yrs")
        print(f"    evidence : {_trunc(r['evidence'])}")

    # -------------------------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"ELIGIBLE JOBS  ({len(eligible_jobs)})")
    print(f"{'='*70}")
    for e in eligible_jobs:
        top3 = ", ".join(e["positive"][:3]) or "(none)"
        print(f"\n  [{e['score']:>3}] {e['title']}")
        print(f"         {e['company']}")
        print(f"         + {top3}")

    # -------------------------------------------------------------------------
    strong = [e for e in eligible_jobs if e["strong"]]
    print(f"\n{'='*70}")
    print(f"STRONG MATCHES  ({len(strong)})  — threshold {settings.strong_threshold}")
    print(f"{'='*70}")
    for e in strong:
        print(f"\n  [{e['score']:>3}] {e['title']}  |  {e['company']}")
        if e["positive"]:
            print(f"         + matched : {', '.join(e['positive'])}")
        if e["negative"]:
            print(f"         - negative: {', '.join(e['negative'])}")
        if e["missing"]:
            print(f"         ? missing : {', '.join(e['missing'])}")
        if e["explanations"]:
            for x in e["explanations"]:
                print(f"           {x}")

    print()


if __name__ == "__main__":
    main()
