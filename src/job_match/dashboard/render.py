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

import json
from importlib.resources import files
from pathlib import Path

_ASSETS = files("job_match.dashboard").joinpath("assets")
ICONS = ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")
FONTS = ("InterVariable-latin.woff2",)
THEME = "#111113"  # DESIGN.md --bg (Radix slate-1, dark)
# Inlined in this order: tokens first, the legacy sheet of the views not yet ported, then the
# system's own rules so they win.
STYLESHEETS = ("tokens.css", "dashboard.css", "app.css")
# Each script needs the ones before it (tracking -> triage; icons -> score -> ui -> palette).
SCRIPTS = (
    ("__TRACKING_JS__", "tracking.js"),
    ("__TRIAGE_JS__", "triage.js"),
    ("__ICONS_JS__", "lucide.js"),
    ("__SCORE_JS__", "score.js"),
    ("__DESC_JS__", "description.js"),
    ("__UI_JS__", "ui.js"),
    ("__PALETTE_JS__", "palette.js"),
    ("__JS__", "dashboard.js"),
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


def render_index(data: dict) -> str:
    # str.replace, not str.format: the CSS and JS are full of braces. The data goes last so no
    # placeholder text inside it is ever replaced.
    html = _asset("index.template.html").replace(
        "__CSS__", "\n".join(_asset(name) for name in STYLESHEETS)
    )
    for placeholder, name in SCRIPTS:
        html = html.replace(placeholder, _asset(name))
    return html.replace("__DATA__", embed_json(data))


AI_PROFILE = "ai-profile.json"


def write_site(data: dict, out_dir: Path, ai_profile: dict | None = None) -> tuple[Path, Path]:
    """Write `index.html`, `data.json`, the web app manifest and its icons, the self-hosted font
    (CSP `font-src 'self'`) and `LICENSES.md` into `out_dir`; returns the first two paths.

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
    (out_dir / "LICENSES.md").write_text(_asset("LICENSES.md"), encoding="utf-8")
    index = out_dir / "index.html"
    data_file = out_dir / "data.json"
    index.write_text(render_index(data), encoding="utf-8")
    data_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return index, data_file
