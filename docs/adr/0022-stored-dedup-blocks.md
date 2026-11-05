# ADR 0022: dedup blocks stored at save time, one commit per posting, memoized normalizers

**Status:** accepted, 2026-11-04

## Context

A profiled daily run (`scripts/profile_daily_run.py`: 466 new postings, 3 000 stored over 30
days, cProfile plus a SQL statement counter) took 5.50 s and 7 464 statements. 2.9 s of it was
`JobRepository._block`: for every new posting it read every row of the dedup window and
normalized its title and location in Python (123 709 `normalize_text` calls), because the two
keys were computed by our code and SQL could not filter on them. The rest: three commits per
posting (1 473 for 466), one `INSERT OR IGNORE INTO sources` per saved row (1 936), the id
re-read after each upsert, and the scoring breakdown JSON parsed for every dedup candidate.

## Decision

1. **`title_normalized` and `location_dept` columns** (migration 0012), written by `save`
   and backfilled once for older rows on connect (`backfill_blocks`, one query when there is
   nothing left to do). `_block` narrows in SQL with the same rule as `same_block_location`:
   a department only blocks with itself and with rows whose place names no single department;
   a key that is no department blocks with everything. Index `jobs(title_normalized,
   collected_at)`.
2. **Candidates without their breakdown:** `_block` selects every column but
   `scoring_breakdown` (read as NULL); dedup compares titles, descriptions and fingerprints.
3. **One commit per posting:** the company upsert and the raw payload are committed with the
   job they belong to. `save` reads the id with `RETURNING`.
4. **Sources registered once per repository** (a set per instance, never module-level: it
   would outlive the connection).
5. **Memoized normalizers** (`normalize_text`, `normalize_title`, `normalize_company`,
   `departments_for`, `lru_cache(4096)`): the same title, company and place are normalized
   several times per posting (fingerprint, blocks, save, scoring).
6. **Digest and closure indexes:** `jobs(eligibility, score DESC, collected_at DESC)` replaces
   `jobs(eligibility)`, and `job_duplicates(duplicate_job_id)` turns the LEFT JOIN's scan into
   a search.

Scores are unchanged by construction and by test: `tests/unit/pipelines/test_golden_scores.py`
runs 80 fixture postings through the real pipeline with the committed config and compares every
verdict, score, explanation and duplicate link with `tests/fixtures/golden_scores.json`,
recorded before this pass.

## Measured (same fixture, medians of three runs)

| | before | after |
|---|---|---|
| wall time, one daily run | 5.50 s | 2.00 s |
| SQL statements | 7 464 | 3 949 |
| commits | 1 473 | 541 |
| `_block` cumulative | 2.89 s | 0.61 s |
| `normalize_text` calls | 123 709 | 399 |
| digest query (668 rows) | 46 ms | 44–71 ms (unchanged: row parsing) |
| dedup title block plan | SEARCH by `collected_at` | SEARCH by `jobs_title_block` |
| branch coverage scoring + eligibility + dedup | 99 % (one branch) | 100 % |

Not done: the digest's `ORDER BY` still sorts in a temp b-tree because `eligibility IN (...)`
spans two index ranges; at 668 rows the sort is not measurable. Commits could be batched
further, but one commit per posting keeps a crashed run's partial work.
