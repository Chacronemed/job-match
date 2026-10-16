"""Throwaway diagnostic — how does Jooble treat multiple keywords?

AND, OR, or ranked relevance? That decides whether the adapter can collapse the 7 profile
keywords into one call per region: its budget is 15 calls and 7 keywords x 7 regions is 49,
so today Jooble never gets past the second keyword.

Four real calls, page 1, one region. Prints counts and id-set overlaps only: no titles, no
companies, and never the API key (it is a URL path segment, so the URL is never logged).

Run: .venv/Scripts/python scripts/jooble_probe.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import httpx  # noqa: E402

from job_match.config.loader import load_settings  # noqa: E402

API_ROOT = "https://jooble.org/api"
MAX_CALLS = 6          # hard ceiling: the free plan allows a few hundred calls a day
RESULTS_PER_PAGE = 50  # same page size the adapter asks for

PROBES = (
    ("a", "devops"),
    ("b", "kubernetes"),
    ("c", "devops kubernetes sre"),
    ("d", "devops OR sre OR kubernetes"),
)


def _region() -> str:
    """First configured region, so the probe measures what the adapter would query."""
    regions = load_settings(ROOT / "config" / "settings.yaml").sources.regions
    return regions[0] if regions else chr(206) + "le-de-France"


def _probe(client: httpx.Client, key: str, label: str, keywords: str,
           region: str, calls: list[int]) -> set[str]:
    if calls[0] >= MAX_CALLS:
        print(f"call budget {MAX_CALLS} exhausted, stopping")
        raise SystemExit(1)

    resp = client.post(
        f"{API_ROOT}/{key}",
        json={
            "keywords": keywords,
            "location": region,
            "page": "1",
            "ResultOnPage": str(RESULTS_PER_PAGE),
        },
        timeout=20,
    )
    calls[0] += 1

    if resp.status_code != 200:
        print(f"[{label}] HTTP {resp.status_code} — aborting (body not printed)")
        raise SystemExit(1)

    body = resp.json() or {}
    jobs = [j for j in (body.get("jobs") or []) if isinstance(j, dict) and j.get("id")]
    ids = {str(j["id"]) for j in jobs}
    print(f"[{label}] keywords={keywords!r:32} "
          f"totalCount={body.get('totalCount')!s:>8}  returned={len(ids)}")
    return ids


def main() -> None:
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        print("JOOBLE_API_KEY is not set (env or .env) — nothing probed", file=sys.stderr)
        raise SystemExit(1)

    region = _region()
    calls = [0]
    ids: dict[str, set[str]] = {}

    print(f"region={region!r}  page=1  per_page={RESULTS_PER_PAGE}")
    with httpx.Client() as client:
        for label, keywords in PROBES:
            ids[label] = _probe(client, key, label, keywords, region, calls)

    print()
    print("page-1 id overlap:")
    for combined in ("c", "d"):
        for single in ("a", "b"):
            shared = len(ids[single] & ids[combined])
            total = len(ids[single])
            pct = round(100 * shared / total) if total else 0
            print(f"  {single} ids also in {combined}: {shared}/{total} ({pct}%)")
        union = ids["a"] | ids["b"]
        shared = len(ids[combined] & union)
        total = len(ids[combined])
        pct = round(100 * shared / total) if total else 0
        print(f"  {combined} ids that are in a or b: {shared}/{total} ({pct}%)")
    print()
    print(f"calls used: {calls[0]}/{MAX_CALLS}")


if __name__ == "__main__":
    main()
