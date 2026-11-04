"""Write the Latin subsets of the PDF fonts (Inter Regular + Bold, TTF) the CV renderer embeds.
Run once; the two `*-latin.ttf` are committed under worker/fonts/ next to their sources.

The renderer embeds them whole (`subset: false`): pdf-lib's run-time subsetting re-encodes the
font on every save, the costliest step of a download (ADR 0019 amendment). A ~400 KB font
becomes ~40 KB: the French and English text of a CV (Basic Latin, Latin-1, Latin Extended-A
for names, the typographic punctuation, €, arrows), no hinting (a PDF does not use it), the
kerning kept and every substitution dropped (see `build`). `render.js` folds any
other character to one of these before it measures (`pdfText`): no tofu, the text stays
extractable for an ATS.
Run (fontTools, once: `.venv\\Scripts\\pip install fonttools`):
  .venv\\Scripts\\python scripts/build_pdf_fonts.py
"""
from pathlib import Path

from fontTools import subset

FONTS = Path(__file__).parent.parent / "worker" / "fonts"
SOURCES = ("Inter-Regular.ttf", "Inter-Bold.ttf")
# Keep in step with SUPPORTED_RANGES in worker/src/render.js (a render test checks both ways).
UNICODES = [
    *range(0x20, 0x7F),  # Basic Latin
    *range(0xA0, 0x100),  # Latin-1: é è ê à ç ô û ï « » ° · nbsp
    *range(0x100, 0x180),  # Latin Extended-A: œ Œ and the names (ł ő ș ...)
    0x2009, 0x202F,  # thin and narrow no-break spaces (French « », 12 h)
    *range(0x2010, 0x2016),  # hyphens and dashes ‐ ‑ ‒ – — ―
    *range(0x2018, 0x201F),  # ‘ ’ ‚ ‛ “ ” „ ‟
    0x2020, 0x2021, 0x2022, 0x2026, 0x2030, 0x2032, 0x2033, 0x2039, 0x203A,  # † ‡ • … ‰ ′ ″ ‹ ›
    0x20AC, 0x2122, 0x2212,  # € ™ −
    *range(0x2190, 0x2194),  # ← ↑ → ↓
]


def build(source: Path, out: Path) -> None:
    options = subset.Options()
    options.hinting = False
    options.desubroutinize = True
    options.name_IDs = ["*"]  # keep the OFL notice in the font itself
    options.notdef_outline = True
    # Kerning only: a substitution (calt, liga, case...) draws a glyph without a code point of
    # its own, and an embedded whole font then maps it to the wrong letter (« +33 » read back
    # as « Ň33 »). No ligature, no alternate: every glyph is one character, as an ATS expects.
    options.layout_features = ["kern"]
    options.drop_tables += ["GSUB"]
    font = subset.load_font(str(source), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    subset.save_font(font, str(out), options)


def main() -> None:
    for name in SOURCES:
        out = FONTS / name.replace(".ttf", "-latin.ttf")
        build(FONTS / name, out)
        print(f"{out.name}: {(FONTS / name).stat().st_size} -> {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
