"""`job-match dashboard --out DIR`: writes the site, prints counts only, fails without a DB."""
import argparse
import json
from unittest.mock import patch

import pytest

from job_match.cli import _cmd_dashboard, main
from job_match.persistence.db import Database


@pytest.fixture
def tmp_project(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        "strong_threshold: 70\nbase_score: 50\ntitle_bonus: 0\n"
        "dedup_window_days: 30\nfuzzy_title_threshold: 0.85\n"
        "fuzzy_desc_threshold: 0.80\n",
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    return tmp_path


def test_dashboard_writes_site_and_prints_counts_only(
    tmp_project, seed_dashboard, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_project)
    with Database(path=str(tmp_project / "data" / "jobs.sqlite")) as db:
        seed = seed_dashboard(db)

    _cmd_dashboard(argparse.Namespace(out="site"))

    out = capsys.readouterr().out
    assert "3 jobs (1 strong, 1 eligible, 1 stretch), 1 leads, 30 runs" in out
    assert seed.xss_title not in out and "Acme" not in out and seed.secret_keyword not in out
    index = tmp_project / "site" / "index.html"
    data = json.loads((tmp_project / "site" / "data.json").read_text(encoding="utf-8"))
    assert index.exists() and len(data["jobs"]) == 3


def test_dashboard_without_a_database_exits_1(tmp_project, monkeypatch, capsys):
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as exc:
        _cmd_dashboard(argparse.Namespace(out="site"))
    assert exc.value.code == 1
    assert "No database" in capsys.readouterr().err
    assert not (tmp_project / "site").exists()
    assert not (tmp_project / "data" / "jobs.sqlite").exists()  # never created on the side


def test_dashboard_subcommand_is_registered(tmp_project, seed_dashboard, monkeypatch):
    monkeypatch.chdir(tmp_project)
    with Database(path=str(tmp_project / "data" / "jobs.sqlite")) as db:
        seed_dashboard(db)
    with patch("sys.argv", ["job-match", "dashboard", "--out", "out-dir"]):
        main()
    assert (tmp_project / "out-dir" / "index.html").exists()
