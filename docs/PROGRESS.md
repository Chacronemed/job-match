# PROGRESS

> Updated by Claude at the end of every session. Read this first when resuming.

## Current milestone
**Milestone 15: dedup when the employer is hidden** — **DONE** (2026-10-16). France Travail
publishes some offers without an employer name, and the dedup block was the normalized company,
so those postings were never compared with anything. M14 is complete. M9 manual GitHub setup
still pending (see below), and the `PROFILE_YAML` secret needs re-encoding before CI searches
nationally.

## Done
- **Dedup when the employer is hidden** (2026-10-16, M15):
  - **The bug:** the digest sent "Ingénieur DevOps — Rennes" twice. Measured on the local DB:
    jobs 155 and 160 shared a normalized title and a department, their descriptions were 98.6%
    similar, both were eligible and canonical. One had an employer name, the other did not, and
    the fuzzy block is `company_normalized` — `""` and `"acme"` are different blocks, so the pair
    was never compared. The `""` block was also too wide: all 107 employer-hidden postings of the
    window in one block, with no location constraint at all.
  - With no employer name the block is **the normalized title plus the department**, any company
    (`JobRepository.list_by_title_department`); the descriptions decide as before. A posting that
    *does* have an employer also looks at the employer-hidden postings with the same title and
    department, so the fix does not depend on arrival order. Two named employers are never
    compared on title and department alone.
  - `normalization.block_location` is the key: `department_of(location)`, falling back to the
    normalized text ("France", "Télétravail", an unlisted town). Source-independent — France
    Travail's "35 - Rennes" and Jooble's "Rennes, France" both give "35".
  - `pipelines/jobs._candidate_blocks` / `_usable_candidates`: one place decides who a posting is
    compared against, used by the run and by the reprocess replay. A **rejected** row is never a
    candidate (`list_unnotified` hides every duplicate, so an eligible job behind a rejected
    canonical would be lost), and a match against a row that is itself a duplicate links to that
    group's canonical instead of starting a chain.
  - **`job-match reprocess` now replays dedup** (it used to skip it, which made this fix invisible
    on data already collected). Collection order, window measured from each job's own
    `collected_at`, candidates strictly earlier in `(collected_at, id)` so the older posting stays
    canonical, ids only in the log. `RunSummary.duplicates` = new links found,
    `RunSummary.self_links_dropped` = corrupt self-links removed.
  - Reprocess on the real DB (533 jobs): **2 new duplicate links** (160 → 155, 200 → 155 — the
    latter missed because both arrived in one run), digest pool 83 → 81 canonical eligible. The
    one remaining same-title/same-department pair is two named employers whose descriptions are
    57% similar: two different offers, correctly kept.
  - ADR 0006. 34 new tests (937 total), ruff clean.
- **National search scope** (2026-10-16, M14):
  - One profile key replaces two lists: `location_scope: france` (or a department list) drives
    the France Travail queries, the Jooble location, and the location gate. Parsed in
    `config/loader._parse_location_scope` into `FTSearch.departments`, where empty already
    meant "no department filter"; `FTSearch.national` names the condition. The old
    `ft_search.departments` key still loads (deprecated alias), `filters.locations` is gone
    from the profile.
  - France Travail: no `departement` param nationally, one paginated query per keyword, and
    the API window is now enforced in the adapter — `Range` start <= 1000, end <= 1149, so
    1050 offers over 7 pages. Truncation logs a WARNING with reachable vs available; an HTTP
    400 on a page ends that query instead of the run.
  - Jooble: `regions=["France"]` when national (chosen in the source factory), so the whole
    call budget goes into pages rather than regions.
  - Gate: `location.french_location()` is tri-state (in France / abroad / cannot tell) and only
    "abroad" rejects. Backed by `fr_geo.FRENCH_DEPARTMENTS` (France Travail files offers abroad
    under the fake department 99) and a short `FOREIGN_PLACES` marker list, checked before city
    names so "Lille, Belgique" is Belgium. The location check now runs on every job.
  - `RunSummary.by_department`, parsed from each offer's own location, with the top 10 in the
    run summary: with one national query `by_area` is just "all".
  - ADR 0005. 123 new tests (903 total), ruff clean.
