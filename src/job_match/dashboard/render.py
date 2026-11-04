"""Render the dashboard: one HTML file with the CSS, the JS and the data inlined.

The snapshot is static and the page works from `file://`: no framework, no build step. The
only requests are same-origin: the tracking API (`/api/`, CSP `connect-src 'self'`) and the
self-hosted Inter font (`fonts/`, CSP `font-src 'self'`);
without it the page shows everything but statuses. Nothing from the database is written into
the markup. The snapshot travels as JSON inside a
`<script type="application/json">` block, with every `<` escaped as `\\u003c` (still valid
JSON) so no job title can close the block or open a tag, and the page's own script builds the
DOM with `textContent`. The template (`assets/index.template.html`) holds only our own words.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path

_ASSETS = files("job_match.dashboard").joinpath("assets")
ICONS = ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")
FONTS = ("InterVariable-latin.woff2",)
# The browser renders the CV and the letter itself (ADR 0019): the renderer is the Worker's
# own `render.js`, its three libraries come as their browser (UMD) builds from the Worker's
# npm install (`npm ci --prefix worker`), and the PDF embeds the static Inter TTFs. The
# renderer's bare imports are rewritten to the UMD globals; nothing else changes.
# `pip install .` (the daily run) puts this file in site-packages: the repo checkout is then
# the working directory, as it is for `job-match dashboard --out site`.
_WORKER_CANDIDATES = (Path(__file__).resolve().parents[3] / "worker", Path.cwd() / "worker")
VENDOR = {
    "pdf-lib.min.js": Path("node_modules", "pdf-lib", "dist", "pdf-lib.min.js"),
    "fontkit.umd.min.js": Path("node_modules", "@pdf-lib", "fontkit", "dist", "fontkit.umd.min.js"),
    "fflate.js": Path("node_modules", "fflate", "umd", "index.js"),
}
PDF_FONTS = ("Inter-Regular.ttf", "Inter-Bold.ttf", "LICENSE-Inter.txt")
_IMPORTS = {
    'import fontkit from "@pdf-lib/fontkit";': "const fontkit = globalThis.fontkit;",
    'import { strToU8, zipSync } from "fflate";': "const { strToU8, zipSync } = globalThis.fflate;",
    'import { PDFDocument, rgb } from "pdf-lib";':
        "const { PDFDocument, rgb } = globalThis.PDFLib;",
}
THEME = "#111113"  # DESIGN.md --bg (Radix slate-1, dark)
# Inlined in this order: tokens first, the legacy sheet of the views not yet ported, then the
# system's own rules so they win.
STYLESHEETS = ("tokens.css", "dashboard.css", "app.css")
# Each script needs the ones before it (tracking -> triage; icons -> score -> ui -> palette).
# They are inlined as one `<script>` each, and the CSP allows exactly those eight by their
# sha256 (`script_hash`): no 'unsafe-inline', so a script that reached the markup would not
# run. The renderer and its libraries are same-origin files ('self', ADR 0019).
SCRIPTS = (
    "tracking.js",
    "triage.js",
    "lucide.js",
    "score.js",
    "description.js",
    "ui.js",
    "palette.js",
    "dashboard.js",
)

# Installable from the browser (Chrome, Edge, iOS "Sur l'écran d'accueil"). No service worker:
# nothing may cache data.json or the page, every open shows the latest snapshot.
MANIFEST = {
    "name": "job-match",
    "short_name": "job-match",
    "lang": "fr",
    "start_url": "./#tri",
    "scope": "./",
    "display": "standalone",
    "background_color": THEME,
    "theme_color": THEME,
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ],
}


def embed_json(data: dict) -> str:
    """JSON for a `<script type="application/json">` block.

    `\\u003c` is a legal JSON escape for `<`, so `</script>`, `<!--` and `<img` inside a title
    can neither end the block nor start markup, and `JSON.parse` reads them back unchanged.
    """
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _asset(name: str) -> str:
    return _ASSETS.joinpath(name).read_text(encoding="utf-8")


def browser_renderer(source: str) -> str:
    """`render.js` for the page: each bare import becomes a read of the UMD global."""
    for line, replacement in _IMPORTS.items():
        if line not in source:
            raise ValueError(f"render.js: expected import missing: {line}")
        source = source.replace(line, replacement, 1)
    if re.search(r"^import\b", source, re.M):
        raise ValueError("render.js: an import the page cannot resolve remains")
    return source


def worker_dir() -> Path:
    """The repo's `worker/` (its `src/render.js` is the renderer the page ships)."""
    for candidate in _WORKER_CANDIDATES:
        if (candidate / "src" / "render.js").is_file():
            return candidate
    raise FileNotFoundError("worker/src/render.js not found: run from the repo root")


