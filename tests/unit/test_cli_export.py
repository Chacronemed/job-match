"""`job-match export --top N --format career-ops`: pipeline.md lines, nothing private."""
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match.cli import _cmd_export, main
from job_match.export.career_ops import ExportLine, append_to_inbox, select_top
from job_match.persistence.db import Database


@pytest.fixture
def tmp_project(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text("strong_threshold: 70\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    return tmp_path


def _ns(**kw) -> argparse.Namespace:
    base = {"top": 3, "days": 1, "format": "career-ops", "out": None, "append": None}
    return argparse.Namespace(**{**base, **kw})


def test_export_writes_the_top_matches_as_a_pending_lane(
    tmp_project, seed_dashboard, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_project)
    with Database(path=str(tmp_project / "data" / "jobs.sqlite")) as db:
        seed = seed_dashboard(db)

    _cmd_export(_ns(out="out/lane.md"), now=seed.now + timedelta(hours=1))

    text = Path("out/lane.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "## Pending"
    # strong (85) then stretch (72); the duplicate (90) and the rejected job are not canonical
    # matches, and the eligible job's `javascript:` URL is dropped.
    assert len(lines) == 3
    assert lines[1].startswith("- [ ] https://example.test/strong | Acme | ")
    assert "| note: job-match 85/100" in lines[1]
    assert lines[2].startswith("- [ ] https://example.test/stretch | Gamma | SRE confirmé | ")
    # The title cell is text career-ops reads as text; only the URL cell is a link.
    assert all(row.split(" | ")[0].startswith("- [ ] https://") for row in lines[1:])
    assert "Secret description" not in text and seed.secret_keyword not in text
    out = capsys.readouterr().out
    assert "career-ops: 2 jobs (top 3, last 1 day(s))" in out
    assert "Acme" not in out and seed.secret_keyword not in out
    assert "\r\n" not in Path("out/lane.md").read_bytes().decode()


def test_export_without_a_database_fails_clearly(tmp_project, monkeypatch, capsys):
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as exc:
        _cmd_export(_ns())
    assert exc.value.code == 1
    assert "No database" in capsys.readouterr().err


def test_export_subcommand_is_registered(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["job-match", "export", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--top" in out and "career-ops" in out and "--append" in out


# ---------------------------------------------------------------------------
# selection and file logic, without a database
# ---------------------------------------------------------------------------

def _line(url: str, score: int = 80) -> ExportLine:
    return ExportLine(url, "Acme", "SRE", "Paris", score, datetime(2026, 11, 3, tzinfo=UTC))


def test_render_escapes_the_column_separator_and_adds_the_posting_date():
    line = ExportLine("https://x.test/1", "A|B", "DevOps\nSRE", "Paris", 77,
                      datetime(2026, 11, 3, 8, 0, tzinfo=UTC))
    assert line.render() == (
        "- [ ] https://x.test/1 | A/B | DevOps SRE | Paris | note: job-match 77/100"
        " | posted: 2026-11-03"
    )


def test_select_top_respects_the_window_and_the_count(seed_dashboard):
    from job_match.persistence.repositories import JobRepository
    with Database(path=":memory:") as db:
        now = seed_dashboard(db).now + timedelta(hours=1)
        jobs = JobRepository(db.conn).list_canonical_scored(now=now, max_age_days=45)
    assert [line.score for line in select_top(jobs, top=1, now=now, days=1)] == [85]
    # Everything in the seed was collected "now": a window that ends yesterday is empty.
    assert select_top(jobs, top=3, now=now + timedelta(days=3), days=1) == []


def test_append_inserts_under_pending_and_skips_known_urls(tmp_path):
    inbox = tmp_path / "pipeline.md"
    inbox.write_text(
        "## Pending\n- [ ] https://x.test/old\n\n## Processed\n- [x] #1 | https://x.test/done\n",
        encoding="utf-8",
    )
    added = append_to_inbox([_line("https://x.test/done"), _line("https://x.test/new")], inbox)
    assert added == 1
    rows = inbox.read_text(encoding="utf-8").splitlines()
    assert rows[:3] == ["## Pending", "- [ ] https://x.test/old",
                        rows[2]] and rows[2].startswith("- [ ] https://x.test/new |")
    assert rows[-2:] == ["## Processed", "- [x] #1 | https://x.test/done"]


def test_append_creates_the_file_when_missing(tmp_path):
    inbox = tmp_path / "new" / "pipeline.md"
    assert append_to_inbox([_line("https://x.test/a")], inbox) == 1
    assert inbox.read_text(encoding="utf-8").startswith("## Pending\n- [ ] https://x.test/a |")