- **Empty-digest bug + relevance title veto** (2026-10-16):
  - **Root cause of "112 eligible, 1 job emailed":** running the jobs pipeline twice in one
    day. `JobRepository.save` upserts on (source, source_job_id), so the second run re-read
    each posting, matched its *own* fingerprint, saved over its own row, and then wrote a
    `job_duplicates` row with `canonical_job_id == duplicate_job_id`. `list_unnotified`
    excludes duplicates, so every job vanished from the digest, and the dedup branch skips
    scoring so their scores were blanked too. The local DB had 85 such self-links.
  - Fix: `pipelines/jobs._other_postings` drops the job's own stored row from both dedup
    candidate lists. Keyed on (source, source_job_id), so the same offer on another source
    is still a duplicate. 10 consecutive runs now leave one visible, scored job.
  - `JobDuplicateRepository.delete_self_links()` cleans rows left by the old behaviour.
  - **Title veto** (`gate.title_is_a_dev_role`): a `dev_titles` word in the title means the
    job is a developer role whatever its description says, unless the title also names a
    `role_titles` term. Runs before and overrides the skill match. Whole-word, accent-
    insensitive matching (`skills.title_term`), so ".net" never matches "network" and "dev"
    never matches "devops". `cloud` is deliberately not a role_title — only "cloud engineer"
    and "ingénieur cloud" — so "Développeur Cloud" stays rejected.
    Both lists in `config/settings.yaml` under `relevance:`, nothing hard-coded.
  - `job-match reprocess [--since YYYY-MM-DD] [--limit N] [--dry-run]` +
    `pipelines/jobs.reprocess_jobs`: re-applies the gate and scorer to stored jobs, no API
    calls, `notified_at` never touched. Drops self-links first. (Since M15 it also replays
    dedup.)
    `JobRepository.list_all(since)` added.
  - Reprocess on the real DB (533 jobs): 85 self-links dropped, 448 rejected
    (EXPERIENCE 286, NOT_RELEVANT 194, CONTRACT 154), **85 eligible / 28 strong**,
    digest-visible went 0 → 70 (40 at or above `digest.min_score` 60). The veto rejects 41
    of the 533 titles; 2 dev-worded titles survive on an explicit role_title
    ("Ingénieur Développeur DevOps Kubernetes").
  - `daily.yml` can now clean the production DB: the `reprocess_since` date drives
    `job-match reprocess` (new step, before the digest and the WAL checkpoint) and/or the
    funding reprocess, selected by a new `reprocess_scope` choice input (jobs / funding /
    both, default jobs). The step runs `--limit 0`, so only aggregate counts reach the
    public Actions log, and `continue-on-error` keeps a failed cleanup from costing the
    digest or the DB push.
  - **Jooble keyword semantics measured before optimizing** (`scripts/jooble_probe.py`,
    4 real calls, Île-de-France, page 1): "devops" 21 offers, "kubernetes" 3,
    "devops kubernetes sre" exactly their union of 21 ids, "devops OR sre OR kubernetes" the
    same 21. Jooble ORs the words and ranks by relevance; it does not AND them, and a literal
    "OR" is just another token. Coverage of the single-keyword sets: 100%.
  - Adapter now sends **one combined query per region** (7 keywords × 7 regions = 49 calls
    — 7) and spends the freed budget on **pagination**: each page is one call, at most
    `max_calls_per_run // len(regions)` pages per region, so page 1 of every region is always
    affordable. `max_results` now defaults to None (the budget is the only ceiling);
    `--limit N` still caps a region and shrinks `ResultOnPage`.
  - 70 new tests (780 total), ruff clean.
