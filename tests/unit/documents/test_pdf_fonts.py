"""The PDF fonts (worker/fonts/*-latin.ttf, ADR 0019 amendment) cover the text they print.

Always: the typography a French or English CV uses, and the committed subsets are exactly what
`scripts/build_pdf_fonts.py` writes today (fontTools is in the dev extra). Locally, when the
private files are there (gitignored, so CI skips): every character of the master CV, the
contact sheet and the companies and titles of the offers in data/jobs.sqlite. A failure names
the characters and their code points, never the text around them: add them to `UNICODES` in
the build script and to `SUPPORTED_RANGES` in worker/src/render.js, then rebuild.
"""
import importlib.util
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
FONTS = ROOT / "worker" / "fonts"
SUBSETS = ("Inter-Regular-latin.ttf", "Inter-Bold-latin.ttf")
TYPOGRAPHY = "’‘“”«»–—…€œŒæçéèêëàâäîïôöùûüÿÉÈÀÇ°•·×"
MASTER = ROOT / "private" / "cv_master.yaml"
CONTACT = ROOT / "private" / "contact.yaml"
JOBS_DB = ROOT / "data" / "jobs.sqlite"

ttLib = pytest.importorskip("fontTools.ttLib", reason="fontTools: pip install -e .[dev]")


def _covered():
    """The code points both subsets map (bold and regular print the same text)."""
    return set.intersection(*(set(ttLib.TTFont(FONTS / n).getBestCmap()) for n in SUBSETS))


def _missing(texts):
    return Counter(ch for t in texts for ch in t if ch not in "\n\r\t" and ord(ch) not in COVERED)


def _describe(missing):
    return ", ".join(f"{c!r} U+{ord(c):04X} {unicodedata.name(c, '?')} ×{n}"
                     for c, n in missing.most_common())


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


COVERED = _covered()


def test_the_typography_of_a_french_or_english_cv_is_covered():
    missing = _missing([TYPOGRAPHY])
    assert not missing, _describe(missing)


def test_the_committed_subsets_are_what_the_build_script_writes(tmp_path):
    spec = importlib.util.spec_from_file_location("build_pdf_fonts",
                                                  ROOT / "scripts" / "build_pdf_fonts.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    for source, subset in zip(build.SOURCES, SUBSETS, strict=True):
        out = tmp_path / subset
        build.build(FONTS / source, out)
        assert out.read_bytes() == (FONTS / subset).read_bytes(), (
            f"{subset} is stale: run .venv\\Scripts\\python scripts/build_pdf_fonts.py")


@pytest.mark.parametrize("path", [MASTER, CONTACT], ids=["master", "contact"])
def test_every_character_of_my_master_and_contact_is_covered(path):
    if not path.is_file():
        pytest.skip(f"{path.name} is private (gitignored): checked locally only")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = _missing(list(_strings(data)))
    assert not missing, f"{path.name}: {_describe(missing)}"


def test_every_character_of_the_offers_companies_and_titles_is_covered():
    if not JOBS_DB.is_file():
        pytest.skip("data/jobs.sqlite is private: checked locally only")
    db = sqlite3.connect(f"file:{JOBS_DB.as_posix()}?mode=ro", uri=True)
    try:
        texts = [r[0] for r in db.execute(
            "SELECT DISTINCT company FROM jobs WHERE company IS NOT NULL "
            "UNION SELECT DISTINCT title FROM jobs WHERE title IS NOT NULL")]
    finally:
        db.close()
    missing = _missing(texts)
    assert not missing, f"jobs (company, title): {_describe(missing)}"
