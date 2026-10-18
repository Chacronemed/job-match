"""Rebuild `src/job_match/normalization/fr_communes.tsv` from the official communes list.

Source: geo.api.gouv.fr (INSEE / COG data), the current communes plus the municipal
arrondissements of Paris, Lyon and Marseille ("Lyon 1er Arrondissement"). The file ships as
package data so the location gate can tell a French town from a foreign one without a
hand-made city list.

The response is untrusted data: only rows with a real department code and a plain name
survive, and only two fields are written (normalized name, department). Prints counts only.

Run: .venv/Scripts/python scripts/build_fr_communes.py
"""
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from job_match.normalization.fr_geo import FRENCH_DEPARTMENTS  # noqa: E402
from job_match.normalization.text import normalize_text  # noqa: E402

API = "https://geo.api.gouv.fr/communes"
OUT = ROOT / "src" / "job_match" / "normalization" / "fr_communes.tsv"
_PLAIN_NAME = re.compile(r"^[a-z0-9 ]+$")


def _fetch(client: httpx.Client, **params: str) -> list[dict]:
    resp = client.get(API, params={"fields": "nom,codeDepartement", "format": "json", **params})
    resp.raise_for_status()
    body = resp.json()
    return [row for row in body if isinstance(row, dict)] if isinstance(body, list) else []


def main() -> None:
    with httpx.Client(timeout=60) as client:
        rows = _fetch(client) + _fetch(client, type="arrondissement-municipal")

    kept: set[tuple[str, str]] = set()
    dropped = 0
    for row in rows:
        name = normalize_text(str(row.get("nom") or ""))
        dept = str(row.get("codeDepartement") or "").upper()
        if dept in FRENCH_DEPARTMENTS and _PLAIN_NAME.match(name):
            kept.add((name, dept))
        else:
            dropped += 1

    lines = [f"{name}\t{dept}" for name, dept in sorted(kept)]
    OUT.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    print(f"fetched={len(rows)} kept={len(kept)} dropped={dropped} "
          f"distinct_names={len({n for n, _ in kept})} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
