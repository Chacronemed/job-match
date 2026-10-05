# PROGRESS

> Updated by Claude at the end of every session. Read this first when resuming.

## Current milestone
**Milestone 12: Lead ↔ Company ↔ Job + leads digest + daily wiring** — **DONE** (2026-10-05).
M9 manual GitHub setup still pending (see below).

## Done
- Project brief written (`docs/PROJECT_BRIEF.md`, `CLAUDE.md`)
- `docs/ARCHITECTURE.md` (brief §25, 14 sections).
- **Milestone 12** (2026-10-05):
  - Link Lead ↔ Company ↔ Job via the shared `companies.id` (both pipelines upsert through `normalize_company`).
    Computed at digest time, no stored flag (it would go stale as new events arrive).
  - `domain/models.py` — read models `CompanyFunding`, `LeadDetail`
  - `FundingEventRepository.latest_by_company(ids, since)` (publication date, else collection date);
    `LeadRepository.list_unnotified_details(jobs_since)` (high first, newest first, `open_jobs` = eligible canonical
    jobs of the company within `dedup_window_days`), `mark_notified`, `reset_notified_since`
  - `notification/assemble.py` — `build_digest(db, settings, now) -> DigestBatch` (data + job/lead ids to mark)
  - `notification/digest.py` — job cards show "Company funding: Raised 11 M€ series a (date)" linked to the article;
    new "Funding Leads" section (HIGH · hiring badge, amount/round, investors, hiring, open jobs, up to 3
    evidence sentences, article link), HTML-escaped; text version too. Subject adds ", N funding leads"
  - `job-match digest`: leads-only digests are sent; jobs and leads marked only after a successful send;
    `--resend-since` resets leads too. Notifier log no longer prints the recipient address
  - `config`: `funding.job_link_days: 180`
  - `daily.yml`: "Run funding pipeline" (`job-match funding run`, no secrets, `continue-on-error`) after the jobs
    run and before the WAL checkpoint and digest
  - 25 new tests (482 total) incl. a workflow step-order guard, ruff clean
- **Milestone 11** (2026-10-04):
  - `funding/extractor.py` — `extract_funding(title, text) -> FundingExtraction`: sentence split, funding sentence
    (strong noun phrase, or verb + accepted amount), guards (past perfect, VC fund close, revenue/valuation/total/debt
    clauses), amount+currency (FR/EN forms, written numbers), round, investors (explicit cues only), hiring phrase,
    explicit location, company heuristic (capitalised run before the verb). Evidence sentence per field.
  - `funding/leads.py` — `build_lead`: priority `high` iff hiring signal; reason `funding 10 M€ series a; hiring: …`
  - `migrations/0004_funding_extraction.sql` — `articles.processed_at`, `funding_events.evidence_json`, `leads.priority`,
    unique indexes `(article_id, company_id)` and `leads(funding_event_id)`
  - `FundingEventRepository` (upsert in place), `LeadRepository` (upsert keeps status/notified_at, `has_recent`),
    `ArticleRepository.mark_processed/list_unprocessed/list_collected_since`
  - `pipelines/funding.py` — `_process_article` shared by `run_funding` and new `reprocess_funding`; extraction
    runs in the same pass as the fetch, full text never stored; lead dedup per company (`funding.lead_dedup_days`)
  - CLI `job-match funding reprocess [--since YYYY-MM-DD] [--limit N] [--dry-run]`; summary adds funding / events /
    leads / by-source lines
  - `normalization/numbers.py` — `WORD_NUMBERS` shared with the experience parser
  - `docs/adr/0003-rule-based-funding-extraction.md`
  - 95 new tests (456 total, 50-case FR/EN extractor matrix incl. negatives), ruff clean
