"""Verify that every board in config/ats_boards.yaml still answers with postings.

    .venv\\Scripts\\python scripts/ats_probe.py            # the configured boards
    .venv\\Scripts\\python scripts/ats_probe.py mistral dust   # try these slugs on all 3 ATS

Prints one line per (ATS, slug): HTTP status and the number of postings. Aggregates only:
no title or description is printed. One request per second (Lever asks for Crawl-delay 1).
Run it before adding a slug; a board at 404 is skipped at run time with a warning.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_match.adapters.http import HttpClient  # noqa: E402
from job_match.adapters.jobs.ats import ENDPOINTS, board_url  # noqa: E402
from job_match.config.loader import load_ats_boards  # noqa: E402
from job_match.config.schema import AtsBoard  # noqa: E402


def probe(http: HttpClient, board: AtsBoard) -> tuple[int, int | None]:
    try:
        resp = http.get(board_url(board))
    except Exception as exc:  # network: report, do not stop the table
        print(f"{board.ats:<10} {board.slug:<24} ERR  {type(exc).__name__}")
        return 0, None
    count: int | None = None
    if resp.status_code == 200:
        try:
            body = resp.json()
            jobs = body if isinstance(body, list) else body.get("jobs", [])
            count = len(jobs)
        except ValueError:
            count = None
    print(f"{board.ats:<10} {board.slug:<24} {resp.status_code}  "
          f"{count if count is not None else '-'}")
    return resp.status_code, count


def main(argv: list[str]) -> int:
    if argv:
        boards = [AtsBoard(company=slug, ats=ats, slug=slug) for slug in argv for ats in ENDPOINTS]
    else:
        boards = load_ats_boards(Path("config/ats_boards.yaml"))
    dead = 0
    with HttpClient() as http:
        for board in boards:
            status, count = probe(http, board)
            dead += status != 200 or not count
            time.sleep(1)
    print(f"\n{len(boards) - dead}/{len(boards)} boards answer with postings")
    return 1 if dead and not argv else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
