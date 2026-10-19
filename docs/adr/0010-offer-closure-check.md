# ADR 0010 — Offer closure check and posting-age cut-off

**Status:** accepted (2026-10-19)

## Context

The digest and the dashboard showed offers that were no longer online. Nothing ever asked a
source whether a stored offer still existed, and both views listed every canonical ELIGIBLE
or STRETCH row whatever its age. France Travail offers are fetched inside a 3-day window and
then kept forever.

Measured first (`scripts/ft_closed_probe.py`, read-only, 1 token call + 9 then 10 detail
calls on the oldest visible offers of the local DB, `GET /partenaire/offresdemploi/v2/offres/{id}`):

| collected | published | answer |
|---|---|---|
| 2026-10-02 (8 offers) | 09-07 … 10-01 | 5 × **HTTP 204** (empty body), 3 × 200 JSON |
| 2026-10-11 (2 offers) | 09-22, 10-02 | 1 × 204, 1 × 200 JSON |

A closed offer answers **204 No Content**. An open offer answers 200 with the full offer; the
only lifecycle fields are `dateCreation` and `dateActualisation`, there is no status field.
No 404 or 410 was observed. 6 of the 10 oldest visible offers were already gone.

## Decision

1. **Two lifecycle columns on `jobs`** (migration 0006): `closed_at` and `last_checked_at`,
   nullable ISO-8601 UTC. They are not fields of the `Job` dataclass, like `notified_at`:
   they describe what we know about the offer, not the offer. `JobRepository.save` never
   writes them, so a re-collection or a reprocess keeps them.
2. **`FranceTravailSource.check_offer(source_job_id) -> OfferStatus`**: one throttled call
   to the detail endpoint with the search's token and rate limit. 200 → OPEN. 204 → CLOSED
   (measured). 404 → CLOSED too: it means "no such resource" and was not observed, so it is
   read as gone rather than retried every day. Anything else — a refused request, 429 or 5xx
   after the client's retries, a timeout, a transport error — is UNKNOWN. `check_offer` is
   optional on the `JobSource` protocol; Jooble and Adzuna do not implement it.
3. **`pipelines/closure.check_closed`** runs inside `job-match run` after collection. It asks
   about every visible job (canonical, ELIGIBLE or STRETCH, not closed, inside the age
   cut-off) whose source has `check_offer` and that was not checked in the last 24 hours
   (a module constant: the run is daily). CLOSED sets `closed_at`, OPEN sets
   `last_checked_at`, **UNKNOWN changes nothing**: a network error never closes a job. A
   source that cannot be asked at all (no token) stops the check after one warning. Rows
   the search itself returned are marked open without a call. Check calls count in
   `api_calls`; `RunSummary.checked` / `closed` are stored and printed.
4. **The views hide closed jobs**: `list_unnotified` (digest) and `list_canonical_scored`
   (dashboard) add `closed_at IS NULL`, and a lead's open-jobs count ignores closed jobs.
   Nothing is deleted or re-scored.
5. **`jobs.max_age_days: 45`** (settings.yaml) is the safety net for offers that were never
   checked: a posting date — the collection date when the source gave none — older than
   this is hidden from both views, and no call is spent on it.
6. **The dashboard shows the posting date and an age in days** instead of the collection
   date (`posted_at`, `age_days` as of `generated_at`; the page is a daily snapshot).

## Alternatives considered

- Deleting closed rows: breaks dedup history and the run funnel; against rule 7 (never delete).
- Re-fetching the whole window to infer closure from absence: an offer can drop out of the
  search for other reasons (ranking, window), and the search window is 3 days anyway.
- A closed status inside the `Job` model: the model is the offer as the source published
  it; lifecycle state belongs next to `notified_at`.
- Making the 24 h interval a setting: there is nothing to tune on a daily run.

## Consequences

- First local run after the change: 104 offers checked, 39 closed (37 %), 0 unclear, 119
  API calls in total (15 search + 104 check); 21 more hidden by age alone.
- Each daily run spends roughly one check call per visible job not returned by that day's
  search, at the search's rate limit (3 req/s): a few hundred calls, about a minute.
- A job whose check keeps answering UNKNOWN stays visible and is asked again every day
  until the age cut-off hides it. Its count shows in `errors`.
