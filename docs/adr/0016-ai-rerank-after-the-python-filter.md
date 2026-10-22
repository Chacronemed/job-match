# ADR 0016: an AI rerank after the Python filter (design only)

**Status:** proposed (2026-10-22, M24). Nothing is implemented. It amends ARCHITECTURE §9, which rejected LLM evaluation for the MVP.

## Context

M24 made the Python score tell offers apart (docs/diagnostics/m24-scoring.md):
- title families, a veto for other trades, skills asked for in the profile section weighed more;
- thresholds recalibrated: strong 80, digest 55.

It filters well for recall, but a rule still can't read:
- that a "DevOps" title is a level-2 support job;
- that a stack is legacy;
- that the experience asked for is hidden in a sentence.

A model can read that for the few offers that pass the filter each day. The verdicts in D1 and the weekly review give a way to see where the rules and the model disagree.

Constraints (CLAUDE.md):
- **Cost:** free only.
- **Dependency:** the core works without it.
- **Engines:** never a blind average with the Python score.
- **Data:** nothing personal leaves.
- **Content:** offer text is untrusted and never executed.
- **Changes:** nothing is applied to the config automatically.

## Decision

1. **Where it runs.** A new step in the daily workflow, after scoring and before the digest. It is an optional engine `ai`, off by default (`settings.yaml ai.enabled: false`).
   - **Candidates:** the offers of the run that pass the gate with a score ≥ `digest.min_score`, best score first.
   - **Daily budget:** at most `ai.daily_limit` new calls (20 to start).
   - **Rejected offers** are never sent.
2. **Verdict.** A strict JSON object, validated against a schema; anything else is discarded:
   ```json
   {"relevance": 0-100, "level": "junior|confirmé|senior|inconnu",
    "reasons": ["…", "…"], "red_flags": ["…"], "prompt_version": "1"}
   ```
   - **Limits:** `reasons` holds at most 3 strings of 160 characters each, and `red_flags` at most 3 (e.g. "support N2 déguisé", "astreinte 24/7 non mentionnée dans le titre").
   - **Storage:** a separate engine in `job_scores` (`engine="ai"`), alongside `native`, as ARCHITECTURE §9 planned for JMS. It is **never averaged** with the Python score.
   - **Divergence:** a gap of at least `divergence_threshold` between the two sets `needs_review` (the existing `ScoringEngine` logic), and the dashboard shows both.
   - **What the verdict never changes:** the gate, the score, or the digest's selection.
3. **Cache by offer hash.** The key is sha256(normalised title + plain description + model id + prompt version + skills-summary hash).
   - **Storage:** a new table `ai_verdicts(hash PRIMARY KEY, model, prompt_version, result_json, created_at)` in the private DB. `job_scores` points to it.
   - **No resend:** a known hash is never sent again, so a repost, a duplicate or a reprocess costs nothing.
   - **Invalidation:** a prompt or model change bumps `prompt_version` and invalidates on purpose.
