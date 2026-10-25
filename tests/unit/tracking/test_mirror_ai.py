"""The D1 AI rerank tables -> jobs DB mirror: validated rows only, all or nothing."""
import json

import pytest

from job_match.persistence.db import Database
from job_match.tracking.mirror import MirrorFormatError, import_ai

KEY = "france_travail:123ABCD"
HASH = "0" * 64


def verdict(id_=1, **fields):
    row = {"id": id_, "job_key": KEY, "hash": HASH, "provider": "anthropic",
           "model": "claude-haiku-5-5", "prompt_version": "1", "score": 84, "level": "fort",
           "reasons": json.dumps(["Kubernetes cité."]), "red_flags": "[]",
           "created_at": "2026-10-25T07:30:00.000Z"}
    row.update(fields)
    return row


def usage(**fields):
    row = {"day": "2026-10-25", "provider": "anthropic", "calls": 3, "tokens_in": 6000,
           "tokens_out": 240}
    row.update(fields)
    return row


def disagreement(id_=1, **fields):
    row = {"id": id_, "job_key": KEY, "hash": HASH, "python_score": 85,
           "python_section": "strong", "ai_score": 20, "ai_level": "hors_sujet",
           "kind": "off_topic_strong", "created_at": "2026-10-25T07:30:00.000Z"}
    row.update(fields)
    return row


def ai_run(id_=1, **fields):
    row = {"id": id_, "started_at": "2026-10-25T07:30:00.000Z",
           "finished_at": "2026-10-25T07:31:00.000Z", "outcome": "ok", "http_status": None,
           "provider": "anthropic", "counters": json.dumps({"scored": 3, "cached": 10})}
    row.update(fields)
    return row


def _rows(conn, table):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


def test_valid_exports_replace_the_three_tables(export):
    with Database(path=":memory:") as db:
        db.conn.execute(
            "INSERT INTO ai_usage VALUES ('2026-01-01', 'workers_ai', 9, 9, 9)"
        )
        result = import_ai(db.conn, export([verdict(), verdict(2, hash="1" * 64, score=40,
                                                               level="tenter")]),
                           export([usage()]), export([disagreement()]))
        assert (result.verdicts, result.usage, result.disagreements, result.skipped) == (2, 1, 1, 0)
        assert [r["score"] for r in _rows(db.conn, "ai_verdicts")] == [84, 40]
        assert _rows(db.conn, "ai_usage") == [usage()]
        assert _rows(db.conn, "disagreements")[0]["kind"] == "off_topic_strong"


def test_runs_travel_with_the_other_tables(export):
    with Database(path=":memory:") as db:
        result = import_ai(db.conn, export([]), export([]), export([]),
                           export([ai_run(), ai_run(2, outcome="stopped", http_status=404)]))
        assert (result.runs, result.skipped) == (2, 0)
        assert [r["http_status"] for r in _rows(db.conn, "ai_runs")] == [None, 404]
        import_ai(db.conn, export([]), export([]), export([]))  # no runs file: emptied too
        assert _rows(db.conn, "ai_runs") == []


@pytest.mark.parametrize("change", [
    {"outcome": "crashed"},
    {"http_status": 42},
    {"http_status": "404"},
    {"provider": "gemini"},
    {"counters": "not json"},
    {"counters": json.dumps({"scored": -1})},
    {"counters": json.dumps([1])},
    {"started_at": None},
    {"id": 0},
])
def test_invalid_runs_are_skipped(export, change):
    with Database(path=":memory:") as db:
        result = import_ai(db.conn, export([]), export([]), export([]),
                           export([{**ai_run(), **change}]))
        assert (result.runs, result.skipped) == (0, 1)


@pytest.mark.parametrize("change", [
    {"score": 101},
    {"score": -1},
    {"score": True},
    {"level": "great"},
    {"provider": "openai"},
    {"hash": "xyz"},
    {"job_key": "no key"},
    {"reasons": "not json"},
    {"reasons": json.dumps(["a", "b", "c", "d"])},
    {"reasons": json.dumps(["x" * 161])},
    {"red_flags": json.dumps([1])},
    {"prompt_version": ""},
    {"extra": 1},
])
def test_invalid_verdicts_are_skipped_and_counted(export, change):
    with Database(path=":memory:") as db:
        result = import_ai(db.conn, export([verdict(), {**verdict(2), **change}]),
                           export([]), export([]))
        assert (result.verdicts, result.skipped) == (1, 1)


@pytest.mark.parametrize("change", [
    {"day": "2026-13-01"},
    {"day": None},
    {"provider": "gemini"},
    {"calls": -1},
    {"tokens_in": "12"},
])
def test_invalid_usage_rows_are_skipped(export, change):
    with Database(path=":memory:") as db:
        result = import_ai(db.conn, export([]), export([{**usage(), **change}]), export([]))
        assert (result.usage, result.skipped) == (0, 1)


@pytest.mark.parametrize("change", [
    {"kind": "maybe"},
    {"ai_level": "fort!"},
    {"python_score": 200},
    {"python_section": "x" * 17},
    {"id": 0},
])
def test_invalid_disagreements_are_skipped(export, change):
    with Database(path=":memory:") as db:
        result = import_ai(db.conn, export([]), export([]),
                           export([{**disagreement(), **change}]))
        assert (result.disagreements, result.skipped) == (0, 1)


def test_a_malformed_export_keeps_the_previous_mirror(export, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a list"}', encoding="utf-8")
    with Database(path=":memory:") as db:
        import_ai(db.conn, export([verdict()]), export([usage()]), export([]))
        with pytest.raises(MirrorFormatError):
            import_ai(db.conn, export([]), bad, export([]))
        assert len(_rows(db.conn, "ai_verdicts")) == 1
