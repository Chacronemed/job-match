# ADR 0016: an AI rerank after the Python filter

**Status:** accepted (2026-10-25, M25). Proposed on 2026-10-22 (M24) with Workers AI called from the daily run; revised before implementation: the Claude API first, Workers AI as the fallback, run from the Worker's own cron. It amends ARCHITECTURE §9 and §10, which kept LLM evaluation out of the MVP.

## Context

M24 made the Python score tell offers apart (docs/diagnostics/m24-scoring.md): title families, a veto for other trades, skills asked for in the profile section weighed more, thresholds recalibrated (strong 80, digest 55).

It filters well for recall, but a rule still can't read:
- that a "DevOps" title is a level-2 support job;
- that a stack is legacy;
- that the experience asked for is hidden in a sentence.

A model can read that for the offers that pass the filter each day (about a hundred). The verdicts and my Tri decisions, side by side, show where the rules and the model disagree.

Constraints (CLAUDE.md):
- **Dependency:** the core works without it. Nothing blocks the dashboard, the digest or the run.
- **Engines:** never a blind average with the Python score. A gap is a signal.
- **Data:** nothing personal leaves. The offer text is public; the profile is not.
- **Content:** offer text is untrusted and never executed.
- **Changes:** nothing is applied to the config automatically.
- **Cost:** the original "free only" constraint is amended: the Claude API costs about one dollar a month at the volumes below, and it answers in structured JSON that Llama does not guarantee. Workers AI stays, free, as the fallback.

## Decision

1. **Where it runs: the Worker's cron, not the daily run.**
   - `wrangler.jsonc` `triggers.crons: ["30 7 * * *", "30 9 * * *"]`: thirty minutes after the daily run (07:00 UTC) that rebuilds and deploys the site, and once more two hours later to catch a late run. The content cache makes the second pass free when nothing is new, and `ai_usage` is per day, so the cap covers both. The handler is `scheduled` in `worker/src/index.js`, the logic `worker/src/ai.js`.
   - **Why the Worker.** D1 holds no offer text, but the deployed site does: `data.json` carries every listed offer with `description_excerpt` (plain text, 5000 characters at most), its Python score, section and `ai_hash`. The cron reads it through the assets binding (`env.ASSETS.fetch`), so no offer text transits through the public CI log and no new CI step or secret is needed. The API key was already a Worker secret.
   - **Candidates:** the listed offers with a Python score at or above `digest.min_score`, best score first, without a verdict for their current content and prompt version. Rejected offers never reach `data.json`, so they are never sent.
   - **Daily cap:** the wrangler var `AI_DAILY_LIMIT` (100 calls a day, retries included, counted in `ai_usage`); `DAILY_LIMIT` in `ai.js` is only its fallback. `vars` may carry such knobs, never an Access identifier nor a key (`test_wrangler_config.py`). `config/settings.yaml ai:` repeats the values for the Python report, and `tests/unit/ai/test_worker_constants.py` keeps both sides equal.
   - **Every run is recorded** in `ai_runs(started_at, finished_at, outcome ok|stopped|no_profile|failed, http_status, provider, counters)`, shown as « Rerank IA » at the top of the Exécutions view (live from `/api/applications`).
2. **Providers, in order.**
   1. **The Claude API, `claude-haiku-5-5`** (checked 2026-10-25 against the claude-api reference: $0.10 per million input tokens, $0.50 per million output, prompts up to 100K; cache reads about a tenth of the input price). The call is a plain `fetch` to `/v1/messages` with `anthropic-version: 2026-10-21`, no SDK (the Worker has no dependencies). `output_config.format` is a strict JSON schema (`additionalProperties: false`, every key required); ranges and lengths are not expressible there, so the Worker validates them. `output_config.effort: "low"`: this is a classification. No `temperature`, no prefill, no thinking parameter: the model's defaults.
   2. **Workers AI, `@cf/meta/llama-3.3-70b-instruct-fp8-fast`** (binding `AI`), in `json_schema` mode, **for the rest of the run** once the API answers 402 (`billing_error`), a 400 that names the credit balance, or 429. Its JSON is not guaranteed, so the same validation applies. Its free allocation (10 000 neurons a day) covers about 120 offers.
   3. **Nothing.** A 5xx is retried once, then the offer is skipped; a refusal is not retried; an invalid JSON answer is retried once, then the offer is skipped. Without a key and without the binding, the cron counts an error and stops. The Python score stays the order.
   - **Any other 4xx stops the run** (401 bad key, 404 unknown model, 400 refused schema, 413…): it is not a quota, so neither a retry nor the fallback would help. The run row keeps `outcome = stopped` and the HTTP status alone (never the message), the log line reads `ai rerank stopped http=404 {counters}`, and the Exécutions view shows the status in red.
   - **Smoke test** (`scripts/ai-smoke.mjs`): a local `wrangler dev --test-scheduled` with `--var AI_DAILY_LIMIT:3` makes three real calls (the Claude API through the outgoing fetch, Workers AI with `--fallback`, which sets `AI_PROVIDER=workers_ai`: in local dev Workers AI always runs remotely), writes the rows in the local D1 and prints counters only. The production D1 is never touched (`remote` is forbidden on the binding).
