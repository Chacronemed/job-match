from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.domain.models import Article
from job_match.persistence.db import Database
from job_match.persistence.repositories import ArticleRepository

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _article(url: str = "https://www.maddyness.com/2026/10/02/acme", **kw) -> Article:
    return Article(
        source=kw.pop("source", "maddyness"),
        url=url,
        title=kw.pop("title", "Acme lève 10 M€"),
        collected_at=_NOW,
        **kw,
    )


def test_migration_0003_adds_extract_column(db):
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(articles)")}
    assert "extract" in cols
    versions = {r[0] for r in db.conn.execute("SELECT version FROM schema_version")}
    assert 3 in versions


def test_save_and_round_trip(db):
    repo = ArticleRepository(db.conn)
    saved = repo.save(_article(published_at=_NOW, extract="Acme annonce…"))

    assert saved.id is not None
    assert repo.exists(saved.url)
    got = repo.get_by_url(saved.url)
    assert got == saved
    assert got.published_at == _NOW
    assert got.collected_at == _NOW
    assert got.extract == "Acme annonce…"


def test_missing_metadata_stays_null(db):
    repo = ArticleRepository(db.conn)
    saved = repo.save(_article())
    assert saved.published_at is None
    assert saved.extract is None


def test_save_same_url_twice_keeps_first(db):
    repo = ArticleRepository(db.conn)
    first = repo.save(_article(title="first"))
    second = repo.save(_article(title="second", source="frenchweb"))

    assert second.id == first.id
    assert second.title == "first"
    assert repo.count() == 1


def test_source_registered_as_funding_kind(db):
    ArticleRepository(db.conn).save(_article())
    row = db.conn.execute("SELECT kind FROM sources WHERE id = 'maddyness'").fetchone()
    assert row["kind"] == "funding"


def test_list_recent_orders_newest_first(db):
    repo = ArticleRepository(db.conn)
    older = Article(source="maddyness", url="https://x.test/old", title="old",
                    collected_at=datetime(2026, 10, 1, tzinfo=UTC))
    repo.save(older)
    repo.save(_article(url="https://x.test/new"))
    urls = [a.url for a in repo.list_recent(limit=10)]
    assert urls == ["https://x.test/new", "https://x.test/old"]
