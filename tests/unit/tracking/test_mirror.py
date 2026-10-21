"""The D1 -> jobs DB mirror: validated rows only, all or nothing, never a note in the logs."""
import argparse
import logging

import pytest

from job_match.persistence.db import Database
from job_match.persistence.repositories import ApplicationRepository
from job_match.tracking.mirror import MirrorFormatError, import_tracking, read_export

KEY = "france_travail:123ABCD"


def _rows(conn, table):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


def test_valid_export_is_mirrored(export, rows):
    apps = export([rows.application(KEY, follow_up_at="2026-10-21", note=rows.note,
                                    cv_url=rows.url)])
    decs = export([rows.decision(1, KEY), rows.decision(2, KEY, "too_senior", None)])
    with Database(path=":memory:") as db:
        result = import_tracking(db.conn, apps, decs)
        assert (result.applications, result.decisions, result.skipped) == (1, 2, 0)
        (row,) = _rows(db.conn, "applications")
        assert row["note"] == rows.note and row["follow_up_at"] == "2026-10-21"
        assert [r["label"] for r in _rows(db.conn, "decisions")] == ["good_fit", "too_senior"]


@pytest.mark.parametrize("change", [
    {"status": "hired"},
    {"job_key": "not a key"},
    {"applied_at": "2026-02-30"},
    {"follow_up_at": "20/10/2026"},
    {"note": "x" * 2001},
    {"cv_url": "http://example.com/cv"},
    {"cv_url": "javascript:alert(1)"},
    {"extra": 1},
    {"updated_at": None},
])
def test_invalid_application_rows_are_skipped_and_counted(export, rows, change):
    bad = {**rows.application(KEY), **change}
    good = rows.application("france_travail:OK1")
    with Database(path=":memory:") as db:
        result = import_tracking(db.conn, export([good, bad]), export([]))
        assert (result.applications, result.skipped) == (1, 1)
        assert [r["job_key"] for r in _rows(db.conn, "applications")] == ["france_travail:OK1"]


@pytest.mark.parametrize("change", [
    {"label": "great"},
    {"score_at_decision": 101},
    {"score_at_decision": True},
    {"id": "1"},
])
def test_invalid_decision_rows_are_skipped(export, rows, change):
    bad = {**rows.decision(1, KEY), **change}
    with Database(path=":memory:") as db:
        result = import_tracking(db.conn, export([]), export([bad]))
        assert (result.decisions, result.skipped) == (0, 1)


def test_import_replaces_the_previous_mirror(export, rows):
    with Database(path=":memory:") as db:
        import_tracking(db.conn, export([rows.application(KEY), rows.application("adzuna:9")]),
                        export([rows.decision(1, KEY)]))
        import_tracking(db.conn, export([rows.application("adzuna:9", "interview")]),
                        export([]))
        assert [(r["job_key"], r["status"]) for r in _rows(db.conn, "applications")] == [
            ("adzuna:9", "interview")
        ]
        assert _rows(db.conn, "decisions") == []


@pytest.mark.parametrize("raw", [
    "not json",
    "{}",
    "[]",
    '[{"results": [], "success": true}, {"results": [], "success": true}]',
    '[{"results": [], "success": false}]',
    '[{"success": true}]',
    '[{"results": [1], "success": true}]',
])
def test_a_malformed_export_writes_nothing_and_keeps_the_previous_mirror(export, rows, raw):
    with Database(path=":memory:") as db:
        import_tracking(db.conn, export([rows.application(KEY)]), export([]))
        with pytest.raises(MirrorFormatError):
            import_tracking(db.conn, export(None, raw=raw), export([]))
        with pytest.raises(MirrorFormatError):
            import_tracking(db.conn, export([]), export(None, raw=raw))
        assert [r["job_key"] for r in _rows(db.conn, "applications")] == [KEY]


def test_read_export_missing_file_is_a_format_error(tmp_path):
    with pytest.raises(MirrorFormatError, match="unreadable export"):
        read_export(tmp_path / "missing.json")


