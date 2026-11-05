"""`job-match apply` without a key: the numbered list of what I can apply to with a filled form.

The list is the applications « À candidater » (D1, live) whose offer is still open and whose
form `fill_form` supports (Greenhouse, Lever, Ashby, by the offer's URL), oldest kept first,
then by key. The dashboard's « Postuler » button numbers them with the same rule
(`board.js`, `applyList`) and says which number to type. An offer missing from the local jobs
DB cannot be classified: it is left out and counted, the numbers may then differ.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from job_match.apply.forms import detect_ats

ATS_TEXT = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}


@dataclass(frozen=True)
class Choice:
    key: str
    title: str
    company: str
    ats: str


@dataclass(frozen=True)
class Listing:
    choices: list[Choice]
    unknown: int  # kept applications whose offer the local jobs DB does not have


def build(apps: list[dict], offers: dict[str, tuple[str, str, str, bool]]) -> Listing:
    """`apps`: D1 rows {job_key, status, updated_at}; `offers`: key → (url, title, company,
    closed)."""
    kept = sorted((a for a in apps if a.get("status") == "to_apply"),
                  key=lambda a: (str(a.get("updated_at") or ""), str(a.get("job_key"))))
    choices: list[Choice] = []
    unknown = 0
    for app in kept:
        offer = offers.get(str(app.get("job_key")))
        if offer is None:
            unknown += 1
            continue
        url, title, company, closed = offer
        ats = detect_ats(url or "")
        if closed or ats is None:
            continue
        choices.append(Choice(str(app["job_key"]), title or "—", company or "—", ats))
    return Listing(choices, unknown)


def local_offers(db_path: Path, keys: list[str]) -> dict[str, tuple[str, str, str, bool]]:
    """key → (url, title, company, closed) for the keys the jobs DB has."""
    if not keys or not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = {}
        for key in keys:
            source, _, source_id = key.partition(":")
            row = conn.execute(
                "SELECT url, title, company, closed_at FROM jobs"
                " WHERE source_id = ? AND source_job_id = ?",
                (source, source_id),
            ).fetchone()
            if row:
                out[key] = (row[0], row[1], row[2], row[3] is not None)
        return out
    finally:
        conn.close()


def lines(listing: Listing) -> list[str]:
    out = [f"{n:>2}. {c.title} · {c.company} ({ATS_TEXT.get(c.ats, c.ats)})"
           for n, c in enumerate(listing.choices, 1)]
    if listing.unknown:
        out.append(f"({listing.unknown} candidature(s) absente(s) de la base locale :"
                   " les numéros peuvent différer du tableau de bord.)")
    return out


def pick(listing: Listing, answer: str) -> Choice | None:
    text = answer.strip()
    if not text.isdigit():
        return None
    n = int(text)
    return listing.choices[n - 1] if 1 <= n <= len(listing.choices) else None
