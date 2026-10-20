# ADR 0011 — Compressed, single-commit DB snapshot in the data repo

**Status:** accepted (2026-10-20). Amends ADR 0001 (how the file is stored, not where).

## Context

`daily.yml` committed the plain `jobs.sqlite` to the private `job-match-data` repo after each
run. Git keeps a full copy of a binary per commit, so the repo grows by roughly one DB per
day. On 2026-10-20 the file was 27.3 MB, `main` had 26 commits, and the packed repo was 9.2 MB.
Storing raw payloads adds about 0.8 MB/day up to the 60-day retention, so the file heads
toward ~50 MB+. GitHub rejects any file over 100 MB.

## Decision

`job_match.persistence.snapshot`, called by two workflow steps:

- **restore**: gunzip `jobs.sqlite.gz` into `data/`. It falls back to the legacy plain
  `jobs.sqlite` once, on the first run after the switch.
- **publish**, after the WAL checkpoint and VACUUM:
  1. gzip the DB deterministically (no name, mtime 0). If the result is byte-identical to
     the stored file, push nothing.
  2. Otherwise move the current file to `jobs.prev.sqlite.gz`, a one-run backup, and build
     one parentless commit (`read-tree --empty` / `write-tree` / `commit-tree`).
  3. Force-push that commit to `main`.
  4. If the compressed file is over 90 MB, fail the step with `::error::` and push
     nothing.

The repo therefore always holds one commit and two compressed files. Measured on the local DB
(11.7 MB after VACUUM), gzip is 4.5× smaller (2.6 MB) and takes 0.4 s.

The logic is Python, not inline shell, so gzip/gunzip, rotation, the guard and the
force-push are tested against a real bare git repository in `tmp_path`.

## Alternatives

- **Git LFS:** history is still kept, and the bandwidth and storage quotas are small.
- **Actions artifacts or cache:** they expire, so they are not a store of record.
- **External storage (S3/R2):** a new secret and a new service for a single file.
- **Keep the history and rewrite it now and then:** that is manual work that will be forgotten.

## Consequences

- No history beyond the previous run. Point-in-time recovery older than one run is gone.
  That is acceptable for a daily cache of public offers.
- The deploy key must be allowed to force-push. Branch protection on `main` would block it.
- Objects from the old history stay in GitHub's storage until GitHub garbage-collects them,
  so a one-time cleanup is needed to shrink the repo right away (see PROGRESS).
