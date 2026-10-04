import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from time import struct_time

import feedparser
import httpx

from job_match.adapters.funding.base import ArticleRef, FeedError
from job_match.adapters.http import HttpClient

logger = logging.getLogger(__name__)


def _struct_to_dt(value: struct_time | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime(*value[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _entry_to_ref(entry: dict) -> ArticleRef | None:
    """Map one feedparser entry to an ArticleRef. Returns None when there is no link."""
    link = (entry.get("link") or "").strip()
    if not link:
        return None
    title = (entry.get("title") or "").strip() or link
    published = _struct_to_dt(entry.get("published_parsed")) or _struct_to_dt(
        entry.get("updated_parsed")
    )
    summary = entry.get("summary") or None
    return ArticleRef(url=link, title=title, published_at=published, summary=summary)


class RssFundingSource:
    """Generic RSS/Atom feed source. Subclasses only set `name` and `FEED_URL`."""

    name: str = "rss"
    FEED_URL: str = ""

    def __init__(self, feed_url: str | None = None, http: HttpClient | None = None) -> None:
        self._feed_url = feed_url or self.FEED_URL
        self._http = http or HttpClient(follow_redirects=True)
        self._api_calls = 0

    @property
    def feed_url(self) -> str:
        return self._feed_url

    @property
    def api_calls_count(self) -> int:
        return self._api_calls

    def fetch_articles(self, since: datetime | None = None) -> Iterator[ArticleRef]:
        try:
            resp = self._http.get(self._feed_url)
            self._api_calls += 1
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FeedError(f"{self.name}: feed request failed: {exc}") from exc

        parsed = feedparser.parse(resp.content)
        entries = parsed.get("entries") or []
        if parsed.get("bozo") and not entries:
            reason = parsed.get("bozo_exception")
            raise FeedError(f"{self.name}: feed could not be parsed: {reason}")

        for entry in entries:
            ref = _entry_to_ref(entry)
            if ref is None:
                logger.warning("%s: feed entry without link skipped", self.name)
                continue
            if since is not None and ref.published_at is not None and ref.published_at < since:
                continue
            yield ref
