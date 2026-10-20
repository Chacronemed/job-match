"""The data-repo snapshot: gzip/gunzip, rotation, size guard, one orphan commit per push.

Runs real git against a bare repository in tmp_path; nothing leaves the machine.
"""
import gzip
import os
import subprocess
from datetime import UTC, datetime

import pytest

from job_match.persistence import snapshot
from job_match.persistence.snapshot import (
    CURRENT,
    LEGACY,
    PREVIOUS,
    SnapshotTooLarge,
    compress,
    main,
    publish,
    restore,
)

_DAY1 = datetime(2026, 10, 20, 7, tzinfo=UTC)
_DAY2 = datetime(2026, 10, 21, 7, tzinfo=UTC)


def _git(cwd, *args) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A bare 'job-match-data' and a function that clones it fresh, like each CI run."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))  # no user hooks, signing or identity
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(bare))
    runs = iter(range(100))

    def clone():
        work = tmp_path / f"run{next(runs)}"
        work.mkdir()
        _git(work, "clone", "--quiet", "--depth=1", str(bare), "data-repo")
        return work / "data-repo"

    clone.bare = bare
    return clone


def _db(path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _commits(bare) -> int:
    return int(_git(bare, "rev-list", "--count", "main"))


def _files(bare) -> set[str]:
    return set(_git(bare, "ls-tree", "--name-only", "main").splitlines())


def _gunzip(bare, name) -> bytes:
    blob = subprocess.run(["git", "show", f"main:{name}"], cwd=bare, check=True,
                          capture_output=True).stdout
    return gzip.decompress(blob)


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

def test_restore_gunzips_the_current_file(tmp_path):
    repo = tmp_path / "data-repo"
    repo.mkdir()
    compress(_db(tmp_path / "src.sqlite", b"SQLite v2"), repo / CURRENT)
    db = tmp_path / "data" / "jobs.sqlite"
    assert "jobs.sqlite.gz" in restore(repo, db)
    assert db.read_bytes() == b"SQLite v2"


def test_restore_falls_back_to_the_legacy_plain_file(tmp_path):
    repo = tmp_path / "data-repo"
    _db(repo / LEGACY, b"plain")
    db = tmp_path / "data" / "jobs.sqlite"
    assert "legacy" in restore(repo, db)
    assert db.read_bytes() == b"plain"


def test_restore_with_no_file_starts_fresh(tmp_path):
    repo = tmp_path / "data-repo"
    repo.mkdir()
    db = tmp_path / "data" / "jobs.sqlite"
    assert "starting fresh" in restore(repo, db)
    assert not db.exists()
    assert db.parent.is_dir()


def test_compress_is_deterministic(tmp_path):
    src = _db(tmp_path / "a.sqlite", b"x" * 10_000)
    compress(src, tmp_path / "1.gz")
    compress(src, tmp_path / "2.gz")
    assert (tmp_path / "1.gz").read_bytes() == (tmp_path / "2.gz").read_bytes()


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def test_publish_round_trip_and_history_stays_one_commit(remote, tmp_path):
    publish(_db(tmp_path / "d1.sqlite", b"day one"), remote(), now=_DAY1)
    assert _commits(remote.bare) == 1
    assert _files(remote.bare) == {CURRENT}

    publish(_db(tmp_path / "d2.sqlite", b"day two"), remote(), now=_DAY2)
    assert _commits(remote.bare) == 1  # force-pushed orphan, not a second commit
    assert _files(remote.bare) == {CURRENT, PREVIOUS}
    assert _gunzip(remote.bare, CURRENT) == b"day two"
    assert _gunzip(remote.bare, PREVIOUS) == b"day one"
    assert "2026-10-21" in _git(remote.bare, "log", "-1", "--format=%s", "main")

    # restore reads back exactly what was published
    db = tmp_path / "restored" / "jobs.sqlite"
    restore(remote(), db)
    assert db.read_bytes() == b"day two"


def test_publish_twice_in_the_same_clone(remote, tmp_path):
    repo = remote()
    publish(_db(tmp_path / "d1.sqlite", b"one"), repo, now=_DAY1)
    publish(_db(tmp_path / "d2.sqlite", b"two"), repo, now=_DAY2)
    assert _commits(remote.bare) == 1
    assert _gunzip(remote.bare, PREVIOUS) == b"one"


def test_unchanged_db_pushes_nothing_and_keeps_the_backup(remote, tmp_path):
    publish(_db(tmp_path / "d1.sqlite", b"one"), remote(), now=_DAY1)
    publish(_db(tmp_path / "d2.sqlite", b"two"), remote(), now=_DAY2)
    head = _git(remote.bare, "rev-parse", "main")
    msg = publish(_db(tmp_path / "d3.sqlite", b"two"), remote(), now=_DAY2)
    assert "unchanged" in msg
    assert _git(remote.bare, "rev-parse", "main") == head
    assert _gunzip(remote.bare, PREVIOUS) == b"one"


def test_first_gzip_run_migrates_the_legacy_file(remote, tmp_path):
    # Today's data repo: a plain jobs.sqlite with a commit history and a README.
    seed = remote()
    (seed / LEGACY).write_bytes(b"legacy db")
    (seed / "README.md").write_text("data\n")
    for i in range(3):
        (seed / LEGACY).write_bytes(b"legacy db" + bytes([i]))
        _git(seed, "add", ".")
        _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"c{i}")
    _git(seed, "push", "--quiet", "origin", "HEAD:main")
    assert _commits(remote.bare) == 3

    repo = remote()
    db = tmp_path / "data" / "jobs.sqlite"
    restore(repo, db)
    db.write_bytes(db.read_bytes() + b" + today")
    publish(db, repo, now=_DAY1)

    assert _commits(remote.bare) == 1
    assert _files(remote.bare) == {CURRENT, PREVIOUS, "README.md"}  # plain file gone
    assert _gunzip(remote.bare, PREVIOUS) == b"legacy db\x02"
    assert _gunzip(remote.bare, CURRENT) == b"legacy db\x02 + today"


def test_size_guard_fails_and_pushes_nothing(remote, tmp_path):
    publish(_db(tmp_path / "d1.sqlite", b"small"), remote(), now=_DAY1)
    head = _git(remote.bare, "rev-parse", "main")
    big = _db(tmp_path / "big.sqlite", os.urandom(100_000))  # random bytes do not compress
    repo = remote()
    with pytest.raises(SnapshotTooLarge, match="over the .* limit"):
        publish(big, repo, max_bytes=10_000, now=_DAY2)
    assert _git(remote.bare, "rev-parse", "main") == head
    assert not list(repo.parent.glob("*.staged"))


def test_cli_size_guard_exits_1_with_a_workflow_error(remote, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(snapshot, "MAX_GZ_BYTES", 10)
    repo = remote()
    db = _db(tmp_path / "data" / "jobs.sqlite", b"more than ten bytes once compressed")
    assert main(["publish", "--repo", str(repo), "--db", str(db)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("::error::jobs.sqlite.gz is")
    assert "Nothing was pushed" in out


def test_the_limit_leaves_room_under_githubs_100_mb():
    assert snapshot.MAX_GZ_BYTES == 90 * 1024 * 1024


def test_cli_restore(tmp_path, capsys):
    repo = tmp_path / "data-repo"
    repo.mkdir()
    assert main(["restore", "--repo", str(repo), "--db", str(tmp_path / "d" / "j.sqlite")]) == 0
    assert "starting fresh" in capsys.readouterr().out