def test_cli_prints_counts_only_and_never_a_note_or_url(
    tmp_path, monkeypatch, export, rows, capsys, caplog
):
    from job_match.cli import _cmd_tracking_import

    data = tmp_path / "data"
    data.mkdir()
    with Database(path=str(data / "jobs.sqlite")):
        pass
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(data))
    apps = export([rows.application(KEY, note=rows.note, cv_url=rows.url),
                   rows.application(KEY.replace("123", "999"), status="bogus", note=rows.note)])
    decs = export([rows.decision(1, KEY)])
    caplog.set_level(logging.DEBUG)
    _cmd_tracking_import(argparse.Namespace(applications=str(apps), decisions=str(decs)))
    out = capsys.readouterr()
    assert "1 applications, 1 decisions, 0 skill overrides, 1 invalid rows skipped" in out.out
    everything = out.out + out.err + caplog.text
    assert "private-marker" not in everything
    assert "private-cv-marker" not in everything
    with Database(path=str(data / "jobs.sqlite")) as db:
        assert ApplicationRepository(db.conn).count() == (1, 1)


def test_cli_rejects_a_malformed_export_and_exits_1(
    tmp_path, monkeypatch, export, rows, capsys
):
    from job_match.cli import _cmd_tracking_import

    data = tmp_path / "data"
    data.mkdir()
    with Database(path=str(data / "jobs.sqlite")):
        pass
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(data))
    bad = export(None, raw=f'{{"note": "{rows.note}"')
    with pytest.raises(SystemExit) as exc:
        _cmd_tracking_import(argparse.Namespace(applications=str(bad), decisions=str(bad)))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "previous mirror kept" in err
    assert "private-marker" not in err


# --- skill overrides -----------------------------------------------------------------

VOCAB = ("helm", "gitlab ci", "kafka")


def _override(skill, created_at="2026-10-21T08:00:00.000Z"):
    return {"skill": skill, "created_at": created_at}


def test_skill_overrides_are_mirrored_and_a_change_is_reported(export):
    with Database(path=":memory:") as db:
        repo = ApplicationRepository(db.conn)
        first = import_tracking(db.conn, export([]), export([]),
                                export([_override("helm"), _override("gitlab ci")]), VOCAB)
        assert (first.skill_overrides, first.overrides_changed) == (2, True)
        assert repo.list_skill_overrides() == ["gitlab ci", "helm"]
        same = import_tracking(db.conn, export([]), export([]),
                               export([_override("gitlab ci"), _override("helm")]), VOCAB)
        assert same.overrides_changed is False
        undone = import_tracking(db.conn, export([]), export([]),
                                 export([_override("helm")]), VOCAB)
        assert undone.overrides_changed is True
        assert repo.list_skill_overrides() == ["helm"]


@pytest.mark.parametrize("row", [
    _override("cobol"),             # well formed, not in the vocabulary
    _override("Helm"),              # not lowercase
    _override("helm; drop table"),  # not a skill name
    _override("helm", None),
    {"skill": "helm"},
    {**_override("helm"), "extra": 1},
])
def test_invalid_overrides_are_skipped_and_counted(export, row):
    with Database(path=":memory:") as db:
        result = import_tracking(db.conn, export([]), export([]),
                                 export([_override("kafka"), row]), VOCAB)
        assert (result.skill_overrides, result.skipped) == (1, 1)
        assert ApplicationRepository(db.conn).list_skill_overrides() == ["kafka"]


def test_without_an_overrides_export_the_mirror_is_kept(export):
    with Database(path=":memory:") as db:
        import_tracking(db.conn, export([]), export([]), export([_override("helm")]), VOCAB)
        result = import_tracking(db.conn, export([]), export([]))
        assert result.overrides_changed is False
        assert ApplicationRepository(db.conn).list_skill_overrides() == ["helm"]


def test_cli_writes_overrides_changed_for_the_workflow(tmp_path, monkeypatch, export, capsys):
    from job_match.cli import _cmd_tracking_import

    data = tmp_path / "data"
    data.mkdir()
    with Database(path=str(data / "jobs.sqlite")):
        pass
    gh_output = tmp_path / "github_output"
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(data))
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    args = argparse.Namespace(applications=str(export([])), decisions=str(export([])),
                              skill_overrides=str(export([_override("helm")])))
    _cmd_tracking_import(args)
    _cmd_tracking_import(args)
    assert gh_output.read_text(encoding="utf-8").splitlines() == [
        "overrides_changed=true", "overrides_changed=false"
    ]
    out = capsys.readouterr().out
    assert "1 skill overrides (changed)" in out
    assert "helm" not in out  # counts only: the CI log is public
