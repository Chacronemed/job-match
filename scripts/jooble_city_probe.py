"""Throwaway diagnostic — does Jooble understand a city + radius better than a region?

The first per-region run returned 0 offers for 9 of the 13 French regions: Jooble's
`location` is a literal match and a posting rarely says "Occitanie". Six real calls, page 1,
the profile keywords, each run through the real pipeline (`run_jobs`, dry run, in-memory DB)
so the numbers are the pipeline's own: totalCount, fetched, rejections by reason, eligible,
strong, and eligible per call. Region vs city shows whether the index understands a city at
all; Lyon with and without a radius shows what the radius adds.

Prints aggregates only, never a title or a company, and never the API key (it is a URL path
segment; the adapter logs a redacted URL and this script keeps httpx quiet).

Run: .venv/Scripts/python scripts/jooble_city_probe.py
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from job_match.adapters.jobs.jooble import JoobleSource  # noqa: E402
from job_match.config.loader import load_aliases, load_profile, load_settings  # noqa: E402
from job_match.persistence.db import Database  # noqa: E402
from job_match.pipelines.jobs import run_jobs  # noqa: E402

MAX_CALLS = 6

# (location, radius_km): None = the place itself, as the index matches it.
VARIANTS = (
    ("Auvergne-Rhône-Alpes", None),   # region, as the daily run queries it today
    ("Lyon", None),
    ("Lyon", 50),
    ("Occitanie", None),              # region
    ("Toulouse", 50),
    ("Nantes", 50),
)


def main() -> None:
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        print("JOOBLE_API_KEY is not set (env or .env) — nothing probed", file=sys.stderr)
        raise SystemExit(1)
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = ROOT / "config"
    profile = load_profile(cfg / "profile.yaml")
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")

    calls = 0
    city_eligible = city_calls = 0
    print(f"{'location':22} {'radius':>6} {'total':>6} {'fetched':>7} {'LOC':>4} {'elig':>5} "
          f"{'strong':>6}  rejected-by-reason")
    for location, radius in VARIANTS[:MAX_CALLS]:
        source = JoobleSource(
            profile, api_key=key, regions=[location], radius_km=radius, max_calls_per_run=1
        )
        with Database(path=":memory:") as db:
            summary = run_jobs(source, profile, settings, db, aliases, dry_run=True)
        calls += source.api_calls_count
        stat = source.query_stats[0] if source.query_stats else None
        total = stat.available if stat and stat.available is not None else "?"
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(summary.rejected_by_reason.items()))
        print(f"{location:22} {radius if radius is not None else '-':>6} {total!s:>6} "
              f"{summary.fetched:>7} {summary.rejected_by_reason.get('LOCATION', 0):>4} "
              f"{summary.eligible:>5} {summary.strong:>6}  {reasons or '-'}")
        if radius is not None:
            city_eligible += summary.eligible
            city_calls += source.api_calls_count

    print()
    if city_calls:
        print(f"city + radius: {city_eligible} eligible over {city_calls} calls "
              f"= {city_eligible / city_calls:.1f} eligible per call")
    print(f"calls used: {calls}/{MAX_CALLS}")


if __name__ == "__main__":
    main()