- **Milestone 10** (2026-10-04):
  - Live probe: `https://www.maddyness.com/feed/` (10 entries, served as text/html, parses fine) and
    `https://www.frenchweb.fr/feed` (100 entries). Trafilatura extracts both cleanly.
  - `adapters/funding/base.py` — `FundingSource` Protocol, `ArticleRef`, `FeedError`
  - `adapters/funding/rss.py` — `RssFundingSource` (feedparser; missing date → None; entry without link skipped;
    bozo + 0 entries → `FeedError`); `maddyness.py`, `frenchweb.py` set `name` + `FEED_URL`
  - `adapters/http.py` — `User-Agent` header (`DEFAULT_USER_AGENT`), `follow_redirects` param
  - `funding/article.py` — `ArticleFetcher` (throttle, trafilatura, None on any failure), `make_extract`
  - `normalization/url.py` — `normalize_article_url` (dedup key)
  - `migrations/0003_add_article_extract.sql`; `Article.extract/.id`; `RunSummary.feeds`
  - `persistence/repositories.py` — `ArticleRepository` (exists / save INSERT OR IGNORE / get_by_url / list_recent / count)
  - `config`: `FundingConfig(requests_per_second, extract_max_chars, sources)` under `settings.funding`
  - `pipelines/funding.py` — `run_funding`: feeds → normalize URL → skip seen (no refetch) → fetch+extract →
    store extract; per-feed and per-article error isolation; `--limit`, `--dry-run`
  - CLI: `job-match funding run [--limit N] [--dry-run]` (dry run = in-memory DB, prints feeds/found/new/skipped/errors)
  - `docs/adr/0002-article-ingestion-extract-only.md`
  - Fixtures: `rss_maddyness.xml`, `rss_invalid.xml`, `article_sample.html`. 46 new tests (361 total), ruff clean
- **Milestone 6b** (2026-10-01):
  - `src/job_match/pipelines/jobs.py` — `run_jobs()`: fetch → exp parse → fingerprint → gate → dedup → score → store; `--dry-run` skips writes; `--limit` caps iteration
  - `src/job_match/cli.py` — `job-match run [--limit N] [--dry-run]` with argparse, loads config, opens DB, prints RunSummary
  - `src/job_match/config/loader.py` — added `load_aliases(path)`
  - 13 new tests (229 total), ruff clean
  - `docs/ARCHITECTURE.md §13` — added M6b row, updated MVP line
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
- Complete the M9 manual GitHub setup and trigger the first daily run; review the first digest's leads and
  evidence sentences (precision check before M11b).
- **Milestone 13:** optional web application (only if needed).
- Manual setup still required (see session log 2026-10-02 M9 entry).

## Deferred
- **Milestone 7 (DEFERRED, experimental/optional):** job-match-scorer adapter. Off by default;
  not required for MVP. Skip until M9+ is stable.
- Score calibration: base_score 0, strong_threshold 60 may suit better — revisit after ~100 live runs.

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

## M9 — Manual GitHub setup (one-time)

### 1. Create the private data repo

On github.com, create a new **private** repository named `job-match-data` under your account
(`Chacronemed/job-match-data`). Initialize it with a README so it has a `main` branch.

### 2. Generate a deploy key

Run on your local machine (not in the project directory):
```
ssh-keygen -t ed25519 -f ~/.ssh/job_match_data_deploy -N "" -C "job-match-data deploy key"
```
This creates:
- `~/.ssh/job_match_data_deploy` — private key (keep secret)
- `~/.ssh/job_match_data_deploy.pub` — public key (safe to share)

### 3. Add the deploy key to `job-match-data`

Go to: `github.com/Chacronemed/job-match-data` → Settings → Deploy keys → Add deploy key.
- Title: `job-match daily workflow`
- Key: paste the contents of `~/.ssh/job_match_data_deploy.pub`
- **Check "Allow write access"**

### 4. Add secrets to `job-match` (the public repo)

Go to: `github.com/Chacronemed/job-match` → Settings → Secrets and variables → Actions → New repository secret.

Add each of the following:

