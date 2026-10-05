"""CLI-level tests for `job-match funding reprocess` and the M11 summary lines."""
from unittest.mock import patch

import pytest

from job_match.cli import _print_funding_summary, main
from job_match.domain.models import RunSummary


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        "funding:\n  requests_per_second: 0\n  sources: [maddyness]\n", encoding="utf-8"
    )
    monkeypatch.setenv("JOB_MATCH_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_funding_reprocess_invalid_since_exits_1(tmp_project, capsys):
    with patch("sys.argv", ["job-match", "funding", "reprocess", "--since", "2026-13-01"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "Invalid date" in capsys.readouterr().err


def test_funding_reprocess_dry_run_on_empty_db(tmp_project, capsys):
    with patch("sys.argv", ["job-match", "funding", "reprocess", "--dry-run", "--limit", "3"]):
        main()
    out = capsys.readouterr().out
    assert "Funding reprocess complete [DRY RUN]" in out
    assert "selected:   0" in out
    assert "funding:    0" in out


def test_funding_run_still_prints_m10_lines_plus_m11_lines(capsys):
    _print_funding_summary(RunSummary(pipeline="funding", feeds=1, fetched=2, articles=2))
    out = capsys.readouterr().out
    for line in ("feeds:      1", "found:      2", "new:        2", "skipped:    0",
                 "funding:    0", "events:     0", "leads:      0"):
        assert line in out


def test_print_funding_summary_shows_funding_lines_and_by_source(capsys):
    _print_funding_summary(RunSummary(
        pipeline="funding", feeds=2, fetched=10, articles=3, duplicates=6, errors=1,
        funding_articles=2, funding_events=1, funding_no_company=1, leads=1, leads_deduped=0,
        by_source={"maddyness": {"articles": 2, "funding": 2, "events": 1, "leads": 1},
                   "frenchweb": {"articles": 1, "funding": 0, "events": 0, "leads": 0}},
    ))
    out = capsys.readouterr().out
    assert "funding:    2  (articles, no company: 1)" in out
    assert "events:     1" in out
    assert "leads:      1  (deduped: 0)" in out
    assert "frenchweb    articles=1 funding=0 events=0 leads=0" in out
    assert "maddyness    articles=2 funding=2 events=1 leads=1" in out
