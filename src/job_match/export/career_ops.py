"""`job-match export --format career-ops`: the day's strongest matches as a career-ops inbox.

career-ops (https://github.com/career-ops-hq/career-ops, MIT) evaluates and tailors a CV for
every URL waiting in its inbox, `data/pipeline.md`, or in a lane file named on the command
line (`/career-ops pipeline data/pipeline.job-match.md`). Its format, from `modes/pipeline.md`:

    ## Pending
    - [ ] {url} | {company} | {title} | {location} | note: ... | posted: YYYY-MM-DD

Positional cells first, then labeled segments. The score goes in a `note:` segment because
career-ops has its own 1-5 score and must not read ours as it. Nothing else leaves the
database: no description, no search keyword, no profile value.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from job_match.domain.models import Job

PENDING_HEADING = "## Pending"


@dataclass(frozen=True)
class ExportLine:
    url: str
    company: str
    title: str
    location: str
    score: int
    published_at: datetime | None

    def render(self) -> str:
        cells = [self.url, _cell(self.company), _cell(self.title), _cell(self.location),
                 f"note: job-match {self.score}/100"]
        if self.published_at is not None:
            cells.append(f"posted: {self.published_at.date().isoformat()}")
        return "- [ ] " + " | ".join(cells)


def _cell(value: str) -> str:
    """One pipeline.md cell: the column separator and line breaks cannot appear in it."""
    return " ".join(value.replace("|", "/").split())


def select_top(jobs: Iterable[Job], *, top: int, now: datetime, days: int) -> list[ExportLine]:
    """The `top` best-scored jobs collected in the last `days` days with an http(s) URL.

    `jobs` is `JobRepository.list_canonical_scored`: canonical, eligible or stretch, still
    online, best score first. Duplicates and rejected jobs never reach this function.
    """
    since = now - timedelta(days=days)
    out: list[ExportLine] = []
    for job in jobs:
        if job.score is None or job.collected_at < since:
            continue
        if not job.url.lower().startswith(("http://", "https://")):
            continue
        out.append(ExportLine(job.url, job.company, job.title, job.location, job.score,
                              job.published_at))
        if len(out) >= top:
            break
    return out


def render_inbox(lines: list[ExportLine]) -> str:
    """A complete lane file: a Pending section career-ops can be pointed at."""
    body = "\n".join(line.render() for line in lines)
    return f"{PENDING_HEADING}\n{body}\n" if body else f"{PENDING_HEADING}\n"


def write_inbox(lines: list[ExportLine], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_inbox(lines), encoding="utf-8", newline="\n")
    return len(lines)


def append_to_inbox(lines: list[ExportLine], path: Path) -> int:
    """Add the lines to an existing pipeline.md under its Pending heading, skipping URLs the
    file already has (pending or processed). Returns how many were added."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    new = [line for line in lines if line.url not in existing]
    if not new:
        return 0
    rendered = [line.render() for line in new]
    text = existing.replace("\r\n", "\n").split("\n")
    heading = next((i for i, row in enumerate(text) if row.strip() == PENDING_HEADING), None)
    if heading is None:
        text = [row for row in text if row.strip()] + [PENDING_HEADING] + rendered + [""]
    else:
        # Right after the last "- [" line of the Pending block, before the next heading.
        insert_at = heading + 1
        for i in range(heading + 1, len(text)):
            if text[i].startswith("#"):
                break
            if text[i].startswith("- ["):
                insert_at = i + 1
        text[insert_at:insert_at] = rendered
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(text), encoding="utf-8", newline="\n")
    return len(new)
