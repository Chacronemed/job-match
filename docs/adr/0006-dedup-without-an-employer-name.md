# ADR 0006 — Dedup when the employer is hidden

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

3. **The department is the blocking key, via `normalization.block_location`**
   (`department_of(location)`, falling back to the normalized text for "France", "Télétravail" or a
   town `fr_geo` does not list). Two departments are two offers. It also makes the key
   source-independent: France Travail's `"35 - Rennes"` and Jooble's `"Rennes, France"` both give
   `"35"`.

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
   `RunSummary.duplicates` now means "new links found" in a reprocess too; self-links removed moved
   to `RunSummary.self_links_dropped`. Each new link is logged with ids only — the daily workflow
   runs this step in a public Actions log.

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

## Consequences

- On the real DB the replay found **2** new links (160 → 155 and 200 → 155, the latter missed because
  both arrived in one run), taking the digest pool from 83 to 81 canonical eligible jobs. The one
  remaining same-title/same-department pair is two *named* employers whose descriptions are 57%
  similar: two genuinely different offers, correctly kept.
- Employer-hidden postings whose normalized titles differ slightly (one says "Senior") are no longer
  compared, where the old `""` block would have caught them. The exact title is the price of a block
  that respects location; `block_location` tightened the far bigger hole.
- Linking a hidden posting to a named one records a canonical whose employer is known — which is the
  better row to keep: it is the one you can apply to.
- Running `reprocess` writes duplicate links to the production DB (the daily workflow's
  `reprocess_scope: jobs` step included). That is the point: the DB is cleaned where the digest reads
  it.
