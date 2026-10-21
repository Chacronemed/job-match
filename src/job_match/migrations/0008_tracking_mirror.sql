-- Read-only mirror of the D1 tracking tables (worker/migrations/0001_tracking.sql), replaced
-- wholesale by `job-match tracking import` before each digest. D1 is the source of truth.
CREATE TABLE IF NOT EXISTS applications (
    job_key      TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    applied_at   TEXT,
    follow_up_at TEXT,
    note         TEXT,
    cv_url       TEXT,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id                INTEGER PRIMARY KEY,
    job_key           TEXT NOT NULL,
    label             TEXT NOT NULL,
    score_at_decision INTEGER,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_job_key ON decisions(job_key);
