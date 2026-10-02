# ADR 0001 — SQLite persistence via a private data repository

**Date:** 2026-10-02  
**Status:** Accepted

---

## Context

The job-match repository is **public** on GitHub. The SQLite database contains personally relevant
data: eligible and rejected job listings mapped to a private candidate profile. This data must not
be readable by anyone with internet access.

GitHub Actions needs durable, versioned storage for the database across daily runs. Several
approaches were evaluated:

| Option | Verdict |
|--------|---------|
| Private data repo + deploy key | **Chosen** |
| Data branch in this repo | Rejected — repo is public, DB would be public |
| Actions artifacts | Rejected — readable by anyone with repo access, expire after 90 days |
| Actions cache | Rejected — evicted after 7 days, not guaranteed storage |
| Fine-grained PAT | Acceptable fallback — scoped to user and expires, deploy key does not |
| External hosted DB (Turso, Supabase, …) | Rejected — adds an external dependency, not justified for MVP |

The candidate profile (`config/profile.yaml`) is also private and must never be committed.

---

## Decision

1. **Private data repository** (`Chacronemed/job-match-data`) holds `jobs.sqlite`. It is pushed
   from the daily workflow using a deploy key.

2. **Deploy key** (`DATA_REPO_DEPLOY_KEY` secret, SSH Ed25519 key pair) grants write access to
   `job-match-data` only. It is stored as a GitHub Actions secret on the public repo.

3. **Profile secret** (`PROFILE_YAML`): the real `config/profile.yaml` is base64-encoded and
   stored as a secret. The workflow decodes it at run time into a gitignored path.

4. **WAL checkpoint and VACUUM** run before every push to ensure the DB file is self-contained
   (no `-wal` or `-shm` sidecar files committed) and compact.

5. **Push only when changed**: `git diff --cached --quiet` skips the push if the DB is identical,
   avoiding empty commits.

6. **Concurrency guard**: the daily workflow uses `concurrency: group: daily,
   cancel-in-progress: false` so only one writer runs at a time.

---

## Consequences

**Positive:**
- Personal data stays private.
- Every run is a restorable snapshot (git history of the data repo).
- No external service dependency.
- The public repo stays clean — no binary blobs, no personal data in any branch, cache or artifact.

**Negative / mitigations:**
- Binary commits grow the data repo over time.
  *Mitigation:* commit only when changed; periodically squash or replace with a gzipped `sqlite3 .dump`.
- One extra secret and a few extra workflow steps.
  *Mitigation:* deploy keys are set-and-forget; the steps are small and self-contained.
- If the data repo is accidentally made public, its history would expose job data.
  *Mitigation:* single private repo; access is via deploy key only; no profile or resume data in the DB.

---

## Related

- `docs/ARCHITECTURE.md §10` — Persistence, private data repo, WAL/VACUUM strategy.
- `.github/workflows/daily.yml` — the workflow that implements this ADR.
- `.gitignore` — `data/`, `*.sqlite`, `*.sqlite-wal`, `*.sqlite-shm`, `config/profile.yaml` all excluded.
