"""`job-match apply --sent` and the D1 / R2 reads through wrangler (a double, never run), and
the local rendering by scripts/apply-render.mjs (real Node, synthetic master)."""

import json
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from job_match.apply import remote, session
from job_match.cli import main

KEY = "ats:greenhouse:acme:123"


def fake(stdout="[]", code=0, calls=None, files=None):
    def run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        if files and "--file" in cmd:
            Path(cmd[cmd.index("--file") + 1]).write_text(files, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, code, stdout, "boom" if code else "")

    return run


def test_latest_ready_version_reads_d1():
    calls = []
    out = json.dumps([{"results": [{"v": 3}], "success": True}])
    assert remote.latest_ready_version(KEY, run=fake(out, calls=calls)) == 3
    cmd = calls[0]
    assert cmd[3:8] == ["d1", "execute", "job-match", "--remote", "--json"]
    assert f"job_key = '{KEY}' AND status = 'ready'" in cmd[-1]
    assert (
        remote.latest_ready_version(KEY, run=fake(json.dumps([{"results": [{"v": None}]}]))) is None
    )


def test_a_key_that_could_break_the_sql_never_reaches_wrangler():
    calls = []
    with pytest.raises(remote.RemoteError, match="invalid job key"):
        remote.latest_ready_version("ats:x'; DROP TABLE applications; --", run=fake(calls=calls))
    with pytest.raises(remote.RemoteError):
        remote.mark_sent(
            "a b",
            date(2026, 11, 5),
            date(2026, 11, 12),
            1,
            "2026-11-05T10:00:00.000Z",
            run=fake(calls=calls),
        )
    assert calls == []


def test_fetch_content_reads_the_version_object():
    calls = []
    doc = remote.fetch_content(KEY, 2, run=fake(calls=calls, files='{"language": "fr"}'))
    assert doc == {"language": "fr"}
    assert calls[0][3:7] == ["r2", "object", "get", f"job-match-docs/docs/{KEY}/v2/content.json"]
    assert remote.fetch_content(KEY, 2, run=fake(code=1)) is None


def test_mark_sent_keeps_an_earlier_date_and_records_the_version():
    calls = []
    remote.mark_sent(
        KEY,
        date(2026, 11, 5),
        date(2026, 11, 12),
        2,
        "2026-11-05T10:00:00.000Z",
        run=fake(json.dumps([{"results": []}]), calls=calls),
    )
    sql = calls[0][-1]
    assert f"VALUES ('{KEY}', 'applied', '2026-11-05', '2026-11-12'" in sql
    assert "COALESCE(applications.applied_at, excluded.applied_at)" in sql
    assert f"sent_documents_version = 2 WHERE job_key = '{KEY}'" in sql


def test_cli_sent_prints_dates_and_version(capsys):
    calls = []
    outputs = iter([json.dumps([{"results": [{"v": 4}]}]), json.dumps([{"results": []}])])

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, next(outputs), "")

    with (
        patch("job_match.apply.remote.subprocess.run", run),
        patch("sys.argv", ["job-match", "apply", KEY, "--sent", "--follow-up-days", "10"]),
    ):
        main()
    out = capsys.readouterr().out
    today = date.today()
    assert f"Envoyée le {today.isoformat()}" in out and "documents v4." in out
    assert "'applied'" in calls[1][-1]


def test_cli_rejects_a_bad_key(capsys):
    with patch("sys.argv", ["job-match", "apply", "not a key"]), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


MASTER = {
    "headline": "Ingénieur DevOps",
    "target": "CDI",
    "available_from": "2026-01-01",
    "mobility": "Mobile en France",
    "experiences": [
        {
            "id": "exp1",
            "employer": "Acme",
            "title": "DevOps",
            "start": "2025-01",
            "end": None,
            "location": "Paris",
            "bullets": [{"id": "exp1.b1", "text": "Kubernetes.", "tools": []}],
        }
    ],
    "projects": [],
    "skills": [],
    "skill_groups": [],
    "education": [],
    "certifications": [],
    "languages": [],
    "extras": [],
}
CONTACT = {
    "first_name": "Jean",
    "last_name": "Test",
    "title": "DevOps",
    "email": "j@example.com",
    "phone": "",
    "linkedin": "",
    "github": "",
    "location": "Paris",
}
CONTENT = {
    "language": "fr",
    "profile": "Ingénieur DevOps. Disponible immédiatement.",
    "offer": {"key": KEY, "title": "DevOps", "company": "Initech", "location": "Paris"},
    "cv": {
        "experiences": [
            {
                "id": "exp1",
                "employer": "Acme",
                "title": "DevOps",
                "start": "2025-01",
                "end": None,
                "location": "Paris",
                "bullets": [{"id": "exp1.b1", "text": "Kubernetes."}],
            }
        ],
        "projects": [],
    },
    "skill_groups": [],
    "headline_techs": [],
    "highlights": [],
    "letter": {"paragraphs": [{"sentences": [{"text": "Bonjour Initech.", "sources": []}]}]},
    "answers": {
        "motivation": {"sentences": [{"text": "J'aime ce poste.", "sources": []}]},
        "why_company": {"sentences": [{"text": "Initech me plaît.", "sources": []}]},
    },
}


def test_render_local_writes_both_pdfs_and_the_kit(tmp_path):
    if not shutil.which("node") or not Path("worker/node_modules/pdf-lib").exists():
        if os.environ.get("CI"):
            pytest.fail("Node and `npm ci --prefix worker` are required in CI")
        pytest.skip("Node or the Worker's npm dependencies are missing")
    apply = {
        "remuneration": {
            "mode": "manuel",
            "fourchette": None,
            "reperes": [{"zone": "IDF", "match": ["paris"], "texte": "42-48 k"}],
        },
        "preavis": "",
        "mobilite": "",
        "reponses_fixes": [],
    }
    paths = session.render_local(
        {"content": CONTENT, "master": MASTER, "contact": CONTACT, "apply": apply},
        tmp_path,
        "Paris",
    )
    assert Path(paths["cv"]).name == "CV_Jean_Test_Initech.pdf"
    assert Path(paths["cv"]).read_bytes()[:5] == b"%PDF-"
    assert Path(paths["letter"]).read_bytes()[:5] == b"%PDF-"
    assert not (tmp_path / "bundle.json").exists()  # the contact sheet is not left behind
    kit = json.loads(Path(paths["kit"]).read_text(encoding="utf-8"))
    by = {i["key"]: i for i in kit["items"]}
    assert by["motivation"]["text"] == "J'aime ce poste."
    assert by["availability"]["text"] == "Disponible immédiatement"
    assert by["salary"]["text"] is None and "IDF : 42-48 k" in by["salary"]["note"]
    assert "Bonjour Initech." in kit["letter_text"]