4. **Provider: Cloudflare Workers AI, `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, in JSON-schema mode.**
   - **Free allocation.** It is free within 10 000 neurons a day, reset at 00:00 UTC; on the free plan, requests fail once it is spent.
   - **Cost per offer.** At the published rates (26 668 neurons per million input tokens, 204 805 per million output), one offer is about 1 500 tokens in and 200 out, roughly **80 neurons**.
   - **Daily volume.** 20 offers is about 1 600 neurons (16 % of the free day), and the allocation would cover about 120.
   - **JSON mode** (`response_format: json_schema`) is documented for this model. Compliance is not guaranteed, so schema validation stays mandatory.
   - **Data.** Cloudflare states that customer content (prompts, outputs) is not used to train or improve models without explicit consent.
   - **Account.** The project already runs a Worker and D1 on Cloudflare: same account, plus one new secret, `CF_AI_TOKEN`, scoped to Workers AI only. It is not the D1 token.
5. **Daily cap and fallback.**
   - **Hard cap:** `ai.max_calls_per_day` (40, retries included).
   - **Fallback:** past the cap, on HTTP 429, on a "neurons exhausted" error, a timeout or two invalid JSON answers, the offer keeps its Python score alone.
   - **Visibility:** the run summary counts `ai_scored`, `ai_cached`, `ai_skipped_quota` and `ai_invalid`, counts only (the CI log is public).
6. **What is sent.** Only:
   - the offer's title and plain description, which are public data;
   - an **anonymous skills summary** generated from the profile: preferred skills with their weight band (fort / moyen), negative skills, years of experience, accepted contract types.
   
   Never the name, email, city, notes, CV or verdicts. A unit test checks that the summary has only those keys, and that no email, phone, URL or `location_scope` value appears in it.
7. **Prompt injection.**
   - **Framing:** the offer text is placed between explicit delimiters, with the instruction that it is data and that any instruction inside it is ignored.
   - **Validation:** the output is only a validated JSON verdict, which never runs anything and never changes a gate.
   - **Red flags:** a verdict whose `reasons` or `red_flags` repeat text injected into the offer is shown as is, labelled "selon l'IA".
8. **Improvement loop (weekly, read-only).** A report ranks the disagreements:
   - the AI relevance band vs the Python section (strong / eligible / below the digest);
   - each of them vs my Tri verdicts (the D1 mirror).
   
   It groups them by title family and by the skills involved, and writes a **correction prompt for Claude Code**: the 10 largest disagreements (title, both verdicts, the AI's reasons) and the question "which `title_relevance` lists or weights would explain them? Propose a diff to config/settings.yaml with a test; do not apply it."
   - **Where it lives.** It runs locally (`job-match ai-report`, like `calibrate`) or in the private data repo, never in the public CI log or repo.
   - **Review.** I read it, then hand it to Claude Code if I want. Nothing is applied automatically.
9. **Out of scope:** emails written by the AI, application or cover-letter drafts, CV generation.

## Provider comparison (checked 2026-10-22)

| | Cloudflare Workers AI | Gemini API, free tier | GitHub Models |
|---|---|---|---|
| Status | available | available | **retired on 2026-07-30** (GitHub docs) |
| Free quota | 10 000 neurons / day, about 120 offers with Llama 3.3 70B, about 750 with Llama 3.1 8B fp8-fast | per project, shown only in AI Studio; secondary sources give about 10 req/min and 500–1 500 req/day for Flash; Pro is no longer free | — |
| Structured output | `json_schema` mode on the listed models | JSON / schema output | — |
| Data use | not used for training without consent | the free tier may use content to improve Google's products, with human review; the paid tier does not | — |
| From GitHub Actions | REST call with a scoped API token | REST call with an API key | — |
| Fit | same account as the Worker and D1, one more scoped secret | a second vendor and key | none |

**Order:**
1. Workers AI.
2. Gemini 2.x / 3.x Flash on the free tier as an **opt-in** second provider (`ai.fallback_provider: gemini`, off by default). It would only receive the public offer text and the anonymous summary, but its free terms allow product improvement on that content.
3. The Python score alone.

Quotas change often. The implementation reads them from config, never from code, and the run summary shows when the cap is hit.

## Alternatives

- **No AI, more rules.** That is what M24 does first. Rules can't read context ("support N2 déguisé"), so they stay the filter and the AI reranks the top only.
- **AI on every offer.** About 7 000 a fortnight, far above any free quota, and most are rejected by the gate anyway.
- **Let the AI score replace the Python score.** That breaks "the core works without it" and "no blind averaging". Rejected.
- **A paid model.** It would be more reliable JSON, but it contradicts the free constraint; it could be revisited if Workers AI quality is poor.
- **GitHub Models** (the original candidate for Actions): it has been retired, so it is no longer an option.

## Consequences

- **New pieces:** a migration (`ai_verdicts`), an `ai` config block, a secret `CF_AI_TOKEN`, one workflow step, `job-match ai-report`, and tests (schema validation, cap and fallback, anonymity of the summary, cache hits) with a mocked provider. The tests never call a real API.
- **Volume and timing:** the daily run gains at most 20 to 40 calls of about 1–3 s each, and the run stays correct when the provider is down.
- **Product:** the dashboard gets a second opinion per offer, and the weekly report gets a source of rule fixes that I approve.

## Sources (checked 2026-10-22)

- GitHub Models retirement: <https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models>
- Gemini API rate limits (quotas shown in AI Studio, page updated 2026-10-15): <https://ai.google.dev/gemini-api/docs/rate-limits>
- Gemini free-tier data use (secondary): <https://ampm-aiops.com/en/guides/gemini-free-tier-data-tradeoff-2026/>, <https://meetily.ai/llm-privacy/gemini>
- Gemini free-tier limits (secondary, they disagree): <https://klymentiev.com/blog/gemini-api-free-tier>, <https://www.scriptbyai.com/gemini-api-rate-limits/>
- Workers AI pricing and free allocation: <https://developers.cloudflare.com/workers-ai/platform/pricing/>
- Workers AI JSON mode: <https://developers.cloudflare.com/workers-ai/features/json-mode/>
- Workers AI data use: <https://developers.cloudflare.com/workers-ai/platform/privacy/>