| Secret name | Value |
|-------------|-------|
| `FT_CLIENT_ID` | Your France Travail API client ID |
| `FT_CLIENT_SECRET` | Your France Travail API client secret |
| `SMTP_HOST` | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | `465` (SSL) or `587` (STARTTLS) |
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASSWORD` | Gmail App Password (not your Google password) |
| `DIGEST_TO` | Email address to send the digest to |
| `PROFILE_YAML` | `base64 -w0 config/profile.yaml` — run this locally and paste the output |
| `DATA_REPO_DEPLOY_KEY` | Contents of `~/.ssh/job_match_data_deploy` (the private key, full including header/footer lines) |

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords → create one named "job-match".

### 5. First run

Trigger manually: `github.com/Chacronemed/job-match` → Actions → "Daily run" → Run workflow.
Watch the logs — they show only aggregate counts (fetched/eligible/strong), never personal data.

---

## Open decisions
- **M11b: roundup articles:** one event per strict deal line (`^- <Company> lève|boucle|raises <explicit amount>`),
  only after M11 precision is validated on real data.
- Exact France Travail search parameters (ROME codes, departments), to settle in M2
- Numeric thresholds (strong match, divergence, fuzzy T1/T2), to calibrate in M4 and M6 on real data
- Score calibration (after first real run): scale is compressed (50–70 on samples). Options: normalize score = earned/max possible points, base_score 0, strong_threshold 60, more negative skills. Calibrate on ~50 real France Travail jobs.
- ~~**M9 — WAL flush before data-repo push:**~~ **Resolved in M9.** `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM` run in daily.yml before DB push. `*.sqlite-wal` and `*.sqlite-shm` added to `.gitignore`.

## Known issues
- Job ↔ funding matching is exact on the normalized company name. FT employer names that differ beyond case,
  accents and legal suffixes (e.g. a holding name) will not match. Fuzzy company matching is not done.
- Cross-source funding dedup is per company via the 30-day lead window only: the same raise covered by Maddyness
  and FrenchWeb yields two events and one lead.
- Funding extractor: company heuristic precision is unmeasured until live data (`funding_no_company` counter).
  Lowercase brand names and "X et Y lèvent" are not recognised by design.
- `funding reprocess` retries articles whose fetch fails on every run (`processed_at` stays NULL) while the
  URL is in the DB. Acceptable for a manual command.
- Maddyness RSS has full `content:encoded` in the feed; we ignore it and fetch the page for a single code path.
  Revisit if article fetches become a cost.
- Funding dry run uses an in-memory DB (same convention as `job-match run --dry-run`), so every article counts as new.
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
- 2026-10-01: M6b complete. `pipelines/jobs.py`, CLI `job-match run`, `load_aliases`, 13 new tests (229 total).
- 2026-10-02: Post-M6b fixes. FT adapter: per-keyword queries, throttle (3 req/s), api_calls counter.
  Seniority keyword gate (`infer_seniority_min`). `rejected_jobs` unique-count invariant. 261 tests.
  Live run (--limit 50 --dry-run): 3 strong (ALENTA 87, EKIMETRICS 77, Nextep HR 72).
- 2026-10-02: M8 complete. Email digest: `notification/digest.py` (HTML + plain-text, HTML-escaped),
  `notification/email_notifier.py` (SMTP_SSL/STARTTLS, Gmail app password), `notification/service.py`
  (NotificationService Protocol). `job-match digest [--dry-run]` CLI. `list_unnotified`/`mark_notified`
  added to `JobRepository`. 285 tests passing.
- 2026-10-02: M9 complete. `.github/workflows/ci.yml` (push/PR: lint + test).
  `.github/workflows/daily.yml` (cron 07:00 UTC + workflow_dispatch; restore profile + DB from secrets,
  run pipeline, WAL checkpoint + VACUUM, send digest, push DB to private repo; digest is continue-on-error;
  push gated on wal.outcome == success). `docs/adr/0001-sqlite-persistence-private-data-repo.md`.
  `.gitignore` updated with `*.sqlite-wal`, `*.sqlite-shm`. Ruff clean, 285 tests.
  Manual GitHub setup required — see instructions below.
- 2026-10-02: Post-M6b fixes. FT adapter: one request per (keyword × dept), throttle (3 req/s),
  api_calls in RunSummary. Seniority keyword rule (`infer_seniority_min`, configurable in settings.yaml).
  Gate: explicit year always wins over seniority keyword. RunSummary: `rejected_jobs` = unique jobs count.
  CLI: prints loaded profile + experience_years, reason breakdown labeled "may sum > jobs".
  `scripts/diagnose.py` added. 261 tests passing.
  Live run (--limit 50 --dry-run): 50 fetched, 44 rejected, 3 eligible, 3 strong.
  Strong matches: ALENTA 87 (eligible because description says "au moins 2 ans", overrides seniority keywords),
  EKIMETRICS 77, Nextep HR 72.
- 2026-10-04: M10 complete. RSS ingestion: Maddyness + FrenchWeb adapters, `ArticleFetcher`, URL dedup,
  migration 0003, `job-match funding run`, ADR 0002. 361 tests passing.
- 2026-10-04: M11 complete. Rule-based funding extractor with evidence, FundingEvent/Company/Lead, lead dedup,
  migration 0004, `job-match funding reprocess`, ADR 0003. 456 tests passing. One event per article (M11b deferred).
- 2026-10-05: Test added: "InBolt"/"Inbolt" share one company and one lead.
- 2026-10-05: M12 complete. Lead ↔ Company ↔ Job link at digest time, Funding Leads digest section, leads
  marked after send, funding run in `daily.yml`. 482 tests passing.
