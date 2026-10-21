"""Render the dashboard: one HTML file with the CSS, the JS and the data inlined.

The snapshot is static and the page works from `file://`: no framework, no build step. The
only network call is the tracking API on the same origin (`/api/`, CSP `connect-src 'self'`);
without it the page shows everything but statuses. Nothing from the database is written into
the markup. The snapshot travels as JSON inside a
`<script type="application/json">` block, with every `<` escaped as `\\u003c` (still valid
JSON) so no job title can close the block or open a tag, and the page's own script builds the
DOM with `textContent`. The template (`assets/index.template.html`) holds only our own words.
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

_ASSETS = files("job_match.dashboard").joinpath("assets")
ICONS = ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")
THEME = "#010102"  # DESIGN.md colors.canvas (dark)

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


def render_index(data: dict) -> str:
    template = _ASSETS.joinpath("index.template.html").read_text(encoding="utf-8")
    css = _ASSETS.joinpath("dashboard.css").read_text(encoding="utf-8")
    tracking_js = _ASSETS.joinpath("tracking.js").read_text(encoding="utf-8")
    triage_js = _ASSETS.joinpath("triage.js").read_text(encoding="utf-8")
    js = _ASSETS.joinpath("dashboard.js").read_text(encoding="utf-8")
    # str.replace, not str.format: the CSS and JS are full of braces.
    return (
        template.replace("__CSS__", css)
        .replace("__TRACKING_JS__", tracking_js)
        .replace("__TRIAGE_JS__", triage_js)
        .replace("__JS__", js)
        .replace("__DATA__", embed_json(data))
    )


def write_site(data: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write `index.html`, `data.json`, the web app manifest and its icons into `out_dir`;
    returns the first two paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.webmanifest").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    icons = out_dir / "icons"
    icons.mkdir(exist_ok=True)
    for name in ICONS:
        (icons / name).write_bytes(_ASSETS.joinpath("icons", name).read_bytes())
    index = out_dir / "index.html"
    data_file = out_dir / "data.json"
    index.write_text(render_index(data), encoding="utf-8")
    data_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return index, data_file
