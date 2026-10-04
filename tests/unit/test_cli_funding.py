"""CLI-level tests for `job-match funding run`. No network: sources are patched."""
from unittest.mock import patch

import pytest

from job_match.adapters.funding.base import ArticleRef
from job_match.cli import _build_funding_sources, main
from job_match.domain.models import RunSummary


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        "funding:\n  requests_per_second: 0\n  extract_max_chars: 100\n  sources: [maddyness]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JOB_MATCH_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_build_funding_sources_known_names():
    sources = _build_funding_sources(["maddyness", "frenchweb"])
    assert [s.name for s in sources] == ["maddyness", "frenchweb"]


def test_build_funding_sources_unknown_name_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        _build_funding_sources(["techcrunch"])
    assert exc.value.code == 1
    assert "Unknown funding source" in capsys.readouterr().err


def test_funding_without_subcommand_exits_1(capsys):
    with patch("sys.argv", ["job-match", "funding"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_funding_run_dry_run_prints_summary(tmp_project, capsys):
    refs = [ArticleRef(url="https://www.maddyness.com/2026/10/02/acme/", title="Acme")]

    class FakeSource:
        name = "maddyness"
        api_calls_count = 1

        def fetch_articles(self, since=None):
            return iter(refs)

    body = "Acme annonce un tour de table. " * 20
    with (
        patch("job_match.cli._build_funding_sources", return_value=[FakeSource()]),
        patch("job_match.funding.article.ArticleFetcher.fetch_text", return_value=body),
        patch("sys.argv", ["job-match", "funding", "run", "--dry-run", "--limit", "5"]),
    ):
        main()

    out = capsys.readouterr().out
    assert "[DRY RUN]" in out
    assert "feeds:      1" in out
    assert "found:      1" in out
    assert "new:        1" in out
    assert not (tmp_project / "data" / "jobs.sqlite").exists()  # dry run writes nothing


def test_funding_run_writes_db_and_skips_on_second_run(tmp_project, capsys):
    refs = [ArticleRef(url="https://www.maddyness.com/2026/10/02/acme/", title="Acme")]

    class FakeSource:
        name = "maddyness"
        api_calls_count = 1

        def fetch_articles(self, since=None):
            return iter(refs)

    body = "Acme annonce un tour de table. " * 20
    with (
        patch("job_match.cli._build_funding_sources", return_value=[FakeSource()]),
        patch("job_match.funding.article.ArticleFetcher.fetch_text", return_value=body) as ft,
        patch("sys.argv", ["job-match", "funding", "run"]),
    ):
        main()
        first = capsys.readouterr().out
        main()
        second = capsys.readouterr().out

    assert "new:        1" in first
    assert "new:        0" in second and "skipped:    1" in second
    assert ft.call_count == 1  # second run never refetched
    assert (tmp_project / "data" / "jobs.sqlite").exists()


def test_print_funding_summary_shape(capsys):
    from job_match.cli import _print_funding_summary

    _print_funding_summary(RunSummary(pipeline="funding", feeds=2, fetched=10, articles=3,
                                      duplicates=6, errors=1, api_calls=5))
    out = capsys.readouterr().out
    for line in ("feeds:      2", "found:      10", "new:        3", "skipped:    6",
                 "errors:     1", "api_calls:  5"):
        assert line in out
