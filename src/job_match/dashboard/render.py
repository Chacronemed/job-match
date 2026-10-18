"""Render the dashboard: one HTML file with the CSS, the JS and the data inlined.

The page is static and works from `file://`: no fetch, no framework, no build step. Nothing
from the database is written into the markup. The snapshot travels as JSON inside a
`<script type="application/json">` block, with every `<` escaped as `\\u003c` (still valid
JSON) so no job title can close the block or open a tag, and the page's own script builds the
DOM with `textContent`. The template (`assets/index.template.html`) holds only our own words.
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

_ASSETS = files("job_match.dashboard").joinpath("assets")


def embed_json(data: dict) -> str:
    """JSON for a `<script type="application/json">` block.

    `\\u003c` is a legal JSON escape for `<`, so `</script>`, `<!--` and `<img` inside a title
    can neither end the block nor start markup, and `JSON.parse` reads them back unchanged.
    """
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_index(data: dict) -> str:
    template = _ASSETS.joinpath("index.template.html").read_text(encoding="utf-8")
    css = _ASSETS.joinpath("dashboard.css").read_text(encoding="utf-8")
    js = _ASSETS.joinpath("dashboard.js").read_text(encoding="utf-8")
    # str.replace, not str.format: the CSS and JS are full of braces.
    return (
        template.replace("__CSS__", css)
        .replace("__JS__", js)
        .replace("__DATA__", embed_json(data))
    )


def write_site(data: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write `index.html` and `data.json` into `out_dir`; returns both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    data_file = out_dir / "data.json"
    index.write_text(render_index(data), encoding="utf-8")
    data_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return index, data_file
