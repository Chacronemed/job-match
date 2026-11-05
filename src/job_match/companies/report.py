"""The detection report (Markdown, French like the dashboard) and its YAML record."""
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import yaml

from job_match.companies.detect import CUSTOM, NOT_FOUND, PUBLIC_ATS, VERIFIED, Detection

_ATS_TEXT = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby",
             "smartrecruiters": "SmartRecruiters", "workday": "Workday"}


def _cell(value: object) -> str:
    return str(value if value not in (None, "") else "—").replace("|", "/")


def render_report(results: Sequence[Detection], requests: int | None = None) -> str:
    verified = [r for r in results if r.status == VERIFIED]
    custom = [r for r in results if r.status == CUSTOM]
    missing = [r for r in results if r.status == NOT_FOUND]
    lines = [
        f"# Détection ATS : {len(results)} entreprises",
        "",
        f"- Vérifiées : **{len(verified)}** · custom : **{len(custom)}** · "
        f"introuvables : **{len(missing)}**" + (f" · {requests} requêtes" if requests else ""),
    ]
    guessed = [r for r in verified if r.guess]
    if guessed:
        right = sum(1 for r in guessed if r.guess_confirmed)
        lines.append(f"- `ats_guess` confirmé pour {right}/{len(guessed)} vérifiées")
    lines += ["", "## Vérifiées par ATS", ""]
    for ats in PUBLIC_ATS:
        group = sorted((r for r in verified if r.ats == ats), key=lambda r: r.company.lower())
        if not group:
            continue
        lines += [f"### {_ATS_TEXT[ats]} ({len(group)})", "",
                  "| Entreprise | Identifiant | Offres | Trouvé par | Guess | Note |",
                  "|---|---|---:|---|---|---|"]
        for r in group:
            guess = "✓" if r.guess_confirmed else (r.guess or "—")
            note = "" if r.names_company else "⚠ id sans le nom : à vérifier"
            lines.append(f"| {_cell(r.company)} | `{r.identifier}` | {r.postings} | "
                         f"{r.method} | {_cell(guess)} | {note} |")
        lines.append("")
    lines += [f"## Custom ({len(custom)})", "",
              "| Entreprise | Plateforme | Guess | Essais |", "|---|---|---|---|"]
    for r in sorted(custom, key=lambda r: ((r.platform or "~"), r.company.lower())):
        lines.append(f"| {_cell(r.company)} | {_cell(r.platform or 'site maison')} | "
                     f"{_cell(r.guess)} | {_cell('; '.join(r.notes[:3]))} |")
    lines += ["", f"## Introuvables ({len(missing)})", "",
              "| Entreprise | Guess | Essais |", "|---|---|---|"]
    for r in sorted(missing, key=lambda r: r.company.lower()):
        lines.append(f"| {_cell(r.company)} | {_cell(r.guess)} | {_cell('; '.join(r.notes[:4]))} |")
    return "\n".join(lines) + "\n"


def write_record(
    results: Sequence[Detection], path: Path, checked_at: datetime,
    *, merge_into: Sequence[str] | None = None,
) -> None:
    """One entry per company, for the next step (the Workday / SmartRecruiters boards).

    `merge_into` (a partial run, `--only`): the names of every company of companies.yaml,
    in file order. The existing record keeps its other entries, the re-checked ones are
    replaced, and an entry whose company left companies.yaml is dropped.
    """
    entries = []
    for r in results:
        entry: dict = {"name": r.company, "status": r.status}
        if r.status == VERIFIED:
            entry.update(ats=r.ats, id=r.identifier, postings=r.postings, method=r.method)
            if not r.names_company:
                entry["check"] = "board id does not carry the company name"
        if r.status == CUSTOM and r.platform:
            entry["platform"] = r.platform
        if r.guess:
            entry["ats_guess"] = r.guess
        entries.append(entry)
    if merge_into is not None and path.exists():
        old = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        by_name = {e["name"]: e for e in old.get("companies") or [] if isinstance(e, dict)}
        by_name.update({e["name"]: e for e in entries})
        entries = [by_name[n] for n in merge_into if n in by_name]
    header = (
        "# Written by `job-match companies detect` (M28). Do not edit: re-run the command.\n"
        f"# Checked {checked_at.date().isoformat()} against the public ATS endpoints;\n"
        "# verified = 200 with at least one posting. Read by no source: a verified board\n"
        "# is copied by hand into config/ats_boards.yaml.\n"
    )
    body = yaml.safe_dump({"checked_at": checked_at.isoformat(timespec="seconds"),
                           "companies": entries}, allow_unicode=True, sort_keys=False)
    path.write_text(header + body, encoding="utf-8")


__all__ = ["render_report", "write_record"]
