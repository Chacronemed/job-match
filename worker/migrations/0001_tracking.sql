-- D1: my actions on offers. The jobs SQLite DB mirrors these tables read-only
-- (src/job_match/migrations/0008_tracking_mirror.sql). job_key = "<source>:<source_job_id>".
CREATE TABLE applications (
    job_key      TEXT PRIMARY KEY,
    status       TEXT NOT NULL CHECK (status IN
                   ('to_review', 'to_apply', 'applied', 'interview', 'rejected', 'ignored')),
    applied_at   TEXT,
    follow_up_at TEXT,
    note         TEXT CHECK (note IS NULL OR length(note) <= 2000),
    cv_url       TEXT,
    updated_at   TEXT NOT NULL
);

CREATE TABLE decisions (
    id                INTEGER PRIMARY KEY,
    job_key           TEXT NOT NULL,
    label             TEXT NOT NULL CHECK (label IN
                        ('good_fit', 'off_topic', 'too_senior', 'missing_skill')),
    score_at_decision INTEGER,
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_decisions_job_key ON decisions(job_key);
