"""Tests for CLI path resolution and Database migrations via importlib.resources.

Verifies that:
- _config_dir() / _data_dir() use CWD-relative defaults, not __file__-relative paths.
- Both are overridable via JOB_MATCH_CONFIG_DIR / JOB_MATCH_DATA_DIR env vars.
- Database() (no migrations_dir) finds SQL migrations via importlib.resources regardless of CWD.
- The CLI resolves config correctly when run from a temp directory that mimics CI layout.
"""
import logging
from pathlib import Path
from types import SimpleNamespace

from job_match.cli import (
    _config_dir,
    _data_dir,
    _print_reprocess_summary,
    _print_summary,
    _quiet_http_logs,
)
from job_match.domain.models import RunSummary
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


# ---------------------------------------------------------------------------
# _print_summary — the jobs summary goes to a public CI log
# ---------------------------------------------------------------------------

def test_print_summary_keeps_keywords_off_stdout(capsys, caplog):
    """Departments are printed; the per-keyword breakdown stays at DEBUG.

    `job-match run` stdout lands in the public Actions log, and query keywords come
    from the private profile — same rule as the adapter's per-query log line.
    """
    summary = RunSummary(
        pipeline="jobs",
        fetched=3,
        queries=2,
        by_area={"92": 2, "77": 1},
        by_keyword={"devops": 2, "sre": 1},
    )

    with caplog.at_level(logging.DEBUG, logger="job_match.cli"):
        _print_summary(summary)

    out = capsys.readouterr().out
    assert "92: 2" in out  # departments stay visible
    assert "devops" not in out
    assert "per keyword" not in out
    assert "devops=2" in caplog.text  # still available at DEBUG


# ---------------------------------------------------------------------------
# _quiet_http_logs — Jooble's API key travels in the URL path
# ---------------------------------------------------------------------------

def test_quiet_http_logs_hides_the_request_url(caplog):
    """httpx logs the full URL at INFO; for Jooble that URL contains the API key.

    `job-match run` output goes to a public Actions log, so that logger has to stay
    above INFO. Warnings and errors still get through.
    """
    logging.getLogger("httpx").setLevel(logging.INFO)  # simulate basicConfig(INFO)
    _quiet_http_logs()

    httpx_logger = logging.getLogger("httpx")
    assert httpx_logger.isEnabledFor(logging.WARNING)
    assert not httpx_logger.isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)


def test_print_summary_shows_counts_per_source(capsys):
    summary = RunSummary(
        pipeline="jobs",
        fetched=3,
        by_source={
            "france_travail": {"fetched": 2, "eligible": 2, "duplicates": 0, "calls": 98},
            "jooble": {"fetched": 1, "eligible": 0, "duplicates": 1, "calls": 7},
        },
    )
    _print_summary(summary)

    out = capsys.readouterr().out
    assert "per source" in out
    assert "france_travail" in out and "98" in out
    assert "jooble" in out and "7" in out


# ---------------------------------------------------------------------------
# _print_reprocess_summary: counts always, titles only when asked
# ---------------------------------------------------------------------------

def _reprocess_summary() -> RunSummary:
    return RunSummary(
        pipeline="jobs_reprocess",
        fetched=533,
        rejected_jobs=448,
        rejected_by_reason={"EXPERIENCE": 286, "NOT_RELEVANT": 194},
        eligible=85,
        strong=28,
        duplicates=85,
    )


def _top() -> list:
    return [
        SimpleNamespace(score=91, title="Ingenieur DevOps AWS", company="Collective.work"),
        SimpleNamespace(score=90, title="Ingenieur DevOps cloud", company="Externatic"),
    ]


def test_reprocess_summary_with_limit_zero_prints_counts_without_titles(capsys):
    """The daily workflow runs this in a public log: aggregates only."""
    _print_reprocess_summary(_reprocess_summary(), _top(), limit=0, dry_run=False)

    out = capsys.readouterr().out
    assert "jobs read:  533" in out
    assert "eligible:   85" in out
    assert "strong:     28" in out
    assert "self-links dropped: 85" in out
    assert "EXPERIENCE: 286" in out
    assert "strong titles" not in out
    assert "Externatic" not in out and "Collective.work" not in out


def test_reprocess_summary_without_a_limit_shows_the_top_titles(capsys):
    _print_reprocess_summary(_reprocess_summary(), _top(), limit=None, dry_run=False)

    out = capsys.readouterr().out
    assert "top 2 strong titles:" in out
    assert "Collective.work" in out and "Externatic" in out


def test_reprocess_summary_limit_caps_the_titles_and_marks_a_dry_run(capsys):
    _print_reprocess_summary(_reprocess_summary(), _top(), limit=1, dry_run=True)

    out = capsys.readouterr().out
    assert "Reprocess complete [DRY RUN]" in out
    assert "top 1 strong titles:" in out
    assert "Externatic" not in out


# ---------------------------------------------------------------------------
# The department breakdown, top 10
# ---------------------------------------------------------------------------

def test_the_summary_ranks_departments_by_count(capsys):
    _print_summary(RunSummary(
        pipeline="jobs",
        fetched=6,
        by_department={"75": 4, "92": 10, "?": 1},
    ))

    out = capsys.readouterr().out
    assert "fetched per department, from the offer location (top 10):" in out
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("75:", "92:", "?:"))]
    assert lines == ["92: 10", "75: 4", "?: 1"]  # biggest first
    assert "more departments" not in out


def test_the_summary_keeps_the_department_list_to_ten_lines(capsys):
    _print_summary(RunSummary(
        pipeline="jobs",
        by_department={f"{n:02d}": 100 - n for n in range(1, 16)},
    ))

    out = capsys.readouterr().out
    listed = [ln for ln in out.splitlines() if ln.startswith("    ") and ":" in ln]
    assert len(listed) == 11  # 10 departments plus the tail line
    assert "+5 more departments: 435" in out  # 89+88+87+86+85


def test_a_run_without_locations_prints_no_department_block(capsys):
    _print_summary(RunSummary(pipeline="jobs"))
    assert "per department" not in capsys.readouterr().out
