-- D1: the AI rerank (ADR 0016, M25). One verdict per offer content (job_key + hash of
-- title + description) and prompt version; a repost or a reprocess costs nothing. The jobs
-- SQLite DB mirrors these tables read-only (src/job_match/migrations/0010_ai_mirror.sql).
-- Reasons and red flags are short JSON arrays of strings; nothing personal is ever stored.
CREATE TABLE ai_verdicts (
    id             INTEGER PRIMARY KEY,
    job_key        TEXT NOT NULL,
    hash           TEXT NOT NULL,
    provider       TEXT NOT NULL CHECK (provider IN ('anthropic', 'workers_ai')),
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    score          INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    level          TEXT NOT NULL CHECK (level IN ('fort', 'tenter', 'hors_sujet')),
    reasons        TEXT NOT NULL,
    red_flags      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (job_key, hash, prompt_version)
);
CREATE INDEX idx_ai_verdicts_job_key ON ai_verdicts(job_key);

-- Counters only (the daily cap and the cost estimate). day = YYYY-MM-DD, UTC.
CREATE TABLE ai_usage (
    day        TEXT NOT NULL,
    provider   TEXT NOT NULL CHECK (provider IN ('anthropic', 'workers_ai')),
    calls      INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider)
);

-- Where the model and the Python score disagree: a gap over the threshold, or an offer the
-- Python score calls strong that the model calls off-topic. Read by `job-match ai-report`.
CREATE TABLE disagreements (
    id             INTEGER PRIMARY KEY,
    job_key        TEXT NOT NULL,
    hash           TEXT NOT NULL,
    python_score   INTEGER NOT NULL,
    python_section TEXT NOT NULL,
    ai_score       INTEGER NOT NULL,
    ai_level       TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('gap', 'off_topic_strong')),
    created_at     TEXT NOT NULL
);
CREATE INDEX idx_disagreements_job_key ON disagreements(job_key);

-- One row per cron pass: the outcome, the HTTP status that stopped it (a 4xx that is not a
-- quota), the last provider used and the counters as JSON. Shown in the Exécutions view.
CREATE TABLE ai_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    outcome     TEXT NOT NULL CHECK (outcome IN ('ok', 'stopped', 'no_profile', 'failed')),
    http_status INTEGER,
    provider    TEXT CHECK (provider IS NULL OR provider IN ('anthropic', 'workers_ai')),
    counters    TEXT NOT NULL
);
