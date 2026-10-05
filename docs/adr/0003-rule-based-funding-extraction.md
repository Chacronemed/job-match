# ADR 0003 — Rule-based funding extraction with per-field evidence

**Status:** accepted (M11, 2026-10-04)

## Context

M10 ingests articles and keeps only a short extract. M11 must turn the in-memory article text
into `FundingEvent`, `Company` and `Lead` rows. The brief (§12–13) and CLAUDE.md rule 9 forbid
inventing any amount, round, investor or hiring claim. The repo is public and the pipeline runs
unattended, so every stored fact must be auditable.

## Decision

1. **Deterministic FR/EN regex extractor, no LLM** (`funding/extractor.py`, pure functions).
   Compiled pattern tables with example comments, in the style of `experience/parser.py`.
2. **Unknown = `None`.** An amount needs an explicit number + unit + currency and must sit in a
   clause free of revenue/valuation/total/debt words. Investors need an explicit cue
   ("mené par", "auprès de", "led by", ...). A hiring signal needs an explicit phrase.
   Sentences in the past perfect ("avait levé", "after raising") and VC fund closes
   ("pour son deuxième fonds", "fund II") are never the funding sentence.
3. **Evidence per field.** `FundingExtraction.evidence` maps each non-null field to the sentence
   it came from (≤300 chars) and is persisted as `funding_events.evidence_json`.
4. **One event per article** (M11). The first sentence with a recognisable company anchors the
   extraction; facts are taken from that sentence and the ones after it, so a roundup's summary
   line ("dix startups ont levé 52,8 M€") never contaminates the first deal. Multi-deal roundups
   are deferred to M11b.
5. **Company = capitalised run before the funding verb**, with descriptor prefixes ("La startup",
   "Paris-based") and trailing fillers ("annonce aujourd'hui un") stripped, matched to
   `companies` via the shared `normalize_company`. Lowercase brands are not recognised by design.
   A funding article with no company is flagged `is_funding=1` but gets no event and no lead,
   and is counted as `funding_no_company`.
6. **Lead rule.** One lead per event; `priority = high` iff a hiring signal exists; no second lead
   for the same company within `funding.lead_dedup_days` (default 30). Re-extraction updates
   reason/priority only and preserves `status`, `created_at`, `notified_at`.
7. **Idempotent reprocess.** `articles.processed_at` marks extraction; `job-match funding
   reprocess` handles `NULL` rows by default and `--since DATE` re-extracts in place thanks to
   `UNIQUE(funding_events.article_id, company_id)` and `UNIQUE(leads.funding_event_id)`.

## Alternatives considered

- LLM extraction: better recall on odd phrasing, but non-deterministic, costs money per run,
  and cannot be audited sentence by sentence. Out of scope for the MVP (ARCHITECTURE §14).
- Store the full text and extract later: forbidden by brief §13 and unnecessary since the text
  is in memory during the fetch.
- Placeholder company for unidentified startups: would create fake leads. Rejected.
- Event per deal line for roundups: more leads, higher false-positive risk. Deferred to M11b
  until precision is measured on live data.

## Consequences

- Migration `0004_funding_extraction.sql`; `Article.is_funding/processed_at`,
  `FundingEvent.id/article_id/evidence`, `Lead.id/priority`; `RunSummary` gains
  `funding_articles`, `funding_events`, `funding_no_company`, `leads_deduped`, `by_source`.
- `WORD_NUMBERS` moved to `normalization/numbers.py` and shared with the experience parser.
- The `funding_no_company` rate on real data is the metric to watch before M11b.