- **Milestone 13** (2026-10-16):
  - `adapters/jobs/jooble.py` (`JoobleSource`, POST per keyword × region) and
    `adapters/jobs/adzuna.py` (`AdzunaSource`, one `what_or` GET per region — all keywords OR'd).
    No keyword × department fan-out: their free quotas are a few hundred calls a day.
  - `adapters/jobs/factory.py` — `build_sources(profile, settings, limit=)` + `REQUIRED_ENV`.
    Enabled source without credentials → one WARNING, run continues; empty list → exit 1.
  - `config/settings.yaml` `sources:` block — `enabled: [france_travail, jooble]` (adzuna off
    until the plan is paid), `regions`, `jooble.max_calls_per_run: 15`, `adzuna: 20`.
    `SourcesConfig`/`SourceLimits` in schema; any key other than `enabled`/`regions` is a
    per-source limit, so a 4th source needs no schema change.
  - `normalization/fr_geo.py` (regions → departments, ~170 cities, department names) +
    `location.departments_for()`: resolves `"92 - Nanterre"`, `"Nanterre"`,
    `"Nanterre, Hauts-de-Seine"` and `"Île-de-France"`. Empty result = unknown → job kept.
    Longest name wins (Boulogne-Billancourt 92 vs Boulogne-sur-Mer 62).
  - `normalization/contract.py` — `parse_contract_type(*texts)` (FR/EN). "Full-time" is working
    time, not a contract, and stays UNKNOWN.
  - Gate: contract `UNKNOWN` no longer rejects (same rule as unknown experience/location); a
    *stated* contract outside the filter still does. Location gate uses `departments_for`.
  - `pipelines/jobs.py` — `run_jobs(sources, ...)` takes one source or a sequence, drains them
    in order through one dedup pass, and reports `by_source` (fetched/eligible/duplicates/calls).
    A source whose `fetch` raises costs one error, not the run.
  - Dedup blocks on the company alone (`JobRepository.list_by_company`): the same offer on
    Jooble carries UNKNOWN contract, so the old `(company, contract_type)` block never
    compared them. First source in `enabled` order wins the canonical row.
  - `cli.py` — `_quiet_http_logs()` keeps `httpx`/`httpcore` above INFO. Jooble puts its API key
    in the URL *path* and Adzuna in the query string, and httpx logs full URLs at INFO straight
    into the public Actions log. Adapters log their own line with the URL redacted (`<key>`).
    Summary prints a per-source block; `QueryStat.department` → `area`,
    `RunSummary.by_department` → `by_area` (a region is not a department).
  - `.env.example` + `daily.yml` env: `JOOBLE_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
    README sources line + diagram. `docs/adr/0004-multi-source-ingestion.md`.
  - 124 new tests (710 total), all HTTP mocked with respx, ruff clean.
  - Verified locally: jooble-only without a key → one WARNING + exit 1; committed config →
    jooble skipped, France Travail ran (503 fetched, 111 eligible, 29 strong, 98 calls);
    no httpx URL line reaches stdout.
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
- Watch the next digest: it should no longer carry the same offer twice. If a twin shows up, the
  pair to look at is two *named* employers (the cross-company path needs a hidden employer on one
  side) or two titles that normalize differently.
- **Re-encode the `PROFILE_YAML` secret** from the updated `config/profile.yaml`, or CI keeps
  searching the old 14 departments (the deprecated `departments` alias still loads):
  `base64 -w0 config/profile.yaml`.
- Watch the first national runs for the `truncated by the API window` WARNING. If a keyword
  hits it daily, the fix is one query per keyword × region, or passing `since`.
- Clean the production DB: trigger "Daily run" manually with `reprocess_since` = the first
  collection date to re-check (e.g. 2026-10-11) and `reprocess_scope` = `jobs`. Then re-check
  the digest: it should carry ~40 jobs, not 1.
- **Pending from M13:** run the Jooble-only check (`sources.enabled: [jooble]`,
  `job-match run --limit 10 --dry-run`) and review what Jooble actually returns: location
  formats not in `fr_geo.py`, and how many jobs land with UNKNOWN contract. The key is in
  `.env` and the keyword probe is done; this is the end-to-end pass.
- Add `JOOBLE_API_KEY` as a GitHub secret before the next daily run, or Jooble stays skipped in CI.
- Complete the M9 manual GitHub setup and trigger the first daily run; review the first digest's leads and
  evidence sentences (precision check before M11b).
- **Milestone 14:** optional web application (only if needed).
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
| `JOOBLE_API_KEY` | Jooble API key (jooble.org/api/keys) — optional; without it Jooble is skipped |
| `ADZUNA_APP_ID` | Adzuna app id — optional, and Adzuna is off in `sources.enabled` anyway |
| `ADZUNA_APP_KEY` | Adzuna app key — optional, same |

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords → create one named "job-match".

### 5. First run

Trigger manually: `github.com/Chacronemed/job-match` → Actions → "Daily run" → Run workflow.
Watch the logs — they show only aggregate counts (fetched/eligible/strong), never personal data.

---

## Open decisions
- ~~Hiring window~~ **Resolved 2026-10-05:** strict window + narrow exception for single-topic
  articles (sentence must refer back to the raise or the company). Measured 1 → 10 high-priority leads.
- ~~Lead ranking~~ **Resolved 2026-10-05:** hiring first, then pre-seed/seed/series A/B, then most recent
  (publication date). Amount is not a ranking criterion.
- **M11b: roundup articles:** one event per strict deal line (`^- <Company> lève|boucle|raises <explicit amount>`),
  only after M11 precision is validated on real data.
- Exact France Travail search parameters (ROME codes, departments), to settle in M2
- Numeric thresholds (strong match, divergence, fuzzy T1/T2), to calibrate in M4 and M6 on real data
- Score calibration (after first real run): scale is compressed (50–70 on samples). Options: normalize score = earned/max possible points, base_score 0, strong_threshold 60, more negative skills. Calibrate on ~50 real France Travail jobs.
- ~~**M9 — WAL flush before data-repo push:**~~ **Resolved in M9.** `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM` run in daily.yml before DB push. `*.sqlite-wal` and `*.sqlite-shm` added to `.gitignore`.

## Known issues
- The title veto keeps a dev title that also names a role_title: "Développeur FullStack -
  Java/Angular/DevOps" survives the veto by design (it was rejected on CONTRACT anyway).
  Tighten `role_titles` if those turn out to be noise.
- `job-match run` twice in a day is now safe, but the second run still re-scores every job
  and rewrites its row. Harmless, just wasted work.
- `fr_geo.py` is deliberately incomplete: an unlisted city resolves to no department and the
  job is kept. Expect noise from Jooble locations outside the table, never silent drops.
- Contract `UNKNOWN` now passes the gate, so Jooble/Adzuna jobs with no contract field reach
  scoring. If that proves noisy, add a scoring penalty — not a gate rejection.
- Cross-source dedup is fuzzy on title+description within one company. A reposting agency that
  renames the company still yields two canonical rows (same limitation as before).
- A national France Travail query reaches 1050 offers (`Range` start <= 1000, end <= 1149, 150
  per page). A keyword with more live offers than that is truncated, with a WARNING per query.
- `FOREIGN_PLACES` is a short marker list: an unlisted foreign city resolves to unknown and its
  job is kept. Noise, never a dropped French job.
- A French employer whose location field names a foreign HQ is now rejected on LOCATION.
- Jooble pagination depth is `max_calls_per_run // len(regions)` pages: adding regions makes
  every region shallower (7 regions, 15 calls = 2 pages = 100 offers each). Raise
  `sources.jooble.max_calls_per_run` rather than trimming regions if depth matters.
- The Jooble probe measured one region on one day. If a region's union of keywords ever exceeds
  what the budget can page through, the relevance ranking decides what we lose, not us.
- Jooble returns a snippet, not the full description: the experience parser and the scorer see
  less text for those jobs than for France Travail ones.
- Existing funding events also lack the stricter hiring/country extraction until reprocessed: trigger
  "Daily run" manually with `reprocess_since` (the DB lives in the private data repo).
- Existing funding events have no `country` until `job-match funding reprocess --since <date>` is run.
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
- 2026-10-16: Dedup for employer-hidden postings. Title + department block when the company is
  empty, the department as a source-independent blocking key, rejected rows excluded as
  canonicals, and a dedup replay inside `job-match reprocess` (2 new links on the real DB,
  digest pool 83 -> 81). ADR 0006. 937 tests passing.
- 2026-10-16: National search. `location_scope: france` as the single geography setting,
  France Travail paginated nationwide inside its 1050-offer API window (truncation warned,
  HTTP 400 non-fatal), Jooble querying "France" once, a tri-state French/foreign/unknown
  gate, and `by_department` in the run summary. ADR 0005. 903 tests passing.
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
- 2026-10-05: Quality fixes from the first real digest. Jobs: relevance gate (`NOT_RELEVANT`, keywords in
  settings.yaml), `digest.min_score: 60`, `jobs.search_query` stored + shown in the digest (DEBUG log only).
  Funding: hiring needs a verb/plan and sits in the anchor window; briefs scoped to the company paragraph;
  explicit `country`. Digest: `funding.lead_filters` (countries, min_amount_eur, exclude_sectors),
  `digest.max_leads: 10`, priority then amount, overflow rolls over. Migration 0005. 537 tests passing.
  Replay on today's frozen live data: jobs emailed 102 → 25, leads emailed 26 → 10 (3 country-filtered,
  13 roll over), high-priority leads 14 → 1 (see open decision on the hiring window).
