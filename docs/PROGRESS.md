# PROGRESS

> Updated by Claude at the end of every session. Read this first when resuming.

## Current milestone
Milestone 0: Repository audit + architecture: **DONE**. Waiting for "start Milestone 1".

## Done
- Project brief written (`docs/PROJECT_BRIEF.md`, `CLAUDE.md`)
- `docs/ARCHITECTURE.md` (brief §25, 14 sections). It covers the external repos (job-match-scorer, career-ops), the
  directory layout, the Mermaid diagram, the domain model, the SQLite schema, adapter interfaces, experience gate,
  scoring, dedup, testing, roadmap and risks.

## Next step
- **Milestone 1: Normalized Job domain model + project skeleton.** It includes `pyproject.toml`, `.gitignore`,
  `.env.example`, `config/profile.example.yaml`, the config loader, dataclasses and enums, and tests.
- Milestone 2 is the France Travail adapter. The order was swapped relative to the brief §22, and ARCHITECTURE §13
  is authoritative.

## Decisions (resolved in M0, see ARCHITECTURE)
- **The repo is PUBLIC.** Nothing personal is committed or logged. Logs contain aggregate counts only.
- SQLite persistence: a **separate private repo** (`job-match-data`) pushed by the workflow with a deploy key
  (`DATA_REPO_DEPLOY_KEY`). The ADR is to be written in M9.
- `config/profile.example.yaml` is committed. The real `config/profile.yaml` (and `config/resume.md`) is
  gitignored and comes from the `PROFILE_YAML` secret (base64) in CI.
- Scoring: the native scorer is the only one required for the MVP and is the primary rank. There is no averaging.
  JMS is a second opinion, and a divergence at or above the threshold sets `needs_review`.
- job-match-scorer (M7) is **EXPERIMENTAL / optional** and disabled by default.
- career-ops is manual only. The optional exporter writes to `jds/` and the `data/pipeline.md` Pending section.

## Open decisions
- Exact France Travail search parameters (ROME codes, departments), to settle in M2
- Numeric thresholds (strong match, divergence, fuzzy T1/T2), to calibrate in M4 and M6 on real data

## Known issues
- job-match-scorer: English-only tokenizer (strips accents), no JSON output, young repo (2 commits)
- France Travail API credentials (`FT_CLIENT_ID`/`FT_CLIENT_SECRET`) are needed before M2 can run live. The tests
  use fixtures.
- There are no tests yet because there is no code yet, so `pytest` was not run in M0.

## Session log
- 2026-09-30: brief created. M0 architecture written, with user-requested changes: M1/M2 swapped, private data
  repo, example profile, JMS experimental.
