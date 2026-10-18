"""Throwaway diagnostic — which Jooble query returns French jobs?

The digest filled up with US offers: `location=""` on jooble.org is the whole world, not
France. Four real calls, page 1, same keywords as the adapter, two hosts x two locations.
Per variant: totalCount, how many offers came back, and how many of their locations the
gate reads as French / abroad / unreadable (`french_location`, the same code the pipeline
runs). The distinct location strings are printed too — they are places, not people — so
a format the gate cannot read is visible.

Never prints the API key (it is a URL path segment, so no URL is printed either).

Run: .venv/Scripts/python scripts/jooble_location_probe.py
"""
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import httpx  # noqa: E402

from job_match.config.loader import load_profile  # noqa: E402
from job_match.normalization.location import french_location  # noqa: E402

MAX_CALLS = 4
RESULTS_PER_PAGE = 50

VARIANTS = (
    ("https://jooble.org/api", ""),
    ("https://jooble.org/api", "France"),
    ("https://fr.jooble.org/api", ""),
    ("https://fr.jooble.org/api", "France"),
)


def _probe(client: httpx.Client, key: str, api_root: str, location: str,
           keywords: str) -> None:
    label = f"{api_root.removeprefix('https://').removesuffix('/api'):<16} location={location!r:9}"
    try:
        resp = client.post(
            f"{api_root}/{key}",
            json={"keywords": keywords, "location": location, "page": "1",
                  "ResultOnPage": str(RESULTS_PER_PAGE)},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        print(f"[{label}] request failed: {type(exc).__name__}")
        return
    if resp.status_code != 200:
        print(f"[{label}] HTTP {resp.status_code} (body not printed)")
        return

    body = resp.json() or {}
    jobs = [j for j in (body.get("jobs") or []) if isinstance(j, dict) and j.get("id")]
    verdicts = Counter()
    places: Counter[str] = Counter()
    for job in jobs:
        loc = str(job.get("location") or "")
        verdict = french_location(loc)
        verdicts["french" if verdict else "abroad" if verdict is False else "unknown"] += 1
        places[loc] += 1
    n = len(jobs)
    share = round(100 * verdicts["french"] / n) if n else 0
    print(f"[{label}] totalCount={body.get('totalCount')!s:>8} returned={n:3d} "
          f"french={verdicts['french']:3d} ({share}%) abroad={verdicts['abroad']:3d} "
          f"unknown={verdicts['unknown']:3d}")
    for loc, count in places.most_common():
        print(f"      {count:3d}  {loc!r}  -> {french_location(loc)}")


def main() -> None:
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        print("JOOBLE_API_KEY is not set (env or .env) — nothing probed", file=sys.stderr)
        raise SystemExit(1)
    keywords = " ".join(load_profile(ROOT / "config" / "profile.yaml").ft_search.keywords)

    with httpx.Client() as client:
        for api_root, location in VARIANTS[:MAX_CALLS]:
            _probe(client, key, api_root, location, keywords)
    print(f"\ncalls used: {min(len(VARIANTS), MAX_CALLS)}/{MAX_CALLS}")


if __name__ == "__main__":
    main()
