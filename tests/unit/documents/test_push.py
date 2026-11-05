"""`job-match cv validate` / `cv push`: the wrangler command, the temp file hygiene and the
counts-only output. No wrangler is ever run: the runner is a double."""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from job_match.cli import main
from job_match.documents.push import BUCKET, PushError, private_dir, push_objects


def test_push_uploads_each_object_from_a_temp_file_then_deletes_it():
    seen = []

    def run(cmd, **kwargs):
        file = Path(cmd[cmd.index("--file") + 1])
        seen.append((cmd, file.read_text(encoding="utf-8"), kwargs))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    objects = {"master/cv_master.json": '{"a": 1}', "master/contact.json": "{}"}
    sizes = push_objects(objects, run=run)
    assert sizes == {"master/cv_master.json": 8, "master/contact.json": 2}
    assert len(seen) == 2
    cmd, text, kwargs = seen[0]
    assert cmd[:3] == ["npx", "--yes", "wrangler@4"]
    assert cmd[3:7] == ["r2", "object", "put", f"{BUCKET}/master/cv_master.json"]
    assert "--remote" in cmd and "--local" not in cmd
    assert cmd[cmd.index("--content-type") + 1] == "application/json"
    assert text == '{"a": 1}'
    assert kwargs["capture_output"] is True
    assert not Path(cmd[cmd.index("--file") + 1]).exists()  # the temp dir is gone


def test_push_local_targets_the_dev_r2_and_a_failure_names_only_the_status():
    def run(cmd, **kwargs):
        assert "--local" in cmd
        return subprocess.CompletedProcess(cmd, 3, "the object body", "boom")

    with pytest.raises(PushError, match=r"exit 3 \(boom\)$") as exc:
        push_objects({"master/contact.json": "{}"}, local=True, run=run)
    assert "body" not in str(exc.value)  # stderr is the reason, stdout could be the object


def test_private_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("JOB_MATCH_PRIVATE_DIR", raising=False)
    assert private_dir() == Path("private")
    monkeypatch.setenv("JOB_MATCH_PRIVATE_DIR", str(tmp_path))
    assert private_dir() == tmp_path


@pytest.fixture
def project(tmp_path, monkeypatch, master_raw, contact_raw):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        "documents:\n  forbidden_phrases: [sans régression]\n", encoding="utf-8",
    )
    (cfg / "skill_vocabulary.yaml").write_text(
        "- kubernetes\n- terraform\n- python\n- aws\n- gcp\n", encoding="utf-8",
    )
    (cfg / "aliases.yaml").write_text("kubernetes: [k8s]\nci/cd: [cicd]\n", encoding="utf-8")
    priv = tmp_path / "private"
    priv.mkdir()
    dump = lambda d: yaml.safe_dump(d, allow_unicode=True)  # noqa: E731
    (priv / "cv_master.yaml").write_text(dump(master_raw), encoding="utf-8")
    (priv / "contact.yaml").write_text(dump(contact_raw), encoding="utf-8")
    monkeypatch.setenv("JOB_MATCH_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("JOB_MATCH_PRIVATE_DIR", str(priv))
    monkeypatch.delenv("PROFILE_YAML", raising=False)
    return tmp_path


def test_cv_validate_prints_counts_only(project, contact_raw, capsys):
    with patch("sys.argv", ["job-match", "cv", "validate"]):
        main()
    out = capsys.readouterr()
    assert out.out.strip() == "cv: 2 experiences, 1 projects, 4 bullets, 6 skills, 0 errors"
    for value in contact_raw.values():
        assert value not in out.out + out.err
    assert "Kubernetes" not in out.out


def test_cv_validate_exits_1_with_the_errors_on_stderr(project, capsys):
    path = project / "private" / "cv_master.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["experiences"][0]["bullets"][0]["text"] = "Livraisons sans régression."
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with patch("sys.argv", ["job-match", "cv", "validate"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "1 errors" in out.out
    assert "exp1.b1: forbidden phrase 'sans regression'" in out.err


def test_cv_push_validates_then_uploads_both_objects(project, contact_raw, capsys):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with (
        patch("job_match.documents.push.subprocess.run", run),
        patch("sys.argv", ["job-match", "cv", "push"]),
    ):
        main()
    out = capsys.readouterr().out
    keys = [c[6] for c in calls]
    assert keys == [f"{BUCKET}/master/cv_master.json", f"{BUCKET}/master/contact.json"]
    assert "master/cv_master.json:" in out and "-> R2 remote" in out
    for value in contact_raw.values():
        assert value not in out


def test_cv_without_subcommand_exits_1(capsys):
    with patch("sys.argv", ["job-match", "cv"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_cv_push_adds_apply_json_when_apply_yaml_exists_and_manuel_drops_the_range(project, capsys):
    (project / "private" / "apply.yaml").write_text(
        "remuneration:\n  mode: manuel\n  fourchette: {min: 41000, max: 47000}\n"
        "  reperes: [{zone: IDF, match: [paris], texte: '42-48 k'}]\npreavis: Aucun\n",
        encoding="utf-8",
    )
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, Path(cmd[cmd.index("--file") + 1]).read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with (
        patch("job_match.documents.push.subprocess.run", run),
        patch("sys.argv", ["job-match", "cv", "push"]),
    ):
        main()
    by_key = {c[6]: text for c, text in calls}
    apply_text = by_key[f"{BUCKET}/master/apply.json"]
    assert '"mode": "manuel"' in apply_text and '"fourchette": null' in apply_text
    assert "41000" not in apply_text  # no salary value leaves the machine in manuel
    assert "41000" not in capsys.readouterr().out


def test_cv_validate_refuses_a_broken_apply_yaml(project, capsys):
    (project / "private" / "apply.yaml").write_text("remuneration: {mode: fourchette}\n",
                                                    encoding="utf-8")
    with patch("sys.argv", ["job-match", "cv", "validate"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "fourchette needs remuneration.fourchette" in capsys.readouterr().err
