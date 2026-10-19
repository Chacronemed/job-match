r"""
Throwaway diagnostic script — what does the France Travail offer-detail endpoint answer
for offers we stored a while ago? Prints the HTTP status per offer id, never a title, never
the token. Measured 2026-10-19 on 9 offers: a closed offer answers 204 No Content (empty
body), an open one 200 with the full offer and no status field. 6 of the 9 oldest visible
offers were already gone. At most 10 detail calls.
Run: .venv\Scripts\python scripts/ft_closed_probe.py
"""

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from job_match.adapters.jobs.france_travail import DETAIL_URL, FranceTravailSource  # noqa: E402
from job_match.config.loader import load_profile  # noqa: E402

DB = ROOT / "data" / "jobs.sqlite"
MAX_CALLS = 10
VISIBLE = (
    "FROM jobs j WHERE j.source_id = 'france_travail'"
    " AND j.eligibility IN ('ELIGIBLE', 'STRETCH')"
    " AND NOT EXISTS (SELECT 1 FROM job_duplicates d WHERE d.duplicate_job_id = j.id)"
)


def main() -> None:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    oldest = conn.execute(
        f"SELECT j.source_job_id, j.collected_at, j.published_at {VISIBLE}"
        " ORDER BY j.collected_at ASC LIMIT ?", (MAX_CALLS - 2,)
    ).fetchall()
    newest = conn.execute(
        f"SELECT j.source_job_id, j.collected_at, j.published_at {VISIBLE}"
        " ORDER BY j.collected_at DESC LIMIT 2"
    ).fetchall()

    source = FranceTravailSource(load_profile(ROOT / "config" / "profile.yaml"))
    print(f"endpoint: {DETAIL_URL}\n")
    counts: dict[str, int] = {}
    for sid, collected, published in oldest + newest:
        t0 = time.monotonic()
        status = source.check_offer(sid)
        counts[status] = counts.get(status, 0) + 1
        print(
            f"{sid:<10} collected={collected[:10]} published={(published or '-')[:10]}"
            f" -> {status} ({time.monotonic() - t0:.2f}s)"
        )
    print(f"\ncalls: {source.api_calls_count}  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
