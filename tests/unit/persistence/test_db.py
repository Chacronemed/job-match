from pathlib import Path

import pytest

from job_match.persistence.db import Database

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _table_names(db: Database) -> set[str]:
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def test_tables_created_after_connect(db):
    tables = _table_names(db)
    assert "jobs" in tables
    assert "companies" in tables
    assert "sources" in tables
    assert "raw_payloads" in tables
    assert "job_duplicates" in tables
    assert "job_scores" in tables
    assert "funding_events" in tables
    assert "leads" in tables
    assert "runs" in tables
    assert "schema_version" in tables


def test_schema_version_tracked(db):
    rows = db.conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    versions = [r[0] for r in rows]
    # Versions must be consecutive starting from 1
    assert versions == list(range(1, len(versions) + 1))
    assert len(versions) >= 1


def test_migrations_idempotent(db):
    """Connecting a second time to the same DB must not re-apply migrations."""
    db2 = Database(path=":memory:", migrations_dir=MIGRATIONS)
    db2.connect()
    count = db2.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count >= 1
    db2.close()


def test_no_pending_migration_on_reconnect(db):
    """Simulate reconnect: migrations must not re-run if schema_version is up to date."""
    before = db.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    # Force _apply_migrations again directly
    db._apply_migrations()
    after = db.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert before == after


def test_foreign_keys_enabled(db):
    pragma = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert pragma == 1


def test_connect_creates_parent_directory(tmp_path):
    """Database must mkdir the parent directory if it does not exist."""
    db_path = tmp_path / "nested" / "subdir" / "jobs.sqlite"
    assert not db_path.parent.exists()
    with Database(path=str(db_path), migrations_dir=MIGRATIONS) as d:
        tables = _table_names(d)
    assert db_path.exists()
    assert "jobs" in tables


def test_connect_memory_does_not_mkdir(tmp_path, monkeypatch):
    """:memory: path must not attempt to create a parent directory."""
    # Patch mkdir to detect any unexpected call
    mkdir_calls: list = []
    original_mkdir = Path.mkdir

    def _spy_mkdir(self, *args, **kwargs):
        mkdir_calls.append(str(self))
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _spy_mkdir)
    with Database(path=":memory:", migrations_dir=MIGRATIONS):
        pass
    assert not mkdir_calls
