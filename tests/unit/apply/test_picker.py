"""`job-match apply` without a key: the numbered list (D1 double, a tiny jobs DB)."""
import json
import sqlite3
import subprocess
from unittest.mock import patch

import pytest

from job_match.apply import picker
from job_match.cli import main

GH = "https://boards.greenhouse.io/acme/jobs/1"
LEVER = "https://jobs.lever.co/beta/2"
SR = "https://jobs.smartrecruiters.com/Devoteam/3-cloud-ops"


def _app(key, updated, status="to_apply"):
    return {"job_key": key, "status": status, "updated_at": updated}


def test_build_keeps_open_supported_offers_oldest_first():
    apps = [_app("ats:lever:beta:2", "2026-11-03"), _app("ats:greenhouse:acme:1", "2026-11-01"),
            _app("ats:smartrecruiters:Devoteam:3", "2026-11-02"),
            _app("ats:greenhouse:acme:9", "2026-11-02"), _app("ft:X", "2026-11-01"),
            _app("ats:lever:beta:4", "2026-10-01", status="applied")]
    offers = {"ats:lever:beta:2": (LEVER, "SRE", "Beta", False),
              "ats:greenhouse:acme:1": (GH, "DevOps", "Acme", False),
              "ats:smartrecruiters:Devoteam:3": (SR, "Cloud Ops (H/F)", "Devoteam", False),
              "ats:greenhouse:acme:9": (GH, "Closed one", "Acme", True),
              "ats:lever:beta:4": (LEVER, "Applied", "Beta", False)}
    listing = picker.build(apps, offers)
    assert [c.key for c in listing.choices] == ["ats:greenhouse:acme:1", "ats:lever:beta:2"]
    assert listing.unknown == 1  # ft:X is not in the local DB
    text = picker.lines(listing)
    assert text[0] == " 1. DevOps · Acme (Greenhouse)"
    assert text[1] == " 2. SRE · Beta (Lever)"
    assert "absente(s) de la base locale" in text[2]
    assert picker.pick(listing, " 2 ").key == "ats:lever:beta:2"
    assert picker.pick(listing, "3") is None and picker.pick(listing, "x") is None
    assert picker.pick(listing, "0") is None


def _db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs (source_id TEXT, source_job_id TEXT, url TEXT, title TEXT,"
                 " company TEXT, location TEXT, closed_at TEXT)")
    conn.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, '', ?)", rows)
    conn.commit()
    conn.close()


def test_cli_without_a_key_lists_and_takes_the_typed_number(tmp_path, monkeypatch, capsys):
    _db(tmp_path / "jobs.sqlite", [("ats", "greenhouse:acme:1", GH, "DevOps", "Acme", None),
                                   ("ats", "lever:beta:2", LEVER, "SRE", "Beta", None)])
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(tmp_path))
    rows = [_app("ats:greenhouse:acme:1", "2026-11-01"), _app("ats:lever:beta:2", "2026-11-02")]
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps([{"results": rows}]), "")

    seen = {}

    def stop(args):  # what _cmd_apply does after the pick is covered elsewhere
        seen["key"] = args
        raise SystemExit(0)

    with (
        patch("job_match.apply.remote.subprocess.run", run),
        patch("sys.argv", ["job-match", "apply"]),
        patch("builtins.input", side_effect=["9", "2"]),
        patch("job_match.apply.config.load_apply", side_effect=stop),
        pytest.raises(SystemExit),
    ):
        main()
    out = capsys.readouterr().out
    assert " 1. DevOps · Acme (Greenhouse)" in out and " 2. SRE · Beta (Lever)" in out
    assert "Numéro inconnu." in out and "→ SRE · Beta" in out
    assert "status = 'to_apply'" in calls[0][-1]


def test_cli_without_a_key_and_nothing_supported_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(tmp_path))
    with (
        patch("job_match.apply.remote.subprocess.run",
              lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "[{\"results\": []}]", "")),
        patch("sys.argv", ["job-match", "apply"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 1
    assert "Aucune candidature" in capsys.readouterr().out
