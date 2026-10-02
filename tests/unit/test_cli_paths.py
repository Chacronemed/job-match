"""Tests for CLI path resolution and Database migrations via importlib.resources.

Verifies that:
- _config_dir() / _data_dir() use CWD-relative defaults, not __file__-relative paths.
- Both are overridable via JOB_MATCH_CONFIG_DIR / JOB_MATCH_DATA_DIR env vars.
- Database() (no migrations_dir) finds SQL migrations via importlib.resources regardless of CWD.
- The CLI resolves config correctly when run from a temp directory that mimics CI layout.
"""
from pathlib import Path

from job_match.cli import _config_dir, _data_dir
from job_match.persistence.db import Database, _default_migrations

# ---------------------------------------------------------------------------
# _config_dir / _data_dir defaults
# ---------------------------------------------------------------------------

def test_config_dir_default_is_cwd_relative(monkeypatch, tmp_path):
    monkeypatch.delenv("JOB_MATCH_CONFIG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _config_dir() == Path("config")


def test_data_dir_default_is_cwd_relative(monkeypatch, tmp_path):
    monkeypatch.delenv("JOB_MATCH_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _data_dir() == Path("data")


def test_config_dir_env_var_absolute(monkeypatch, tmp_path):
    custom = tmp_path / "my_config"
    monkeypatch.setenv("JOB_MATCH_CONFIG_DIR", str(custom))
    assert _config_dir() == custom


def test_data_dir_env_var_absolute(monkeypatch, tmp_path):
    custom = tmp_path / "my_data"
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(custom))
    assert _data_dir() == custom


def test_config_dir_not_based_on_file():
    """Default must NOT contain the installed package path."""
    result = _config_dir()
    assert not result.is_absolute() or "site-packages" not in str(result)


# ---------------------------------------------------------------------------
# _default_migrations — importlib.resources
# ---------------------------------------------------------------------------

def test_default_migrations_returns_path():
    mdir = _default_migrations()
    assert isinstance(mdir, Path)


def test_default_migrations_contains_sql_files():
    mdir = _default_migrations()
    sql_files = sorted(mdir.glob("*.sql"))
    assert len(sql_files) >= 2
    assert any(f.stem.startswith("0001") for f in sql_files)


def test_default_migrations_works_from_any_cwd(monkeypatch, tmp_path):
    """Migrations must be found even when CWD has no 'migrations' folder."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "migrations").exists()
    mdir = _default_migrations()
    assert mdir.exists()
    assert any(mdir.glob("*.sql"))


# ---------------------------------------------------------------------------
# Database without explicit migrations_dir — uses importlib.resources
# ---------------------------------------------------------------------------

def test_database_default_migrations_applies_schema(tmp_path):
    db_path = tmp_path / "test.sqlite"
    with Database(path=str(db_path)) as db:
        tables = {
            row[0]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "jobs" in tables
    assert "companies" in tables


def test_database_default_migrations_from_foreign_cwd(monkeypatch, tmp_path):
    """Database() must work from a directory that has no migrations/ subdirectory."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "migrations").exists()
    db_path = tmp_path / "test.sqlite"
    with Database(path=str(db_path)) as db:
        count = db.conn.execute(
            "SELECT COUNT(*) FROM schema_version"
        ).fetchone()[0]
    assert count >= 2  # at least migration 0001 and 0002 applied


# ---------------------------------------------------------------------------
# Simulated CI layout (non-editable install cwd)
# ---------------------------------------------------------------------------

def test_cli_path_resolution_from_temp_project_root(monkeypatch, tmp_path):
    """Simulates running `job-match` from a freshly-checked-out project root.

    The CWD has config/ and data/ but no src/ — mimicking a CI workspace
    where the package is installed and the repo is the CWD.
    """
    # Create minimal config tree in tmp dir
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "marker.txt").write_text("ok")

    monkeypatch.delenv("JOB_MATCH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("JOB_MATCH_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    # _config_dir() should resolve to tmp_path/config (relative to cwd)
    result = _config_dir()
    assert result == Path("config")
    assert (tmp_path / result / "marker.txt").exists()
