-- D1: a new verdict, "location" (the offer is in the wrong place), picked after a left swipe in
-- the triage view. SQLite cannot change a CHECK constraint in place, so the table is rebuilt.
CREATE TABLE decisions_new (
    id                INTEGER PRIMARY KEY,
    job_key           TEXT NOT NULL,
    label             TEXT NOT NULL CHECK (label IN
                        ('good_fit', 'off_topic', 'too_senior', 'missing_skill', 'location')),
    score_at_decision INTEGER,
    created_at        TEXT NOT NULL
);
INSERT INTO decisions_new (id, job_key, label, score_at_decision, created_at)
    SELECT id, job_key, label, score_at_decision, created_at FROM decisions;
DROP TABLE decisions;
ALTER TABLE decisions_new RENAME TO decisions;
CREATE INDEX idx_decisions_job_key ON decisions(job_key);
