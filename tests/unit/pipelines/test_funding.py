"""Integration tests for pipelines/funding.py with in-memory SQLite, fake feeds and a
fake fetcher. No network."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.adapters.funding.base import ArticleRef, FeedError
from job_match.config.schema import FundingConfig, Settings
from job_match.persistence.db import Database
from job_match.persistence.repositories import ArticleRepository
from job_match.pipelines.funding import run_funding

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 2, 7, 0, 0, tzinfo=UTC)
_BODY = "La startup Acme annonce un tour de table de dix millions d'euros. " * 20


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeFeed:
    def __init__(self, name: str, refs: list[ArticleRef], fail: bool = False) -> None:
        self.name = name
        self._refs = refs
        self._fail = fail
        self.api_calls_count = 1

    def fetch_articles(self, since=None):
        if self._fail:
            raise FeedError(f"{self.name}: down")
        return iter(self._refs)


class FakeFetcher:
    """Returns a body for every URL except those listed in `broken`."""

    def __init__(self, broken: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._broken = broken or set()
        self.api_calls_count = 0

    def fetch_text(self, url: str) -> str | None:
        self.calls.append(url)
        self.api_calls_count += 1
        return None if url in self._broken else _BODY


def _ref(slug: str, **kw) -> ArticleRef:
    return ArticleRef(
        url=f"https://www.maddyness.com/2026/10/02/{slug}/",
        title=kw.pop("title", slug.replace("-", " ")),
        published_at=kw.pop("published_at", _NOW),
        **kw,
    )


def _settings(max_chars: int = 80) -> Settings:
    return Settings(funding=FundingConfig(requests_per_second=0, extract_max_chars=max_chars))


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_new_articles_are_stored_with_short_extract(db):
    feed = FakeFeed("maddyness", [_ref("acme-leve"), _ref("beta-leve", published_at=None)])
    fetcher = FakeFetcher()

    summary = run_funding([feed], _settings(max_chars=80), db, fetcher)

    assert summary.pipeline == "funding"
    assert (summary.feeds, summary.fetched, summary.articles) == (1, 2, 2)
    assert summary.duplicates == 0
    assert summary.errors == 0
    assert summary.api_calls == 3  # 1 feed + 2 articles

    repo = ArticleRepository(db.conn)
    assert repo.count() == 2
    a = repo.get_by_url("https://www.maddyness.com/2026/10/02/acme-leve")
    assert a is not None
    assert a.source == "maddyness"
    assert a.title == "acme leve"
    assert a.published_at == _NOW
    assert a.extract is not None
    assert len(a.extract) <= 81  # max_chars + ellipsis
    assert len(_BODY) > 81  # full body never stored
    b = repo.get_by_url("https://www.maddyness.com/2026/10/02/beta-leve")
    assert b is not None and b.published_at is None

    kind = db.conn.execute("SELECT kind FROM sources WHERE id = 'maddyness'").fetchone()[0]
    assert kind == "funding"


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_seen_article_is_skipped_without_refetch(db):
    feed = FakeFeed("maddyness", [_ref("acme-leve")])
    first = FakeFetcher()
    run_funding([feed], _settings(), db, first)
    assert first.calls == ["https://www.maddyness.com/2026/10/02/acme-leve/"]

    second = FakeFetcher()
    summary = run_funding([feed], _settings(), db, second)

    assert second.calls == []  # no refetch of an already-seen URL
    assert summary.fetched == 1
    assert summary.articles == 0
    assert summary.duplicates == 1
    assert ArticleRepository(db.conn).count() == 1


def test_duplicate_url_within_one_run_is_deduped_after_normalization(db):
    refs = [
        _ref("acme-leve"),
        ArticleRef(
            url="https://WWW.maddyness.com/2026/10/02/acme-leve?utm_source=rss&utm_medium=feed#top",
            title="same article, tracked link",
            published_at=_NOW,
        ),
    ]
    fetcher = FakeFetcher()
    summary = run_funding([FakeFeed("maddyness", refs)], _settings(), db, fetcher)

    assert len(fetcher.calls) == 1
    assert (summary.fetched, summary.articles, summary.duplicates) == (2, 1, 1)
    assert ArticleRepository(db.conn).count() == 1


def test_same_url_across_two_sources_is_stored_once(db):
    ref = _ref("acme-leve")
    feeds = [FakeFeed("maddyness", [ref]), FakeFeed("frenchweb", [ref])]
    summary = run_funding(feeds, _settings(), db, FakeFetcher())

    assert summary.feeds == 2
    assert (summary.articles, summary.duplicates) == (1, 1)
    stored = ArticleRepository(db.conn).get_by_url("https://www.maddyness.com/2026/10/02/acme-leve")
    assert stored is not None and stored.source == "maddyness"  # first seen wins


# ---------------------------------------------------------------------------
# Failures never crash the run
# ---------------------------------------------------------------------------

def test_broken_feed_is_counted_and_other_feeds_still_run(db):
    feeds = [FakeFeed("maddyness", [], fail=True), FakeFeed("frenchweb", [_ref("ok")])]
    summary = run_funding(feeds, _settings(), db, FakeFetcher())

    assert summary.feeds == 1
    assert summary.errors == 1
    assert summary.articles == 1


def test_unexpected_feed_exception_is_isolated(db):
    class Exploding:
        name = "boom"

        def fetch_articles(self, since=None):
            raise ValueError("unexpected")

    summary = run_funding([Exploding(), FakeFeed("frenchweb", [_ref("ok")])], _settings(), db,
                          FakeFetcher())
    assert (summary.feeds, summary.errors, summary.articles) == (1, 1, 1)


def test_failed_article_fetch_is_counted_and_not_stored(db):
    broken = "https://www.maddyness.com/2026/10/02/paywalled/"
    feed = FakeFeed("maddyness", [_ref("paywalled"), _ref("fine")])
    summary = run_funding([feed], _settings(), db, FakeFetcher(broken={broken}))

    assert summary.errors == 1
    assert summary.articles == 1
    repo = ArticleRepository(db.conn)
    assert repo.count() == 1
    assert not repo.exists("https://www.maddyness.com/2026/10/02/paywalled")  # retried next run


# ---------------------------------------------------------------------------
# --limit / --dry-run
# ---------------------------------------------------------------------------

def test_limit_caps_entries_across_feeds(db):
    feeds = [
        FakeFeed("maddyness", [_ref("a"), _ref("b")]),
        FakeFeed("frenchweb", [_ref("c"), _ref("d")]),
    ]
    fetcher = FakeFetcher()
    summary = run_funding(feeds, _settings(), db, fetcher, limit=3)

    assert summary.fetched == 3
    assert summary.articles == 3
    assert len(fetcher.calls) == 3


def test_dry_run_fetches_but_writes_nothing(db):
    fetcher = FakeFetcher()
    summary = run_funding([FakeFeed("maddyness", [_ref("a")])], _settings(), db, fetcher,
                          dry_run=True)

    assert summary.articles == 1
    assert fetcher.calls  # extraction still exercised
    assert ArticleRepository(db.conn).count() == 0
