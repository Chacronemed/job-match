-- Dedup blocks stored, not recomputed (2026-11-04 performance pass): `_block` used to read
-- every row of the window and normalize its title and location in Python for each new
-- posting (2.9 s of a 5.5 s run on 3 000 stored jobs). The two keys are written at save time
-- and backfilled once for older rows (persistence/db.py), so SQL does the narrowing.
ALTER TABLE jobs ADD COLUMN title_normalized TEXT;
ALTER TABLE jobs ADD COLUMN location_dept TEXT;
CREATE INDEX IF NOT EXISTS jobs_title_block ON jobs(title_normalized, collected_at);
-- The digest, the dashboard and the closure check all read canonical eligible jobs by
-- score: one index serves the three, and the LEFT JOIN on duplicates stops scanning.
CREATE INDEX IF NOT EXISTS jobs_eligibility_score ON jobs(eligibility, score DESC, collected_at DESC);
DROP INDEX IF EXISTS jobs_eligibility;  -- subsumed: with it the planner kept sorting in a temp b-tree
CREATE INDEX IF NOT EXISTS job_duplicates_duplicate ON job_duplicates(duplicate_job_id);
