import logging
import re
import time

import httpx
import trafilatura

from job_match.adapters.http import HttpClient

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
ELLIPSIS = "…"


def make_extract(text: str, max_chars: int) -> str:
    """Whitespace-collapsed head of the article text, cut on a word boundary."""
    flat = _WS_RE.sub(" ", text).strip()
    if len(flat) <= max_chars:
        return flat
    cut = flat[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + ELLIPSIS


class ArticleFetcher:
    """Fetches an article page politely and extracts its main text.

    The full text is returned to the caller and never stored; callers keep only a
    short extract (see `make_extract`).
    """

    def __init__(
        self,
        http: HttpClient | None = None,
        requests_per_second: float = 1.0,
    ) -> None:
        self._http = http or HttpClient(follow_redirects=True)
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request_time = 0.0
        self._api_calls = 0

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def fetch_text(self, url: str) -> str | None:
        """Return the extracted main text, or None on any failure (logged, never raised)."""
        self._throttle()
        try:
            resp = self._http.get(url)
            self._api_calls += 1
        except httpx.HTTPError as exc:
            logger.warning("article fetch failed (%s): %s", type(exc).__name__, url)
            return None
        if resp.status_code != 200:
            logger.warning("article fetch returned %d: %s", resp.status_code, url)
            return None
        try:
            text = trafilatura.extract(
                resp.text, url=url, include_comments=False, include_tables=False
            )
        except Exception as exc:  # third-party parser: never let it crash the run
            logger.warning("article extraction raised %s: %s", type(exc).__name__, url)
            return None
        if not text or not text.strip():
            logger.warning("article extraction returned nothing: %s", url)
            return None
        return text
