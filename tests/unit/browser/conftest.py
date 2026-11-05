"""Browser tests: the rendered page in a real Chromium, the API mocked by Playwright routes.

Skipped on a machine without Playwright or its browser; in CI (`CI` set, the browser installed
by ci.yml) a missing one is a failure, never a silent skip. Once, locally:
`.venv/Scripts/pip install -e .[dev]` then `.venv/Scripts/python -m playwright install chromium`.
"""
import json
import os

import pytest

from job_match.config.schema import Settings
from job_match.dashboard.data import build_dashboard_data
from job_match.dashboard.render import render_index, write_site
from job_match.persistence.db import Database

ORIGIN = "http://jm.test"
# the files the page may fetch after load: the renderer, its libraries, the PDF fonts
STATIC_TYPES = {".js": "text/javascript", ".ttf": "font/ttf", ".json": "application/json",
                ".md": "text/markdown", ".txt": "text/plain"}


def _require(reason):
    if os.environ.get("CI"):
        pytest.fail(reason + " (required in CI, see ci.yml)")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def browser():
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        _require("Playwright is not installed")
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Error as exc:  # the package without its browser
            _require(f"Chromium is not installed: {str(exc).splitlines()[0]}")
        yield b
        b.close()


@pytest.fixture
def dashboard_data(seed_dashboard):
    """`(data, seed)`: the shared seed (tests/unit/conftest.py), default settings."""
    with Database(path=":memory:") as db:
        seed = seed_dashboard(db)
        data = build_dashboard_data(db, Settings(), seed.now)
    return data, seed


@pytest.fixture
def open_dashboard(browser, dashboard_data, tmp_path):
    """`open_dashboard(api, hash, init_script=None)` -> (page, errors).

    Serves the rendered page at ORIGIN, the files `write_site` writes next to it (the document
    renderer, its libraries and the PDF fonts, ADR 0019) and answers `GET /api/applications`
    with `api`; `errors` collects console errors and uncaught exceptions as they happen.
    """
    data, _seed = dashboard_data
    html = render_index(data)
    site = tmp_path / "site"
    write_site(data, site)
    pages = []

    def _open(api, hash_="#candidatures", init_script=None, viewport=(1440, 900), routes=None,
              hold_api=False):
        """`api`: the `GET /api/applications` payload, or a callable returning it per call
        (a polling test answers differently the second time). `routes`: {(method, path):
        (status, headers, body)} answered before the 404; every call to one of them, and every
        applications call, is appended to `page.api_calls` as (method, path); the renderer's
        files (`.js`, `.ttf`) to `page.file_calls`, by path. `hold_api`: the first applications
        call waits until the test calls `page.release_api()` (a test fixes the order of the
        page's own rendering and the API answer instead of racing them)."""
        ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                  accept_downloads=True)
        page = ctx.new_page()
        errors = []
        page.api_calls = []
        page.file_calls = []
        held = []

        def answer_api(route):
            payload = api() if callable(api) else api
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        def release_api():
            for _ in range(250):  # the page may not have asked yet: 5 s at most
                if held:
                    return answer_api(held.pop())
                page.wait_for_timeout(20)
            raise AssertionError("the page never called GET /api/applications")

        page.release_api = release_api
        page.api_held = False
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        if init_script:
            page.add_init_script(init_script)

        def handle(route, request):
            path = request.url[len(ORIGIN):].split("#")[0]
            extra = (routes or {}).get((request.method, path))
            if path in ("", "/", "/index.html"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            elif path == "/api/applications" and request.method == "GET":
                page.api_calls.append(("GET", path))
                if hold_api and not page.api_held:
                    page.api_held = True
                    held.append(route)
                else:
                    answer_api(route)
            elif extra is not None:
                page.api_calls.append((request.method, path))
                status, headers, body = extra
                route.fulfill(status=status, headers=headers, body=body)
            elif path.startswith("/api/"):
                route.fulfill(status=404, content_type="application/json",
                              body='{"error":"not found"}')
            elif (site / path.lstrip("/")).is_file():
                file = site / path.lstrip("/")
                if file.suffix in (".js", ".ttf"):  # the renderer, preloaded with Candidatures
                    page.file_calls.append(path)
                kind = STATIC_TYPES.get(file.suffix, "application/octet-stream")
                route.fulfill(status=200, content_type=kind, body=file.read_bytes())
            else:  # manifest, icons, the woff2 font: present in a deployed site, empty here
                route.fulfill(status=200, body=b"")

        page.route(f"{ORIGIN}/**", handle)
        page.goto(f"{ORIGIN}/{hash_}")
        pages.append(ctx)
        return page, errors

    yield _open
    for ctx in pages:
        ctx.close()


@pytest.fixture
def job_keys(dashboard_data):
    """The keys of the offers the page shows, best score first."""
    data, _seed = dashboard_data
    return [j["key"] for j in data["jobs"]]
