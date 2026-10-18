# ADR 0006 — Dedup blocks: the employer, and the place

**Status:** accepted (2026-10-16)

## Context

The digest sent the same offer twice: "Ingénieur DevOps — Rennes", same location, no company
name. France Travail publishes some offers without an employer, and the fuzzy dedup block is
`company_normalized`. Measured on the local DB (533 jobs):

- Jobs 155 and 160 shared a normalized title and a department, their descriptions were **98.6%**
  similar, and both were eligible *and* canonical, so both were emailed. One carried an employer
  name, the other did not: `""` and `"acme"` are different blocks, so the pair was never compared.
  The fuzzy comparison was not too strict — it never ran.
- The `""` block is also wrong in the other direction: it put **all 107** employer-hidden postings
  of the window in one block, with no location constraint at all, so two unrelated offers in
  different cities were candidates for each other.

## Decision

1. **With no employer name, the block is the normalized title plus the department**, any company
   (`JobRepository.list_by_title_department`). Then the description decides, with the same
   thresholds (`fuzzy_title_threshold`, `fuzzy_desc_threshold`) as before. The company block cannot
   do this job: every hidden employer shares the same empty name.

2. **A posting that does have an employer also looks at the employer-hidden postings** sharing its
   title and department (`hidden_employer_only=True`), on top of its own company block. Otherwise
   the fix would depend on arrival order: the hidden twin finds the named one, but not the reverse.
   Two *named* employers are never compared on title and department alone — only a hidden employer
   justifies crossing company boundaries.

3. **The department is part of every block, via `normalization.block_location`**
   (`department_of(location)`, falling back to the normalized text for "France", "Télétravail" or a
   town `fr_geo` does not list). It makes the key source-independent: France Travail's
   `"35 - Rennes"` and Jooble's `"Rennes, France"` both give `"35"`.

   **The company block takes the same key** (`list_by_company(company, location_key, since)`): one
   employer hiring in two departments is two offers, however identical the two ads read. It used to
   ignore the location entirely, which hid a posting in Lille behind the same employer's posting in
   Yvelines — and the candidate is mobile across France, so those are two real opportunities.

   `same_block_location` decides when two keys may be one place: two real department codes are two
   places, but a key that is *not* a department code means "we cannot tell" and matches anything.
   Unknown never splits a block, exactly as it never rejects a job in the gate — Jooble often says
   only "France" where France Travail says "92 - Nanterre", and those two postings must stay
   comparable.

4. **A rejected posting is never a dedup candidate** (`pipelines.jobs._usable_candidates`).
   `list_unnotified` hides every duplicate, so an eligible job linked to a rejected canonical would
   disappear from the digest instead of being deduped. The same helper drops the job's own stored
   row (as `_other_postings` already did) and de-duplicates the candidate list.

5. **A match against a row that is itself a duplicate links to that group's canonical**
   (`_canonical_of`), so chains cannot form, and a resolved canonical equal to the job itself is
   skipped rather than written as a self-link.

6. **`job-match reprocess` now replays dedup**, in collection order, for every eligible job that is
   not already a duplicate. It was skipped before ("the links are already stored"), which made the
   fix invisible on data already collected — exactly the data the bug was reported on. The window is
   measured from each job's own `collected_at`, not from today, so the replay asks what the current
   rules would have said when the posting arrived, and candidates are restricted to rows strictly
   earlier in `(collected_at, id)` so the older posting stays canonical.
   **A stored link the current rules no longer make is removed** (`_sync_dedup`,
   `JobDuplicateRepository.delete_link`), and the job goes back to the digest. Keeping it would be
   the original bug upside down: a job hidden by a rule that no longer exists. Where the rules now
   name a different canonical, the stale link is removed and the new one written in the same pass.

   `RunSummary.duplicates` now means "new links found" in a reprocess too; links removed are
   `self_links_dropped` (corrupt self-references) and `stale_links_dropped` (rules no longer match).
   Every change is logged with ids only — the daily workflow runs this step in a public Actions
   log.

## Alternatives considered

- **Keep the `""` block and lower `fuzzy_desc_threshold`.** It would not have found 155/160 at all
  (different blocks), and loosening the description test weakens every other pair.
- **Block on the department alone when the employer is hidden**, letting the fuzzy title test decide.
  More tolerant of near-identical titles, but it compares every hidden posting of a department to
  every other, and cross-company links would rest on title similarity instead of an exact title.
- **A `title_normalized` column with an index**, like `company_normalized`. The block query scans the
  window on three small columns and materializes only the matches, which is nothing at this size
  (533 rows). This is the escape hatch if the window ever grows enough to matter, noted in the
  method's docstring.
- **A dedicated `reason` value for cross-company links** (e.g. `fuzzy_no_company`). The engine does
  not know which block produced a candidate, and the stored pair already shows it. Not worth the
  plumbing.
- **A one-off cleanup script instead of the reprocess replay.** `reprocess` already exists to
  re-apply current rules to stored data, and the daily workflow can trigger it.
- **Leaving stale links in place, and only ever adding.** Then every future blocking change needs a
  manual DELETE, and until it runs the digest silently hides jobs the rules say are distinct.
- **Keeping the company block location-blind and filtering reposts at digest time.** It would move a
  dedup decision into the notifier, where nothing is recorded and nothing is auditable.

## Consequences

- On the real DB (533 jobs), in two passes: the hidden-employer block **added 2** links (160 → 155,
  and 200 → 155 which the original run missed because both arrived in one run), then the
  department-aware company block **removed 2** (200 and 217, THALES postings in Lambersart (59) and
  Rennes (35) that were hidden behind the Yvelines one). The digest pool went 83 → 81 → 83, and both
  surviving links are inside a single department. The remaining same-title/same-department pair in
  the pool is two *named* employers whose descriptions are 57% similar: two different offers,
  correctly kept.
- Employer-hidden postings whose normalized titles differ slightly (one says "Senior") are no longer
  compared, where the old `""` block would have caught them. The exact title is the price of a block
  that respects location; `block_location` tightened the far bigger hole.
- Linking a hidden posting to a named one records a canonical whose employer is known — which is the
  better row to keep: it is the one you can apply to.
- An employer who reposts one ad in six departments now gives six digest entries. That is the point
  (six places to work), and the alternative hid five of them.
- Running `reprocess` writes duplicate links to the production DB (the daily workflow's
  `reprocess_scope: jobs` step included). That is the point: the DB is cleaned where the digest reads
  it.
