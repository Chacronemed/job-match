-- Read-only mirror of the D1 `skill_overrides` table (worker/migrations/0002_skill_overrides.sql):
-- skills I marked "je maîtrise" on the dashboard. Replaced with the other tracking tables by
-- `job-match tracking import`; the jobs pipeline merges them into the profile.
CREATE TABLE IF NOT EXISTS skill_overrides (
    skill      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