- 2026-10-16: Measured Jooble's keyword semantics (OR + relevance ranking, union coverage
  100%) with a 4-call probe, then collapsed the adapter to one combined query per region and
  spent the freed budget on pagination (pages count as calls). 780 tests passing.
- 2026-10-16: Daily workflow can clean the production DB: `reprocess_since` + new
  `reprocess_scope` inputs drive `job-match reprocess` before the digest, counts only in the
  log (`--limit 0`). 772 tests passing.
- 2026-10-16: Location gate fixed to accept the departments we query (`ft_search.departments` as
  the single source of truth, unparseable location kept); FT per-query keyword moved to DEBUG and
  the per-keyword summary block off stdout (public Actions log). 586 tests.
- 2026-10-16: Diagnosed the empty digest (self-referential duplicate links from running the
  pipeline twice in a day), fixed the cause and added cleanup; added the dev-title relevance
  veto and `job-match reprocess`. Reprocess on the real DB: 85 eligible, 28 strong,
  digest-visible 0 → 70. 765 tests passing.
- 2026-10-16: M13 complete (bar the Jooble live run). Jooble + Adzuna adapters, source factory,
  `sources` config, `fr_geo.py`, contract parser, multi-source pipeline with cross-source dedup
  and `by_source`, httpx URL logging silenced, ADR 0004. 710 tests passing.
- 2026-10-05: Follow-ups. Single-topic hiring exception (tie-back to raise/company), lead ranking
  hiring → early round → recency, keyword `production` replaced by `ingénieur de production informatique`
  (`exploitation` kept), `daily.yml` workflow_dispatch input `reprocess_since` (runs before the digest,
  input passed via env). 549 tests passing.
