"""The SQLite file in the private data repo: restore it before a run, publish it after.

The data repo holds a single commit, force-pushed each run, with two files:
`jobs.sqlite.gz` (this run) and `jobs.prev.sqlite.gz` (the previous run, a one-day backup).
Git keeps a full copy of a binary per commit, so a daily commit history grows without bound;
an orphan commit keeps the repo at two compressed files. GitHub rejects files over 100 MB,
so publishing refuses a compressed file over `MAX_GZ_BYTES` and pushes nothing.

Usage (daily.yml):
    python -m job_match.persistence.snapshot restore --repo data-repo --db data/jobs.sqlite
    python -m job_match.persistence.snapshot publish --repo data-repo --db data/jobs.sqlite

The DB must be checkpointed and VACUUMed before `publish`. Only sizes are printed: the
workflow log of the public code repo is public.
"""

import argparse
import gzip
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

CURRENT = "jobs.sqlite.gz"
PREVIOUS = "jobs.prev.sqlite.gz"
LEGACY = "jobs.sqlite"  # uncompressed file, before the switch to gzip
MAX_GZ_BYTES = 90 * 1024 * 1024
BRANCH = "main"
_BOT = ("github-actions[bot]", "github-actions[bot]@users.noreply.github.com")


class SnapshotTooLarge(Exception):
    pass


def restore(repo: Path, db: Path) -> str:
    """Copy the DB out of the data repo; gzip first, the legacy plain file otherwise."""
    db.parent.mkdir(parents=True, exist_ok=True)
    if (repo / CURRENT).exists():
        with gzip.open(repo / CURRENT, "rb") as src, db.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        return f"Restored DB from {CURRENT}"
    if (repo / LEGACY).exists():
        shutil.copyfile(repo / LEGACY, db)
        return f"Restored DB from legacy {LEGACY}"
    return "No existing DB — starting fresh"


def compress(src: Path, dst: Path) -> int:
    """gzip with no name and mtime 0, so the same DB always gives the same bytes."""
    with src.open("rb") as f_in, dst.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f_out:
            shutil.copyfileobj(f_in, f_out)
    return dst.stat().st_size


def publish(
    db: Path, repo: Path, *, max_bytes: int = MAX_GZ_BYTES, now: datetime | None = None
) -> str:
    """Compress the DB, rotate the previous copy, force-push one orphan commit."""
    staged = repo.parent / f"{CURRENT}.staged"
    size = compress(db, staged)
    if size > max_bytes:
        staged.unlink()
        raise SnapshotTooLarge(
            f"{CURRENT} is {_mb(size)}, over the {_mb(max_bytes)} limit (GitHub rejects files"
            " over 100 MB). Nothing was pushed: lower raw_payloads.retention_days or prune"
            " the DB, then rerun."
        )

    current = repo / CURRENT
    if current.exists() and current.read_bytes() == staged.read_bytes():
        staged.unlink()
        return f"DB unchanged ({_mb(size)}) — nothing to push"

    # Yesterday's file becomes the backup; on the first gzip run it is the legacy file.
    if current.exists():
        shutil.move(current, repo / PREVIOUS)
    elif (repo / LEGACY).exists():
        compress(repo / LEGACY, repo / PREVIOUS)
    (repo / LEGACY).unlink(missing_ok=True)
    shutil.move(staged, current)

    # A parentless commit built from an empty index: no branch to switch, works on an empty
    # repo, and the force-push replaces the whole history with this one commit.
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    files = [f for f in (CURRENT, PREVIOUS, "README.md") if (repo / f).exists()]
    _git(repo, "read-tree", "--empty")
    _git(repo, "add", *files)
    tree = _git(repo, "write-tree")
    commit = _git(repo, "-c", f"user.name={_BOT[0]}", "-c", f"user.email={_BOT[1]}",
                  "commit-tree", tree, "-m", f"chore: daily snapshot {stamp}")
    _git(repo, "update-ref", "HEAD", commit)
    _git(repo, "push", "--quiet", "--force", "origin", f"{commit}:refs/heads/{BRANCH}")
    return f"Pushed {CURRENT} ({_mb(size)}), previous kept as {PREVIOUS}"


def _git(repo: Path, *args: str) -> str:
    # stderr is inherited, so a failed push says why in the workflow log
    out = subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, text=True)
    return out.stdout.strip()


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m job_match.persistence.snapshot")
    parser.add_argument("command", choices=["restore", "publish"])
    parser.add_argument("--repo", type=Path, required=True, help="data repo checkout")
    parser.add_argument("--db", type=Path, required=True, help="local SQLite file")
    args = parser.parse_args(argv)
    try:
        if args.command == "restore":
            print(restore(args.repo, args.db))
        else:
            print(publish(args.db, args.repo, max_bytes=MAX_GZ_BYTES))
    except SnapshotTooLarge as exc:
        print(f"::error::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
