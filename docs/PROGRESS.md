# PROGRESS

> Updated by Claude at the end of every session. Read this first when resuming.

## Current milestone
Milestone 6: Fingerprint + deduplication: **DONE**. Waiting for "start Milestone 6b".

## Done
- Project brief written (`docs/PROJECT_BRIEF.md`, `CLAUDE.md`)
- `docs/ARCHITECTURE.md` (brief §25, 14 sections).
- **Milestone 6** (2026-10-01):
  - `src/job_match/normalization/` — `text.py`, `company.py`, `title.py`, `location.py`, `url.py`
    (NFKD folding, dotted-acronym collapse, legal-suffix strip, H/F noise, tracking-param strip)
  - `src/job_match/dedup/fingerprint.py` — `compute_fingerprint`: sha256 of normalized company|title|location|contract|desc[:500]
  - `src/job_match/dedup/engine.py` — `DedupEngine`: exact fingerprint check, then RapidFuzz fuzzy
    blocking on (company_normalized, contract_type); thresholds from Settings
  - `migrations/0002_add_company_normalized.sql` — adds `company_normalized` column + index to `jobs`
  - `repositories.py` updated: `company_normalized` stored on save; `get_by_fingerprint`,
    `list_by_block` added to `JobRepository`; new `JobDuplicateRepository` (save_link, get_canonical_id, list_duplicates_of)
  - 60 new tests (211 total), ruff clean
- **Milestone 5** (2026-10-01):
  - `migrations/0001_init.sql` — full schema: `sources`, `raw_payloads`, `companies`, `jobs`, `job_duplicates`, `job_scores`, `articles`, `funding_events`, `leads`, `runs`
  - `src/job_match/persistence/db.py` — `Database`: WAL mode, foreign keys ON, numbered migration runner (`schema_version` bootstrap, idempotent)
  - `src/job_match/persistence/repositories.py` — `CompanyRepository` (upsert by normalized_name), `RawPayloadRepository`, `JobRepository` (upsert by source+source_job_id, `get`, `list_eligible`, `list_rejected`), `JobScoreRepository`, `RunRepository`; full serialisation/deserialisation of `ScoringBreakdown` and `ExperienceRequirement`
  - 24 new tests (151 total), ruff clean
- **Milestone 4** (2026-10-01):
  - `src/job_match/scoring/base.py` — `Scorer` Protocol (`runtime_checkable`)
  - `src/job_match/scoring/native.py` — `NativeRuleScorer(aliases)`: whole-word/phrase matching via `(?<!\w)…(?!\w)`, alias expansion, title-keyword bonus, score clamped 0–100, full `ScoreResult` with `explanations`
  - `src/job_match/scoring/engine.py` — `ScoringEngine`: runs scorers safely (exception → `available=False`), native is primary rank, divergence + `needs_review` computed when ≥2 scorers
  - `src/job_match/config/schema.py` + `config/settings.yaml` — added `base_score=50`, `title_bonus=10` to `Settings`; `loader.py` updated accordingly
  - 26 new tests (127 total), ruff clean
- **Milestone 3** (2026-10-01):
  - `src/job_match/experience/parser.py` — `parse(text) → ExperienceRequirement`; regex table (FR+EN), written-number map, smallest-minimum rule, false-positive guard (company founding year), ambiguous→UNKNOWN, nothing→NOT_MENTIONED
  - `src/job_match/eligibility/gate.py` — `evaluate(job, requirement, profile) → EligibilityResult`; hard gate: experience, contract, location; UNKNOWN/NOT_MENTIONED stay eligible; "remote" in location always passes
  - 55 new tests (101 total), ruff clean
  - Position-tracking prevents `_PLAIN_RE` from double-capturing numbers inside max phrases ("up to 2 years")
- **Milestone 2** (2026-10-01):
  - `src/job_match/adapters/http.py` — `HttpClient` with retry/backoff (429+Retry-After, 5xx, timeout)
  - `src/job_match/adapters/jobs/base.py` — `JobSource` Protocol, `RawItem` TypeAlias
  - `src/job_match/adapters/jobs/france_travail.py` — `FranceTravailSource`: OAuth2, pagination, `to_job`
  - 3 JSON fixtures, 20 new tests (46 total), ruff clean
  - Contract-type map in adapter; `workplace_type=UNKNOWN` (FT v2 has no clean field)
  - `experience=None` (parser is M3); `max_results` is constructor param for testability
- **Milestone 1** (2026-10-01):
  - `.gitattributes` (`* text=auto eol=lf`)
  - `.gitignore`, `.env.example`
  - `pyproject.toml` (hatchling, `src/` layout, Python 3.12, ruff + pytest config)
  - `config/profile.example.yaml` (fake DevOps profile), `config/aliases.yaml`, `config/settings.yaml`
  - `src/job_match/domain/models.py` — all enums (`StrEnum`) and dataclasses (`frozen=True, slots=True`)
  - `src/job_match/config/schema.py` — `Profile`, `Settings`, `ConfigError`
  - `src/job_match/config/loader.py` — `load_profile`, `load_profile_from_env`, `load_settings`
  - `src/job_match/cli.py` — stub entry point
  - 26 tests green, `ruff check .` clean

## Next step
- **Milestone 6b: Job pipeline + CLI.** `pipelines/jobs.py` (fetch → normalize → experience gate → dedup → score → store) + `job-match run` CLI command that prints the RunSummary. No email yet. Thin orchestration only — no new domain logic.

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
- Score calibration (after first real run): scale is compressed (50–70 on samples). Options: normalize score = earned/max possible points, base_score 0, strong_threshold 60, more negative skills. Calibrate on ~50 real France Travail jobs.
- **M9 — WAL flush before data-repo push:** run `PRAGMA wal_checkpoint(TRUNCATE)` and close the connection before committing the DB, so no data remains in the `-wal` file. Also ensure `*.sqlite-wal` and `*.sqlite-shm` are gitignored.

## Known issues
- job-match-scorer: English-only tokenizer (strips accents), no JSON output, young repo (2 commits)
- France Travail API credentials (`FT_CLIENT_ID`/`FT_CLIENT_SECRET`) are needed before M2 can run live. The tests
  use fixtures.

## Session log
- 2026-09-30: brief created. M0 architecture written, with user-requested changes: M1/M2 swapped, private data
  repo, example profile, JMS experimental.
- 2026-10-01: M1 complete. Project skeleton, domain model, config loader, 26 tests green.
- 2026-10-01: M2 complete. France Travail adapter: OAuth2, pagination, retry/backoff, 20 new tests (46 total).
- 2026-10-01: M3 complete. Experience parser + eligibility gate, 55 new tests (101 total).
- 2026-10-01: M4 complete. Native scoring engine: `NativeRuleScorer`, `ScoringEngine`, 26 new tests (127 total).
- 2026-10-01: M5 complete. SQLite persistence: migration runner, 5 repositories, 24 new tests (151 total).
- 2026-10-01: M6 complete. Normalization module, fingerprint, DedupEngine, migration 0002, 60 new tests (211 total).
