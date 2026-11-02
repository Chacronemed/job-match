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
from job_match.dashboard.render import render_index
from job_match.persistence.db import Database

ORIGIN = "http://jm.test"


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
def open_dashboard(browser, dashboard_data):
    """`open_dashboard(api, hash, init_script=None)` -> (page, errors).

    Serves the rendered page at ORIGIN and answers `GET /api/applications` with `api`;
    `errors` collects console errors and uncaught exceptions as they happen.
    """
    data, _seed = dashboard_data
    html = render_index(data)
    pages = []

    def _open(api, hash_="#candidatures", init_script=None, viewport=(1440, 900), routes=None):
        """`routes`: {(method, path): (status, headers, body)} answered before the 404; the
        calls made to them are appended to `page.api_calls` as (method, path)."""
        ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                  accept_downloads=True)
        page = ctx.new_page()
        errors = []
        page.api_calls = []
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
                route.fulfill(status=200, content_type="application/json", body=json.dumps(api))
            elif extra is not None:
                page.api_calls.append((request.method, path))
                status, headers, body = extra
                route.fulfill(status=status, headers=headers, body=body)
            elif path.startswith("/api/"):
                route.fulfill(status=404, content_type="application/json",
                              body='{"error":"not found"}')
            else:  # manifest, icons, the font: present in a deployed site, empty here
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