3. **Verdict.** A strict JSON object:
   ```json
   {"relevance": 0-100, "level": "fort|tenter|hors_sujet",
    "reasons": ["…"], "red_flags": ["…"]}
   ```
   - `reasons` and `red_flags` hold at most 3 strings of 160 characters each; anything else (an extra key, a fraction, a string score) is thrown away, never patched.
   - **Storage, D1** (`worker/migrations/0004_ai_verdicts.sql`): `ai_verdicts(job_key, hash, provider, model, prompt_version, score, level, reasons, red_flags, created_at)`, unique on `(job_key, hash, prompt_version)`; `ai_usage(day, provider, calls, tokens_in, tokens_out)`, counters only; `disagreements` (point 5).
   - **Never averaged.** The dashboard shows both scores; the Python ledger does not change.
4. **Cache by content.** `data.py` gives each offer `ai_hash = sha256(normalized title + description_excerpt)`. A repost, a duplicate or a reprocess keeps its hash, so it costs nothing; a changed description gets a new verdict. The prompt version lives in the verdict row: bumping `PROMPT_VERSION` (and `settings.yaml ai.prompt_version`) makes every offer a candidate again without erasing history.
5. **Disagreements, computed by the Worker** when the verdict lands (the Python score is in `data.json`):
   - `gap` when |AI − Python| > `DISAGREEMENT_GAP` (25);
   - `off_topic_strong` when the model says `hors_sujet` on an offer the Python score calls strong.
6. **What is sent.** Only:
   - the offer's title, employer, contract, required years and plain description, between `<offre>` delimiters, with the instruction that the text is data and any instruction inside it is ignored;
   - an **anonymous skills summary** (`src/job_match/ai/summary.py`): preferred skills with a band (fort / moyen), negative skills, years of experience, accepted contract types, and `mobility` = `france` or `departements`, never the codes.

   The summary is generated in CI from the profile secret and written by `write_site` to `site/ai-profile.json`, a file behind Access that only the cron reads: it is never embedded in the page nor in `data.json`. Without it the cron sends nothing. `tests/unit/ai/test_summary.py` checks that only the allow-listed keys come out, and that a profile full of traps (name, email, phone, URL, city, department codes, search keywords) leaks nothing.
7. **Prompt caching.** The system block (the barème, the rules, the summary with sorted keys) is one `cache_control: ephemeral` block, byte-identical from one call to the next and longer than the 512-token minimum, so every offer of the day reads it from the cache.
8. **Security and logs.** The Worker never logs the key, a prompt or an answer: `ai.js` has no `console` call at all, and `scheduled` logs the counters only (`eligible, candidates, cached, scored, invalid, refused, skipped_cap, fallback, errors, skipped_no_profile, disagreements`). A test spies on `console.log` and checks that neither the key, nor the offer, nor a reason appears.
9. **Dashboard.** `GET /api/applications` also returns `ai_verdicts` (the latest per offer), so a verdict shows the same morning:
   - the Tri is ordered by the AI score when there is one, the Python score otherwise (`triage.js rankScore`), after the "Nouveau" rows;
   - an offer the model calls `hors_sujet` leaves the Tri and the sidebar count, and stays in Offres behind the « Avis de l’IA » filter (`ia=` in the hash);
   - the card shows an « IA 84 » badge, and the « Relevé » and the record panel a « Selon l’IA » block (score, level, reasons, red flags), labelled as the model's opinion;
   - a verdict whose hash no longer matches the offer is ignored (`triage.js aiOf`).
