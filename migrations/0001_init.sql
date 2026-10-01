CREATE TABLE IF NOT EXISTS sources (
    id   TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('job', 'funding')),
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT    NOT NULL REFERENCES sources(id),
    source_item_id TEXT    NOT NULL,
    fetched_at     TEXT    NOT NULL,
    payload_json   TEXT    NOT NULL,
    UNIQUE(source_id, source_item_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    website         TEXT,
    location        TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id          TEXT    NOT NULL REFERENCES sources(id),
    source_job_id      TEXT    NOT NULL,
    title              TEXT    NOT NULL,
    company            TEXT    NOT NULL,
    company_id         INTEGER REFERENCES companies(id),
    location           TEXT    NOT NULL,
    workplace_type     TEXT    NOT NULL,
    contract_type      TEXT    NOT NULL,
    description        TEXT    NOT NULL,
    url                TEXT    NOT NULL,
    published_at       TEXT,
    collected_at       TEXT    NOT NULL,
    fingerprint        TEXT,
    experience_min     REAL,
    experience_max     REAL,
    experience_status  TEXT,
    experience_evidence TEXT,
    eligibility        TEXT,
    rejection_reason   TEXT,
    score              INTEGER,
    scoring_breakdown  TEXT,
    needs_review       INTEGER NOT NULL DEFAULT 0,
    notified_at        TEXT,
    UNIQUE(source_id, source_job_id)
);

CREATE INDEX IF NOT EXISTS jobs_fingerprint  ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS jobs_eligibility  ON jobs(eligibility);
CREATE INDEX IF NOT EXISTS jobs_score        ON jobs(score);
CREATE INDEX IF NOT EXISTS jobs_collected_at ON jobs(collected_at);

CREATE TABLE IF NOT EXISTS job_duplicates (
    canonical_job_id  INTEGER NOT NULL REFERENCES jobs(id),
    duplicate_job_id  INTEGER NOT NULL REFERENCES jobs(id),
    reason            TEXT    NOT NULL,
    similarity        REAL,
    detected_at       TEXT    NOT NULL,
    PRIMARY KEY(canonical_job_id, duplicate_job_id)
);

CREATE TABLE IF NOT EXISTS job_scores (
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    engine      TEXT    NOT NULL,
    available   INTEGER NOT NULL,
    score       INTEGER,
    result_json TEXT,
    scored_at   TEXT    NOT NULL,
    PRIMARY KEY(job_id, engine)
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT    NOT NULL REFERENCES sources(id),
    url          TEXT    NOT NULL UNIQUE,
    title        TEXT    NOT NULL,
    published_at TEXT,
    collected_at TEXT    NOT NULL,
    is_funding   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS funding_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id        INTEGER NOT NULL REFERENCES companies(id),
    article_id        INTEGER REFERENCES articles(id),
    amount            REAL,
    currency          TEXT,
    round             TEXT,
    event_date        TEXT,
    investors_json    TEXT,
    sector            TEXT,
    location          TEXT,
    recruiting_signal TEXT,
    collected_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    funding_event_id INTEGER REFERENCES funding_events(id),
    reason           TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'new',
    created_at       TEXT NOT NULL,
    notified_at      TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    summary_json TEXT
);
