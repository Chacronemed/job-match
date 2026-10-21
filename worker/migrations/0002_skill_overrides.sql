-- D1: skills I marked "je maîtrise" on the dashboard. The jobs pipeline merges them into
-- the profile as preferred skills (scoring.override_weight); mirrored read-only by
-- src/job_match/migrations/0009_skill_overrides_mirror.sql.
CREATE TABLE skill_overrides (
    skill      TEXT PRIMARY KEY CHECK (length(skill) <= 40),
    created_at TEXT NOT NULL
);