10. **Mirror.** The daily run's « Export tracking » step also exports the three tables, and `job-match tracking import --ai-verdicts --ai-usage --disagreements` replaces the SQLite mirror (`migrations/0010_ai_mirror.sql`), validated row by row like the tracking tables. The mirror is a day behind (the export runs before the pipeline); only the report reads it.
11. **Improvement loop (weekly, read-only).** `job-match ai-report [--since] [--out]` (`src/job_match/ai/report.py`) ranks seven days of disagreements (a `hors_sujet` on a strong offer first, then the largest gap), joins my latest Tri verdict on each, groups by title family and by the profile skills counted, prints the usage and an upper bound of the Claude cost, and writes a **correction prompt for Claude Code**: the 10 largest disagreements (title, both scores, the model's reasons, whom my verdict sides with) and the question "which `title_relevance` lists or weights explain them? Propose a diff to config/settings.yaml with a test; do not apply it." It writes `data/ai-report-<date>.md`, local and uncommitted. Nothing is applied automatically.
12. **Out of scope:** emails written by the AI, application or cover-letter drafts, CV generation.

## Cost (production base: about 100 offers a day at or above the digest threshold)

Per Claude call: the system block about 1 200 tokens, read from the cache; the offer about 2 000 tokens (the Haiku 5.5 tokenizer counts about 30 % more than the previous one); about 150 output tokens.

| | a call | a day (100) | a month |
|---|---|---|---|
| input, $0.10 / M | $0.0002 | $0.02 | $0.60 |
| output, $0.50 / M | $0.00008 | $0.008 | $0.23 |
| cache read, about $0.01 / M | $0.00001 | $0.001 | $0.04 |
| **total** | **about $0.0003** | **about $0.03** | **about $0.90** |

The one cache write a day is negligible. Workers AI as the fallback: about 80 neurons an offer, 100 offers about 8 000 of the 10 000 free neurons. `ai_usage` holds the real counts, and the weekly report prints the bound.

## Alternatives

- **The daily run calls the model (the first draft of this ADR).** It has the profile but would send offer text from a public CI log context, needs a second copy of the API key as a GitHub secret, and the dashboard would see verdicts a day late. Rejected.
- **A D1 queue filled by the daily run.** One `wrangler d1 execute` per offer, with the text in the command line. Slower, and the text transits the CI. Rejected.
- **The Python SDK or the TypeScript SDK in the Worker.** The Worker has no dependencies on purpose; the request is one documented JSON body. Rejected for now.
- **Workers AI first (the first draft).** Free, but its JSON mode is not guaranteed and the daily allocation would cap the day. Kept as the fallback.
- **Gemini free tier.** Its terms allow product improvement on the content. Dropped.
- **GitHub Models.** Retired on 2026-07-30.
- **Let the AI score replace the Python score.** Breaks "the core works without it" and "no blind averaging". Rejected.

## Consequences

- **New pieces:** `worker/src/ai.js`, the `scheduled` handler, migration 0004 (D1) and 0010 (SQLite), `triggers` and the `AI` binding in wrangler.jsonc, `ai/summary.py`, `ai/report.py`, `job-match ai-report`, the `--ai-*` import flags, `ai-profile.json`, the `ai:` settings block, and the dashboard's badge, block, order and filter.
- **Secrets and vars:** `ANTHROPIC_API_KEY` (set through wrangler); `AI_DAILY_LIMIT` is a wrangler var. `AI_PROVIDER` exists for the smoke test only (`--var`). No new GitHub secret.
- **Tests:** 25 Node tests for `ai.js` and the API (mocked `fetch` and `env.AI`: request shape, cache by hash and prompt version, daily cap, 402 / 400-credit / 429 fallback, Workers AI failing too, retries, refusals, disagreements, no profile, the log), the triage order and the `hors_sujet` exclusion; Python tests for the summary's anonymity, the mirror validation, the hash, the separate profile file, the workflow step, the constants agreement and the report. No test calls a real API.
- **Timing:** the cron sees the previous deploy if the daily run overruns 30 minutes; it then judges that snapshot and catches up the next day. Acceptable.
- **Product:** a second opinion per offer the same morning, a Tri ordered by it, and a weekly prompt that turns disagreements into rule fixes I approve.

## Sources (checked 2026-10-25)

- Claude API reference bundled with Claude Code (claude-api skill, cached 2026-10-06): model ids and prices, `output_config.format`, prompt caching minimums, error codes.
- Workers AI pricing and free allocation: <https://developers.cloudflare.com/workers-ai/platform/pricing/>
- Workers AI JSON mode: <https://developers.cloudflare.com/workers-ai/features/json-mode/>
- Workers AI data use: <https://developers.cloudflare.com/workers-ai/platform/privacy/>
- GitHub Models retirement: <https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models>
