"""Tests for the RSS funding adapters (Maddyness, FrenchWeb). No live calls."""
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from job_match.adapters.funding.base import ArticleRef, FeedError, FundingSource
from job_match.adapters.funding.frenchweb import FrenchWebSource
from job_match.adapters.funding.maddyness import MaddynessSource
from job_match.adapters.funding.rss import RssFundingSource, _entry_to_ref
from job_match.adapters.http import HttpClient

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
FEED_URL = "https://feeds.example.test/rss"


def _feed_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _source(cls=MaddynessSource) -> RssFundingSource:
    return cls(feed_url=FEED_URL, http=HttpClient(max_retries=0))


# ---------------------------------------------------------------------------
# Protocol / constants
# ---------------------------------------------------------------------------

def test_sources_satisfy_protocol_and_have_distinct_names():
    for cls in (MaddynessSource, FrenchWebSource):
        src = cls()
        assert isinstance(src, FundingSource)
        assert src.feed_url.startswith("https://")
    assert MaddynessSource.name != FrenchWebSource.name


# ---------------------------------------------------------------------------
# Entry mapping
# ---------------------------------------------------------------------------

def test_entry_without_link_is_dropped():
    assert _entry_to_ref({"title": "no link"}) is None


def test_entry_without_title_falls_back_to_link():
    ref = _entry_to_ref({"link": "https://x.test/a"})
    assert ref is not None
    assert ref.title == "https://x.test/a"
    assert ref.published_at is None
    assert ref.summary is None


# ---------------------------------------------------------------------------
# fetch_articles
# ---------------------------------------------------------------------------

def test_fetch_articles_parses_fixture_feed():
    with respx.mock:
        respx.get(FEED_URL).mock(
            return_value=httpx.Response(200, content=_feed_bytes("rss_maddyness.xml"))
        )
        refs = list(_source().fetch_articles())

    # 4 items in the fixture, one has no link → 3 refs
    assert len(refs) == 3
    assert all(isinstance(r, ArticleRef) for r in refs)

    first = refs[0]
    assert first.url == "https://www.maddyness.com/2026/10/02/acme-leve-10-millions/"
    assert "Acme" in first.title
    assert first.published_at == datetime(2026, 10, 2, 7, 0, 25, tzinfo=UTC)
    assert "série A" in (first.summary or "")

    no_date = refs[1]
    assert no_date.published_at is None  # missing pubDate → None, never invented

    tracked = refs[2]
    assert "utm_source" in tracked.url  # adapter does not normalize; the pipeline does


def test_fetch_articles_counts_one_api_call():
    with respx.mock:
        respx.get(FEED_URL).mock(
            return_value=httpx.Response(200, content=_feed_bytes("rss_maddyness.xml"))
        )
        src = _source(FrenchWebSource)
        list(src.fetch_articles())
    assert src.api_calls_count == 1


def test_fetch_articles_since_filters_dated_entries_but_keeps_undated():
    since = datetime(2026, 10, 2, 7, 15, 0, tzinfo=UTC)
    with respx.mock:
        respx.get(FEED_URL).mock(
            return_value=httpx.Response(200, content=_feed_bytes("rss_maddyness.xml"))
        )
        refs = list(_source().fetch_articles(since=since))
    urls = [r.url for r in refs]
    assert "https://www.maddyness.com/2026/10/02/acme-leve-10-millions/" not in urls  # 07:00
    assert "https://www.maddyness.com/2026/10/01/sans-date/" in urls  # undated: kept
    assert any("utm_source" in u for u in urls)  # 07:30 > since


def test_invalid_feed_raises_feed_error():
    with respx.mock:
        respx.get(FEED_URL).mock(
            return_value=httpx.Response(200, content=_feed_bytes("rss_invalid.xml"))
        )
        with pytest.raises(FeedError):
            list(_source().fetch_articles())


def test_http_error_raises_feed_error():
    with respx.mock:
        respx.get(FEED_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(FeedError):
            list(_source().fetch_articles())


def test_network_failure_raises_feed_error():
    with respx.mock:
        respx.get(FEED_URL).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(FeedError):
            list(_source().fetch_articles())
