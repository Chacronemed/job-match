# PROGRESS

> Updated by Claude at the end of every session. Read this first when resuming.

## Current milestone
**Milestone 22: "Pourquoi cette offre ?" panel + decision-based calibration** — **DONE locally**
(2026-10-21), not deployed. ADR 0013. Needs the M21 Cloudflare setup (Next step) before the
overrides reach production; then one manual `reprocess_since` run fills the evidence on the
production rows. Still pending: the M21 Cloudflare setup, the data-repo cleanup (ADR 0011), the
two Cloudflare secrets, M9 manual GitHub setup, `PROFILE_YAML` re-encoding, `SMTP_PORT` variable.

## Done
- **"Pourquoi cette offre ?" + calibration** (2026-10-21, M22, ADR 0013):
  - **Evidence in the breakdown JSON** (no migration; old rows load with empty defaults):
    - `normalization/skills.find_skill` and `snippet`: the sentence around a match, at most 160
      characters, with "…" when cut. "node.js" is never split, and a bullet marker is stripped.
    - `NativeRuleScorer(aliases, vocabulary)` records `evidence`, `weights` and `unlisted`
      (vocabulary skills that are not in the profile; they never change the score).
    - `ScoringBreakdown.experience_detail` is `{required_years, basis, sentence,
      excludes_apprenticeship}`.
      - `basis` (`ExperienceBasis`) is explicit / seniority / unknown / not_mentioned, decided by
        the gate (`_basis`).
      - The sentence comes from `ExperienceRequirement.sentence` (`parser.sentence_of`), or from
        `infer_seniority` for a keyword.
  - **Vocabulary:** `config/skill_vocabulary.yaml`, 60 terms, loaded by `load_skill_vocabulary`.
    Its aliases are in `aliases.yaml` (gitlab-ci, gitlabci, argo cd, postgres…).
  - **Skill overrides:**
    - D1: `worker/migrations/0002_skill_overrides.sql`.
    - Worker: `PUT` / `DELETE /api/skill-overrides/:skill` (lowercase, at most 40 characters,
      same auth and origin rules); `GET /api/applications` also returns `skill_overrides`.
    - `fakeD1` now applies every migration.
    - Mirror: migration `0009_skill_overrides_mirror.sql`; `tracking import --skill-overrides`
      skips names outside the vocabulary and writes `overrides_changed=true|false` to
      `$GITHUB_OUTPUT`.
    - `config/loader.apply_skill_overrides` adds them as preferred skills with
      `scoring.override_weight: 2`. Called by `run` and `reprocess` (`cli._with_skill_overrides`);
      only the count is printed.
  - **`daily.yml`:**
    - Set up Node, Apply D1 migrations and Export tracking (3 exports) now run right after
      Restore DB, before the jobs pipeline.
    - New step "Reprocess for skill overrides", only when `overrides_changed == 'true'`:
      `reprocess --since <today − max_age_days> --limit 0`.
  - **Dashboard:**
    - `data.py` adds `why` per job: skills, unlisted, lowered, experience, each sentence capped
      at 240 characters.
    - `dashboard.js` `whyPanel`, five blocks: Compétences détectées (plus "absentes, sans effet
      sur le score"), Non trouvé dans ton profil with "je maîtrise" / Annuler, Expérience with
      a confidence badge, Ce qui a baissé le score, and Ton avis (the verdict pills moved here,
      with their own save state).
    - "Toutes les explications" is folded.
    - `failureText` is shared, so a verdict save now gives the friendly 401/5xx message too.
    - `tracking.js` adds `client.overrideSkill`. DESIGN.md has four new components.
  - **`job-match calibrate [--since]`** (`calibration/report.py`,
    `ApplicationRepository.list_latest_decisions`):
    - reports the precision of strong, the score distribution per label (10-point bands), rule
      lift on off_topic, and the unlisted skills on missing_skill jobs;
    - suggests (threshold at recall ≥ 0.5, lower a preferred weight at lift ≥ 2, add a skill
      named on ≥ 3 missing_skill jobs) only from 10 verdicts on, and never writes config;
    - local only.
  - **Local reprocess (1670 jobs):**
    - 337 scored. Basis: explicit 94, not_mentioned 183, seniority 48, unknown 12.
    - 138 jobs carry unlisted skills (gitlab ci 41, java 34, kafka 18, openshift 18…).
    - Scores are unchanged by construction.
  - **Verified:**
    - `wrangler dev` with a local D1 (scratch config holding only the `DB` binding) behind
      `dev-access-proxy.mjs`, driven by playwright-cli at 1440 and 390, dark and light:
      - "je maîtrise" → D1 row;
      - forced 500 on Annuler → revert + Retry → deleted;
      - verdict stored with `score_at_decision` 92;
      - a `<img onerror>` / `<script>` snippet shown as text, `__xss` unset;
      - 44 px targets on mobile, no horizontal overflow, 0 console errors apart from the forced
        500.
    - Local D1 export → import printed `(changed)` and `overrides_changed=true`, and the
      reprocess gave datadog +2 on 9 jobs. The mirror was then reset to empty and reprocessed.
  - Tests:
    - 73 Node tests;
    - Python tests: evidence/basis/overrides/vocabulary (18), mirror overrides (9), why
      (4), calibrate (6), workflow, enums (the skill pattern agrees across D1, Worker and
      Python; the vocabulary passes it).
    - ruff clean. 1 test fails, unrelated to M22 (Known issues).
- **Application tracking** (2026-10-20, M21, ADR 0012; M20 was the closure check):
  - **D1** (`worker/migrations/0001_tracking.sql`):
    - `applications(job_key PK, status, applied_at, follow_up_at, note ≤ 2000, cv_url,
      updated_at)`;
    - `decisions(id, job_key, label, score_at_decision, created_at)`;
    - `job_key` = `source:source_job_id` (`tracking.constants.job_key`; `data.py` adds `key`).
  - **Worker** (`worker/src/`, no deps; `wrangler.jsonc`: `main`, `run_worker_first: ["/api/*"]`,
    D1 binding `DB`):
    - routes: `GET /api/applications` (+ latest verdict per job), `PUT
      /api/applications/:key` (upsert), `POST /api/decisions`;
    - every call verifies the Access JWT (RS256, JWKS cached 1 h with at most one refetch a
      minute for an unknown kid, `aud`, `iss`, `exp`/`nbf` ± 60 s); missing → 401, keys
      unreachable → 503, secrets unset → 500;
    - same-origin only (writes need `Origin`), JSON with a body ≤ 8 KB, no CORS headers;
    - validation: unknown fields, enums, real dates, `https:` CV links without credentials;
      errors never echo input.
  - **Dashboard** (`assets/tracking.js` pure logic + `dashboard.js`; CSP `connect-src 'self'`):
    - "Aujourd'hui" is the default tab: KPI strip, "Relances du jour", then the queue of
      untracked/to_review/to_apply jobs, to_apply first;
    - Jobs tab: Status column (sortable) and filter (`st=` in the hash);
    - the details form is optimistic, reverts on failure, offers Retry and shows field errors;
    - the note saves after 800 ms or on blur; `beforeunload` warns while a save is pending;
    - a banner appears when opened from a file or when the API fails. DESIGN.md has the new
      components.
  - **Mirror and digest:**
    - migration `0008_tracking_mirror.sql`;
    - `tracking/mirror.py` validates every row like the Worker and replaces both tables in one
      transaction; a malformed export writes nothing;
    - `job-match tracking import` prints counts only;
    - `list_unnotified` leaves out jobs whose status is not to_review/to_apply;
      `ApplicationRepository.list_followups_due` (not rejected/ignored, oldest first, offer
      joined when still stored);
    - the digest opens with "Relances du jour" (no note, no CV link), sends even when it only
      has follow-ups, never marks them, and counts them in the subject.
  - **`daily.yml`:**
    - "Set up Node" moved up;
    - "Apply D1 migrations" and "Export tracking" run after the pipelines and before the
      VACUUM, both `continue-on-error`;
    - the export goes to a `umask 077` temp dir that is removed on exit and never printed.
  - **Tests:**
    - `worker/test/*.test.mjs`: 68 Node tests, a fake D1 over `node:sqlite` running the real
      migration, a real RSA key; run by `tests/unit/test_worker_js.py`, and `ci.yml` installs
      Node 22;
    - Python tests: mirror, enums agreeing across SQL/Worker/JS/Python, digest exclusion and
      follow-ups, workflow order, wrangler config.
    - 1280 tests, ruff clean.
  - **Verified locally:**
    - `wrangler dev` with a local D1 behind `scripts/dev-access-proxy.mjs` (signs a JWT, serves
      the JWKS, injects the header; `.dev.vars` is gitignored);
    - API without a JWT or with a forged one → 401, foreign Origin → 403, `http:` CV → 400;
    - playwright-cli at 1440 and 390, dark and light: save → "Saved", forced 500 → error,
      revert and Retry, a `<img onerror>` note shown as text, 0 console errors, no overflow;
    - layout fixes from the screenshots: min widths on status/score/date, link-ink "To
      apply", "Ignored" struck through instead of tertiary ink, 44 px targets on mobile.
- **Compressed single-commit DB snapshot** (2026-10-20, ADR 0011): the data repo had a
  27.3 MB `jobs.sqlite`, 26 commits, 9.2 MB packed. `job_match.persistence.snapshot`
  restore (gunzip, legacy plain file read once) / publish (deterministic gzip, skip if
  identical, rotate to `jobs.prev.sqlite.gz`, parentless commit force-pushed to `main`,
  `::error::` + exit 1 and no push over 90 MB). `daily.yml` Restore/Push steps call it; the
  VACUUM step is unchanged and runs before. Local DB: 11.7 MB → 2.6 MB gz (4.5×, 0.4 s).
  Tests use a real bare repo in tmp_path. **One-time cleanup pending** (manual, see the
  session notes / ADR 0011): delete and recreate `job-match-data` after the first new run,
  or wait for GitHub GC.
- **Raw payloads stored** (2026-10-20): `raw_payloads` existed since 0001 but nothing wrote it.
  - `run_jobs` stores each fetched item right after `to_job` (not in dry run), as canonical
    JSON (sorted keys, compact, `default=str`), via `RawPayloadRepository.save_if_changed`:
    skipped when identical to the latest row for that offer. `save` now returns whether a row
    was inserted (one copy per item per run), so `raw_stored` counts real rows.
  - `adapters/jobs/base.source_payload` drops the adapters' own `_jm_*` annotations first:
    with `_jm_query` kept, an offer returned by "devops" and "devsecops" differed every run.
  - `prune(now - raw_payloads.retention_days)` after the closure check (`settings.yaml`
    `raw_payloads.retention_days: 60`, `RawPayloadsConfig`, positive int). No VACUUM.
  - `RunSummary.raw_stored` / `raw_pruned` in `summary_json` and the CLI summary; not in the
    dashboard `RUN_KEYS`. Payloads are never logged (only counts and the exception type).
  - Local DB: 8.3 MB (0 raw rows) → 12.6 MB after real runs; 582 offers stored at 4.3 KB avg
    (2.5 MB); an immediate rerun stored 0. Projection: ~0.8 MB/day of new offers, ~50 MB at
    60 days (more if offers change often). Lower `retention_days` if the DB push gets slow.
  - README "Lessons from production": the "Un anglais" → 1 an row. 1211 tests, ruff clean.
- **Experience parser fix** (2026-10-20, post-M20): job 171 ("Minimum 5 ans … (hors stage et
  alternance)") was ELIGIBLE because `_PLAIN_RE` read "**Un an**glais" as 1 year and the
  smallest-minimum rule beat 5. The France Travail structured experience field is not used at
  all (the adapter never maps it, and FT raw payloads are not stored).
  - Shared `_UNIT` with a trailing `\b`; "années" counts after a qualifier, or in the plain
    form only before "d'expérience" ("deux années consécutives" is not a requirement).
  - An explicit minimum ("minimum/au moins N", "N+") wins over a smaller plain or range mention.
  - `ExperienceRequirement.excludes_apprenticeship` ("hors stage", "hors alternance", "hors
    stage et alternance") → migration `0007` column, explanation note
    `EXCLUDES_APPRENTICESHIP_NOTE`. Eligibility is unchanged by the flag.
  - Local reprocess: 22 jobs changed status (14 ELIGIBLE→REJECTED, 3 STRETCH→REJECTED,
    5 ELIGIBLE→STRETCH); rows ELIGIBLE 240→221, STRETCH 101→103. Flag: 0 ELIGIBLE, 3 STRETCH,
    6 REJECTED. 1190 tests, ruff clean.
- **Offer closure check** (2026-10-19, M20):
  - **Measured first** (`scripts/ft_closed_probe.py`, 1 token + 9 detail calls, then 10 through
    the adapter): `GET /partenaire/offresdemploi/v2/offres/{id}` answers **204 No Content** for
    a withdrawn offer and 200 with the full offer otherwise; no status field, only
    `dateCreation`/`dateActualisation`. 6 of the 10 oldest visible local offers were gone.
  - Migration `0006_job_closure.sql`: `jobs.closed_at`, `jobs.last_checked_at` (nullable ISO
    UTC, not on the `Job` model, never written by `save`, like `notified_at`).
  - `adapters/jobs/base.OfferStatus` (OPEN / CLOSED / UNKNOWN); `check_offer` is an optional
    `JobSource` method. `FranceTravailSource.check_offer`: same token and throttle as the
    search, counts in `api_calls`; 200 → OPEN, 204/404 → CLOSED, anything else (400/401/403,
    429/5xx after retries, timeout, transport error) → UNKNOWN with a warning; a token failure
    propagates.
  - `pipelines/closure.check_closed` runs inside `run_jobs` after collection: rows the search
    returned are `mark_open` (no call); `JobRepository.list_to_check` picks canonical
    ELIGIBLE/STRETCH rows not closed, inside the age cut-off, not checked in 24 h
    (`RECHECK_AFTER`), never-checked first; CLOSED → `mark_closed`, OPEN → `mark_checked`,
    UNKNOWN → untouched and counted in `errors`; an exception from a source stops the check
    after one warning. `dry_run` writes nothing. `RunSummary.checked` / `closed`, stored in
    `summary_json`, printed by `_print_summary` (jobs run only), shown on the Runs tab.
  - `list_unnotified` / `list_canonical_scored` take keyword-only `now` + `max_age_days`: always
    `closed_at IS NULL`, and with both `COALESCE(published_at, collected_at) >= cutoff`. Lead
    `open_jobs` ignores closed jobs. `settings.yaml` `jobs.max_age_days: 45` (`JobsConfig`,
    positive int).
  - Dashboard: `posted_at` (= published_at or collected_at) and `age_days` per job; columns
    "Posted" (sort desc) and "Age" (sort asc) replace "Collected"; date filters are "Posted
    from/to"; details row shows the collected date and says when the source gave no posting
    date; `RUN_KEYS` += checked/closed.
  - **Local run** (real API, local DB): 15 search + 104 check calls, **39 closed (37 %)**, 0
    unclear; 21 more hidden by age alone; dashboard 286 → 265 visible jobs (43 strong, 152
    eligible, 70 stretch), ages 0–41 days; digest dry run 115 jobs. Playwright at 1440 and
    390: headers, both sort directions on Age and Posted, `from=` filter, 9-column details
    row, runs tab "checked at source 104 · closed 39", no horizontal overflow, 0 console
    errors.
  - 52 new tests (1175 total), ruff clean.
- **Private web dashboard** (2026-10-19, M19):
  - `dashboard/data.py` is the allow-list of what leaves the DB: canonical ELIGIBLE/STRETCH
    jobs (`JobRepository.list_canonical_scored`, notified or not), every lead
    (`LeadRepository.list_details`, shares the SQL of `list_unnotified_details`), the last 30
    `jobs`/`jobs_reprocess` runs (`RunRepository.list_recent` → new `RunRecord` read model).
    No description, no `search_query`, no `by_keyword`/`queries` (profile keywords), no
    profile loaded at all. Links kept only with an http(s) scheme. `required_years` =
    `experience.min_years`, else the stretch note's number, else null; the gate is never
    re-run. Funnel `rejected` = fetched − duplicates − eligible − stretch (unique rejected
    jobs are not stored; the per-reason map is labelled "may fail several gates").
  - `dashboard/render.py` + `assets/index.template.html|dashboard.css|dashboard.js`:
    one file, CSS/JS inlined, data in a `<script type="application/json">` block with every
    `<` as `<`, DOM built with `textContent`, CSP meta (`default-src 'none'`, inline
    only), `noindex`. Works from `file://` (checked with Python Playwright). Tabs, KPI strip,
    search / section chips / department / min score / dates, sort on every column, details
    row with explanations and skill pills, leads with evidence sentences, CSS-bar funnel per
    run. Filter state lives in the hash (`#jobs?q=…&hide=…&min=…&sort=…`), validated
    against allow-lists. Dark first (DESIGN.md tokens), light via the inverse tokens
    (`prefers-color-scheme` + toggle in `localStorage`), 390px card layout, reduced motion.
  - `wrangler.jsonc` (name `job-match`, `assets.directory ./site`, no `main`); `daily.yml`
    steps "Build dashboard" / "Set up Node" / "Deploy dashboard" after the DB push, all
    `continue-on-error` and `if: always() && steps.wal.outcome == 'success'`; wrangler's
    stdout (the Worker URL) discarded. `/site/`, `.wrangler/`, `.taste-skill/` gitignored.
  - `docs/design/DESIGN.md` adapted (job-match, no Linear wording, `semantic-stretch`,
    Light Mode and Dashboard Components sections). README "Dashboard" section (no URL),
    ARCHITECTURE §13 rows 13–19, ADR 0009.
  - Verified in Playwright at 1440 and 390, dark and light, every tab; search, chips,
    department, min score, dates, every sort both ways, click/Enter expand; 0 console
    errors; no horizontal overflow at 390. web-design-guidelines review applied
    (theme-color, h1/h2, input names, touch-action, URL state, select colours).
    Deviation kept on purpose: sentence case on labels (DESIGN.md), no list
    virtualisation (125 rows).
  - 36 new tests (1123 total), ruff clean. Local snapshot: 125 jobs (26 strong, 57
    eligible, 42 stretch), 0 leads (the local DB has none), 7 runs.
  - **CI fix (2026-10-19):** the three dashboard test files imported
    `tests.unit.dashboard._seed`, which only resolves under `python -m pytest` (cwd on
    `sys.path`); CI's plain `pytest -q` failed at collection. The seed is now the
    `seed_dashboard` factory fixture in `tests/unit/conftest.py` (returns a `DashboardSeed`
    with ids and constants) plus `dashboard_data` in `tests/unit/dashboard/conftest.py`; no
    test imports the `tests` package. CLAUDE.md now names the CI commands
    (`.venv\Scripts\ruff check .`, `.venv\Scripts\pytest -q`). Polish: `<html lang="fr">`
    (date inputs show dd/mm/yyyy), contract values uppercase.
- **Experience stretch tier** (2026-10-18, M18):
  - **Measured first** (local DB, read-only, 533 jobs, candidate 2 years): 145 jobs rejected
    *only* on EXPERIENCE. Required years: exactly 3 → 25 (21 would score ≥ 60, 13 strong);
    4 → 8; 5+ → 68; seniority keyword with no number → 44 (18 at the "confirmé" level).
  - `settings.yaml` `experience.stretch_years: 1` (`ExperienceConfig`; 0 = off). Gate:
    `candidate < required <= candidate + stretch_years` → `EligibilityResult.stretch=True`,
    no reason; `required_years` is the explicit number, else the seniority-keyword minimum.
    Above the band: EXPERIENCE as before. A job in the band that fails another gate is
    rejected, not stretch.
  - `Eligibility.STRETCH`, third value of the same column. Run and reprocess store it,
    dedup and score it like an eligible job, and count `RunSummary.stretch` on its own
    (never in `eligible` or `strong`). The scoring engine puts the gate's words first in the
    explanations: `stretch: requires 3y, you have 2`.
  - Digest: `DigestData.stretch`, section "À tenter (stretch)" after Other Eligible, by score,
    same `min_score`, each card carrying the stretch line. Subtitle and email subject count it.
    `list_unnotified` / `reset_notified_since` read both tiers; `list_eligible` (top strong
    titles) and the leads' open-jobs count stay on ELIGIBLE.
  - **Reprocess on the local DB:** see the counts in the session log line below.
  - ADR 0008 (the user asked for 0007; that number was taken by the location gate).
    26 new tests (1087 total), ruff clean. Also updated the committed-settings test: Jooble
    was switched off in `sources.enabled` after M17's probe.
- **Three fixes from the production log** (2026-10-18, M17):
  - **France Travail pagination never worked.** The adapter sent the page as an HTTP `Range`
    header; the API ignores it (even out of window, no 400) and answers page 1 every time.
    Measured on the largest keyword: 7 pages, 1050 "fetched", **150 distinct**. The page is
    the `range` **query parameter** (`range=150-299` answers `offres 150-299/3836`). Fixed,
    with a regression test. Every national run so far saw only the newest-by-relevance 150
    offers per keyword; the upsert hid the repeats, so the DB did not balloon.
  - **Newest first + publication window:** `sort=1` on every query, `publieeDepuis` from
    `sources.france_travail.published_since_days` (3; the loader accepts only 1, 3, 7, 14,
    31). Dry run, France Travail only, same day:

    | run | calls | fetched | distinct | eligible | strong | truncation warnings |
    |---|---|---|---|---|---|---|
    | before (header paging, no window) | 25 | 3275 | ~575 | 491 | 149 | 3 |
    | after (query paging, 3-day window) | 13 | 1236 | 1236 | 188 | 58 | 0 |

    The "before" eligible count is inflated by the same 150 offers scored 7 times. A range of
    3000-3149 was also served, so the documented 1050 ceiling may be gone; the clamp and the
    truncation WARNING stay as a guard.
  - **Jooble city + radius, measured** (`scripts/jooble_city_probe.py`, 6 calls, real
    pipeline, dry run): Lyon, Lyon r50, Occitanie, Toulouse r50, Nantes r50 all returned
    `totalCount=0`, 0 eligible (the Auvergne-Rhône-Alpes line printed but was lost to an
    output-encoding quirk; the production log already had it at 0). `JoobleSource` gained an
    optional `radius_km` (settings `sources.jooble.radius_km`, dormant, tested).
    `settings.yaml` regions unchanged. See Open decisions.
  - **`SMTP_PORT` is a repository variable** (`vars.SMTP_PORT` in daily.yml): a secret's value
    is masked everywhere in the log, so "465" hid every count equal to it. An unset variable
    expands to "", and `EmailNotifier.from_env` now reads "" as the 465 default instead of
    crashing on `int("")`.
  - 24 new tests (1061 total), ruff clean.
- **Positive French location gate + Jooble per region** (2026-10-18, M16):
  - **Measured first** (`scripts/jooble_location_probe.py`, 4 calls): jooble.org with an
    empty location = 18 669 offers, **0% French** on page 1 (46/50 US); `location="France"` =
    16 offers, 100% French but only the ones whose location literally says "France";
    fr.jooble.org answers 403. No national query exists, so `sources.regions` is now the 13
    metropolitan regions, the factory always passes them (the `[""]` substitution is gone),
    and `jooble.max_calls_per_run: 26` = 2 pages per region.
  - **Gate:** `location_allowed(location, profile, *, source)`. National scope: France Travail
    is kept unless a 99 prefix or a foreign marker; every other source needs
    `french_location(...) is True` (a commune, department, region or district name, a postal
    code, or "France"); unknown is rejected. Restricted scope unchanged, except a clearly
    foreign location is rejected there too.
  - **Official communes list** replaces the 170-city hand table: `scripts/build_fr_communes.py`
    (geo.api.gouv.fr, communes + municipal arrondissements, untrusted-data filtering) writes
    `src/job_match/normalization/fr_communes.tsv` (35 013 rows, 540 KB, package data, lazy
    load). `fr_geo.py` keeps regions, every multi-word department name, a 12-entry
    `EXTRA_PLACES` for business districts that are not communes (La Défense, Sophia
    Antipolis…), the foreign markers (now with US states, "usa", "uk"…) and `US_STATE_CODES`.
  - `location._scan`: one n-gram, longest-first, span-consuming lookup over all names
    (Porto-Vecchio is not Portugal, Haute-Savoie is not Savoie, "Y" only as the whole
    string), plus postal codes. US "City, ST" detected on the raw string, end-anchored.
    `departments_for` is empty for a foreign location. 2 000 lookups in 30 ms.
  - `normalize_text` spells out ligatures (œ → oe): NFKD does not, and 110 communes were
    being dropped. Fingerprints containing a ligature change; reprocess absorbs it.
  - `job-match reprocess` tallies and prints `by_department` (the "?" bucket).
  - **Reprocess on the local DB** (533 France Travail rows, all "NN - City"): nothing
    changed — 0 LOCATION, 85 eligible / 28 strong, no "?" bucket, 0 links added/removed. The
    US rows are in the production DB: trigger "Daily run" with `reprocess_since`.
  - ADR 0007; ADR 0005 point 5 marked superseded. 89 new tests (1037 total), ruff clean.
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
  - **The company block takes the same key** (`list_by_company(company, location_key, since)`): one
    employer hiring in two departments is two offers. It used to ignore the location, which hid a
    THALES posting in Lambersart (59) behind the same employer's in Vélizy (78).
    `same_block_location` is the tolerance: two real department codes are two places, but a key
    that is not a department code means "cannot tell" and matches anything, so a Jooble row saying
    only "France" still meets its France Travail twin. Unknown never splits a block, as it never
    rejects a job.
  - **The replay also removes links the current rules no longer make** (`_sync_dedup`,
    `JobDuplicateRepository.delete_link`), and relinks to the right canonical in the same pass.
    Keeping them would be the original bug upside down: a job hidden by a rule that no longer
    exists. `RunSummary.stale_links_dropped` counts them, next to `self_links_dropped`.
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
  - Reprocess on the real DB (533 jobs), in two passes: the hidden-employer block **added 2**
    links (160 → 155, and 200 → 155 which the original run missed because both arrived in one
    run); the department-aware company block then **removed 2** (200 and 217, THALES in Lambersart
    and Rennes, hidden behind the Vélizy posting). Digest pool 83 → 81 → 83, and both surviving
    links are inside one department. The remaining same-title/same-department pair in the pool is
    two named employers whose descriptions are 57% similar: two different offers, correctly kept.
  - ADR 0006. 43 new tests (946 total), ruff clean.
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

## Known issues
- `tests/unit/test_wrangler_config.py::test_one_d1_database_with_the_repo_migrations` fails.
  `wrangler.jsonc` now has a second D1 binding (`job_match` → database `job-match`, `remote:
  true`), added outside M22. It looks like `wrangler d1 create` was run with the name
  `job-match` and appended its own binding, while the first binding (`job-match-tracking`) still
  has the zero `database_id`. Decide which database is the tracking one:
  - either put its id into the `DB` binding and delete the extra entry;
  - or rename the `DB` binding's `database_name` and update `daily.yml` and the test.

## Next step
- **M22 in production:** after the M21 Cloudflare setup, trigger "Daily run" once with
  `reprocess_since` = today minus 45 days and `reprocess_scope` = `jobs`, so the visible rows get
  their evidence. Then open a job's details: the panel should show sentences and a confidence
  badge, not "non recalculé". After about 10 verdicts, run `job-match calibrate` locally on a
  restored DB.
- **Cloudflare setup for M21 (one-time, before the next daily run uses it):**
  1. `npx wrangler@4 d1 create job-match-tracking`, then put the printed `database_id` into
     `wrangler.jsonc` in place of the zeros, and commit it (not a secret).
  2. API token (`CLOUDFLARE_API_TOKEN`): add **Account → D1 → Edit** next to **Workers Scripts
     → Edit**.
  3. Zero Trust → Access → Applications → the `job-match` app → copy the **Application Audience
     (AUD) Tag**. The team domain is `https://<team>.cloudflareaccess.com` (Settings → Custom
     Pages shows the team name). Then run `npx wrangler@4 secret put CF_ACCESS_AUD` and
     `npx wrangler@4 secret put CF_ACCESS_TEAM_DOMAIN`. They are secrets, so deploys keep them.
  4. Check that the Access application covers the whole hostname, `/api/*` included, with no
     Bypass policy. Without a JWT the API answers 401 by design.
  5. The first daily run applies the D1 migration and exports empty tables. Then open the
     dashboard and change one status: the next digest's log line should read `Tracking
     mirror: 1 applications…`.
- **Watch the first production closure check:** the Actions log should carry
  `closure check: checked=N closed=M unclear=0` and the summary's `checked:` / `closed:`
  lines. The first run checks every visible row (none has `last_checked_at`), so expect
  `api_calls` to jump by a few hundred once; from then on roughly one call per visible job
  not returned by the day's search. If `unclear` is ever non-zero, look at the WARNING line
  above it (HTTP status or exception name). If a visible offer is wrongly hidden, check
  whether the API answered 404 for a live id: then drop 404 from `check_offer`'s CLOSED set.
- **Wire the dashboard deploy:** check in the Cloudflare dashboard that Workers → `job-match`
  has Access enabled on its workers.dev and preview URLs (a first deploy without it would be
  public until Access is switched on). Then add two repository secrets:
  `CLOUDFLARE_ACCOUNT_ID` (Workers overview, right column) and `CLOUDFLARE_API_TOKEN` (My
  Profile → API Tokens → Create → "Edit Cloudflare Workers" template, scoped to the account).
  Until they exist the deploy step fails quietly (`continue-on-error`). The log must show
  "Dashboard deployed" and never a URL; if wrangler ever needs the Node step first, it is
  already there. First real check: the Leads tab (the local DB has no leads).
- **Clean the production DB with the stretch tier:** trigger "Daily run" with
  `reprocess_since` = the first collection date and `reprocess_scope` = `jobs`; the log's
  `stretch:` line should be non-zero and the next digest should carry the "À tenter" section.
  Then judge the section on real cards: if the stretch jobs are worth the read, consider
  `stretch_years: 2` (8 more jobs locally, all above the threshold); if not, set it to 0.
- **Create the `SMTP_PORT` repository variable:** job-match repo → Settings → Secrets and
  variables → Actions → **Variables** tab → New repository variable, name `SMTP_PORT`, value
  `465` (or `587` for STARTTLS). Then delete the `SMTP_PORT` *secret*. Until the variable
  exists the digest uses 465.
- **Decide on Jooble** (Open decisions): one control call with `Île-de-France` (it returned 21
  offers on 2026-10-16) tells whether the key was throttled on 2026-10-18 or whether cities
  really match nothing. If cities match nothing, Jooble is 4 non-empty regions per run.
- Watch the first windowed France Travail run: `fetched` per keyword should equal `available`
  and the log should carry no `truncated by the API window` line. If a keyword's 3-day volume
  ever exceeds 1050, the WARNING says so; `published_since_days: 1` is the lever.
- After a gap longer than 3 days (a failed run, a paused schedule), raise
  `published_since_days` to 7 for one run, or the missed offers are never fetched.
- **Clean the production DB of the US rows:** trigger "Daily run" with `reprocess_since` =
  the first Jooble collection date and `reprocess_scope` = `jobs`. The log's reason breakdown
  should now show `LOCATION`, and the per-department block should have no "?" bucket worth
  mentioning. Then check the next digest for any US/foreign card.
- Watch the first per-region Jooble run: `by_area` has 13 rows now, 2 pages each; if one
  region hits `available` far above what 2 pages return, raise `jooble.max_calls_per_run`.
- If a real French job is rejected on LOCATION, look at its location string: a business park
  or a lieu-dit goes into `fr_geo.EXTRA_PLACES`; never loosen the gate.
- Watch the next digest: it should no longer carry the same offer twice. If a twin shows up, the
  pair to look at is two *named* employers in one department (the cross-company path needs a hidden
  employer on one side) or two titles that normalize differently. The opposite symptom — one offer
  per department for the same ad — is deliberate now.
- **Re-encode the `PROFILE_YAML` secret** from the updated `config/profile.yaml`, or CI keeps
  searching the old 14 departments (the deprecated `departments` alias still loads):
  `base64 -w0 config/profile.yaml`.
- Clean the production DB: trigger "Daily run" manually with `reprocess_since` = the first
  collection date to re-check (e.g. 2026-10-11) and `reprocess_scope` = `jobs`. Then re-check
  the digest: it should carry ~40 jobs, not 1.
- **Pending from M13:** run the Jooble-only check (`sources.enabled: [jooble]`,
  `job-match run --limit 10 --dry-run`) and review how many jobs land with UNKNOWN contract
  (location formats are covered by the communes list now).
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
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASSWORD` | Gmail App Password (not your Google password) |
| `DIGEST_TO` | Email address to send the digest to |
| `PROFILE_YAML` | `base64 -w0 config/profile.yaml` — run this locally and paste the output |
| `DATA_REPO_DEPLOY_KEY` | Contents of `~/.ssh/job_match_data_deploy` (the private key, full including header/footer lines) |
| `JOOBLE_API_KEY` | Jooble API key (jooble.org/api/keys) — optional; without it Jooble is skipped |
| `ADZUNA_APP_ID` | Adzuna app id — optional, and Adzuna is off in `sources.enabled` anyway |
| `ADZUNA_APP_KEY` | Adzuna app key — optional, same |

And one repository **variable** (same page, "Variables" tab), not a secret, because a secret's
value is masked in the log and `465` would hide every count equal to it:

| Variable name | Value |
|-------------|-------|
| `SMTP_PORT` | `465` (SSL) or `587` (STARTTLS); unset = 465 |

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords → create one named "job-match".

### 5. First run

Trigger manually: `github.com/Chacronemed/job-match` → Actions → "Daily run" → Run workflow.
Watch the logs — they show only aggregate counts (fetched/eligible/strong), never personal data.

---

## Open decisions
- **Keep Jooble?** (2026-10-18) The per-region run returned 0 for 9/13 regions, and the city +
  radius probe returned 0 for Lyon (with and without radius 50), Toulouse and Nantes:
  0 eligible per call. Jooble's `location` looks like an exact match on the posting's own
  location string. Either drop Jooble from `sources.enabled`, keep only the regions that
  return offers, or try the literal strings Jooble postings carry ("Paris, France"?). A
  control call on `Île-de-France` first, to rule out a throttled key.
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
- Closure check covers France Travail only; Jooble/Adzuna rows are never asked and rely on
  `jobs.max_age_days`. A job whose check keeps answering UNKNOWN stays visible and is asked
  again daily until the age cut-off hides it (counted in `errors`). 404 is read as closed
  without having been observed. The local DB now holds today's fetch (533 → 1587 rows).
- Dashboard: an ELIGIBLE job gated by a seniority keyword alone shows "—" for required years
  (only the parser's number or the stretch note is stored; the gate is never re-run). The
  Leads tab's "open jobs" counts ELIGIBLE only, like the digest. `playwright-cli` blocks
  `file:` URLs: serve `site/` with `python -m http.server` to look at it in that tool.
- A stretch job is decided by the parsed minimum or the seniority keyword map. "confirmé" = 3
  comes from `seniority_min_years`; a posting that says "confirmé" and means 5 lands in the
  stretch tier. The map is the fix, never the gate.
- Rows already notified before M18 are not re-sent when they move from REJECTED to STRETCH
  (they were never notified, so they will be sent once, in the stretch section, after the
  production reprocess).
- The title veto keeps a dev title that also names a role_title: "Développeur FullStack -
  Java/Angular/DevOps" survives the veto by design (it was rejected on CONTRACT anyway).
  Tighten `role_titles` if those turn out to be noise.
- `job-match run` twice in a day is now safe, but the second run still re-scores every job
  and rewrites its row. Harmless, just wasted work.
- Under the national scope a Jooble/Adzuna location the communes list cannot read ("", a
  lieu-dit, a business park not in `EXTRA_PLACES`) is **rejected** on LOCATION. That is the
  intended trade; the fix for a real French place is one `EXTRA_PLACES` line.
- A commune name shared by several departments ("Saint-Denis", "Sainte-Marie") resolves to no
  single department: the job passes the gate, but lands in the "?" bucket and its dedup block
  falls back to the location text.
- `fr_communes.tsv` is a snapshot (2026-10-18); communes merge every January. Rebuild with
  `scripts/build_fr_communes.py` when a merged town shows up rejected.
- Contract `UNKNOWN` now passes the gate, so Jooble/Adzuna jobs with no contract field reach
  scoring. If that proves noisy, add a scoring penalty — not a gate rejection.
- Cross-source dedup is fuzzy on title+description within one company. A reposting agency that
  renames the company still yields two canonical rows (same limitation as before).
- A national France Travail query is clamped at 1050 offers (`range` start <= 1000, end <= 1149,
  150 per page, per the docs). A keyword with more offers than that in its window is truncated,
  with a WARNING per query. On 2026-10-18 the API served `range=3000-3149`, so the ceiling may be
  gone; the clamp stays until measured again.
- France Travail offers older than `published_since_days` are never fetched. A gap longer than
  the window (failed runs, paused schedule) loses them unless the window is raised for one run.
- `JoobleSource.radius_km` is dormant: every city probed returned 0 with or without it.
- `FOREIGN_PLACES` is a marker list: an unlisted foreign city from France Travail (no 99
  prefix) resolves to unknown and is kept. From Jooble/Adzuna it is rejected anyway.
- A French employer whose location field names a foreign HQ is rejected on LOCATION.
- Jooble pagination depth is `max_calls_per_run // len(regions)` pages: 13 regions, 26 calls
  = 2 pages = 100 offers per region. Raise `sources.jooble.max_calls_per_run` rather than
  trimming regions if depth matters. Overseas regions are not queried on Jooble.
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
- 2026-10-20 (3): Application tracking (M21). D1 + Worker API with Access JWT checks,
  "Aujourd'hui" view, details form, D1 → jobs DB mirror, digest exclusion and "Relances du
  jour". Verified with wrangler dev + a local Access proxy + playwright-cli. ADR 0012.
- 2026-10-19 (3): Offer closure check (M20). Measured the detail endpoint (204 = closed),
  added `closed_at`/`last_checked_at`, `check_offer` on the France Travail adapter, the
  post-collection `check_closed` step (24 h interval, unknown never closes), the
  `jobs.max_age_days` cut-off in digest and dashboard, Posted/Age columns, checked/closed in
  the run summary. Local run: 104 checked, 39 closed. ADR 0010. 1175 tests passing.
- 2026-10-19 (2): CI collection fix. Dashboard seed helpers became conftest fixtures (no
  `tests` package imports), local test command aligned with `ci.yml` (`.venv\Scripts\pytest -q`),
  `lang="fr"` and uppercase contracts on the dashboard. 1123 tests passing under plain `pytest`.
- 2026-10-19: Private web dashboard (M19). Static generator (`job-match dashboard`), allow-listed
  data, XSS-safe embedding, three tabs with filters/sort/details and a run funnel, DESIGN.md
  tokens in dark and light, Cloudflare Worker static-assets deploy after the DB push in
  `daily.yml`, ADR 0009. Verified with playwright-cli at 1440/390 in both themes and from
  `file://`. 1123 tests passing.
- 2026-10-18 (3): Experience stretch tier (M18). Measured 145 EXPERIENCE-only rejections on
  the local DB (25 at exactly +1 year, 21 of them scoring ≥ 60), then built the tier:
  `experience.stretch_years`, `Eligibility.STRETCH`, stretch line in the explanations, digest
  section "À tenter", separate counts in run and reprocess. Local reprocess: 533 read, EXPERIENCE rejections 286 to 197, eligible 85, strong 28, stretch 43 (25 explicit + 18 "confirme"), 1 new duplicate link; digest preview: 31 stretch cards above 60.
  ADR 0008. 1087 tests passing.
- 2026-10-18 (2): Production log fixes. Found that France Travail pagination never worked
  (`Range` header ignored; `range` query param fixed it: 150 → 738 distinct on one keyword).
  Added `sort=1` and `publieeDepuis` from settings (3 days): 25 → 13 calls, 0 truncation.
  Jooble city + radius probe: 0 everywhere, decision left open. `SMTP_PORT` to a repository
  variable, empty port = default. 1061 tests passing.
- 2026-10-18: US jobs in the digest. Measured Jooble (empty location = worldwide, 0% French;
  "France" = 16 offers; fr.jooble.org 403) and switched to one query per French region.
  Gate now needs a positively French location from Jooble/Adzuna, backed by the official
  communes list shipped as package data (35k rows), an n-gram scanner, US "City, ST"
  detection, and ligature folding in `normalize_text`. Reprocess prints the "?" bucket.
  ADR 0007. 1037 tests passing.
- 2026-10-16: Dedup blocks. Title + department block when the employer is hidden, the department
  in the company block too (`same_block_location` keeps an unreadable location comparable),
  rejected rows excluded as canonicals, and a dedup replay inside `job-match reprocess` that adds
  and removes links (+2 then -2 on the real DB, digest pool 83 -> 81 -> 83). ADR 0006. 946 tests
  passing.
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