def write_renderer(out_dir: Path, worker: Path | None = None) -> None:
    """`assets/render.js`, `vendor/` and the PDF fonts: what the downloads need (ADR 0019)."""
    worker = worker or worker_dir()
    missing = [str(worker / p) for p in VENDOR.values() if not (worker / p).is_file()]
    if missing:
        raise FileNotFoundError(
            "the Worker's npm dependencies are missing (run `npm ci --prefix worker`): "
            + ", ".join(missing)
        )
    assets = out_dir / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "render.js").write_text(
        browser_renderer((worker / "src" / "render.js").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    vendor = out_dir / "vendor"
    vendor.mkdir(exist_ok=True)
    for name, src in VENDOR.items():
        (vendor / name).write_bytes((worker / src).read_bytes())
    fonts = out_dir / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in PDF_FONTS:
        (fonts / name).write_bytes((worker / "fonts" / name).read_bytes())


def script_hash(body: str) -> str:
    """The CSP source for one inline script: sha256 of its exact text between the tags."""
    digest = hashlib.sha256(body.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def render_index(data: dict) -> str:
    # str.replace, not str.format: the CSS and JS are full of braces. The data goes last so no
    # placeholder text inside it is ever replaced.
    html = _asset("index.template.html").replace(
        "__CSS__", "\n".join(_asset(name) for name in STYLESHEETS)
    )
    bodies = ["\n" + _asset(name) + "\n" for name in SCRIPTS]
    html = html.replace("__SCRIPT_HASHES__", " ".join(script_hash(b) for b in bodies))
    html = html.replace("__SCRIPTS__", "\n".join(f"<script>{b}</script>" for b in bodies))
    return html.replace("__DATA__", embed_json(data))


AI_PROFILE = "ai-profile.json"


def write_site(data: dict, out_dir: Path, ai_profile: dict | None = None) -> tuple[Path, Path]:
    """Write `index.html`, `data.json`, the web app manifest and its icons, the self-hosted font
    (CSP `font-src 'self'`), the document renderer with its libraries and PDF fonts
    (`write_renderer`, ADR 0019) and `LICENSES.md` into `out_dir`; returns the first two paths.

    `ai_profile` (the anonymous skills summary, `ai/summary.py`) goes to `ai-profile.json`,
    a file only the Worker's cron reads (ADR 0016): it is never embedded in the page nor in
    `data.json`. Without it the file is removed, and the cron sends nothing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_file = out_dir / AI_PROFILE
    if ai_profile is not None:
        profile_file.write_text(
            json.dumps(ai_profile, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8"
        )
    elif profile_file.exists():
        profile_file.unlink()
    (out_dir / "manifest.webmanifest").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    icons = out_dir / "icons"
    icons.mkdir(exist_ok=True)
    for name in ICONS:
        (icons / name).write_bytes(_ASSETS.joinpath("icons", name).read_bytes())
    fonts = out_dir / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in FONTS:
        (fonts / name).write_bytes(_ASSETS.joinpath("fonts", name).read_bytes())
    write_renderer(out_dir)
    (out_dir / "LICENSES.md").write_text(_asset("LICENSES.md"), encoding="utf-8")
    index = out_dir / "index.html"
    data_file = out_dir / "data.json"
    index.write_text(render_index(data), encoding="utf-8")
    data_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return index, data_file
