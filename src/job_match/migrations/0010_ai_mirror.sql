-- Read-only mirror of the D1 AI rerank tables (worker/migrations/0004_ai_verdicts.sql),
-- replaced wholesale by `job-match tracking import` like the tracking tables. Only
-- `job-match ai-report` reads them; the dashboard gets the verdicts live from the Worker.
CREATE TABLE IF NOT EXISTS ai_verdicts (
    id             INTEGER PRIMARY KEY,
    job_key        TEXT NOT NULL,
    hash           TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    score          INTEGER NOT NULL,
    level          TEXT NOT NULL,
    reasons        TEXT NOT NULL,
    red_flags      TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_verdicts_job_key ON ai_verdicts(job_key);

CREATE TABLE IF NOT EXISTS ai_usage (
    day        TEXT NOT NULL,
    provider   TEXT NOT NULL,
    calls      INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider)
);

CREATE TABLE IF NOT EXISTS disagreements (
    id             INTEGER PRIMARY KEY,
    job_key        TEXT NOT NULL,
    hash           TEXT NOT NULL,
    python_score   INTEGER NOT NULL,
    python_section TEXT NOT NULL,
    ai_score       INTEGER NOT NULL,
    ai_level       TEXT NOT NULL,
    kind           TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_disagreements_job_key ON disagreements(job_key);

CREATE TABLE IF NOT EXISTS ai_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    http_status INTEGER,
    provider    TEXT,
    counters    TEXT NOT NULL
);
