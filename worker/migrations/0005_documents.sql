-- D1: application documents (ADR 0017, M26). One row per generated version of the CV and the
-- cover letter for an offer I kept ("Garder" -> applications.status = to_apply). The texts
-- themselves live in R2 (content_key, then the rendered files); D1 keeps the status, the
-- model, the prompt version, the R2 keys, an error code and the cost. Nothing personal here.
CREATE TABLE documents (
    id              INTEGER PRIMARY KEY,
    job_key         TEXT NOT NULL,
    version         INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'running', 'ready', 'failed')),
    language        TEXT CHECK (language IS NULL OR language IN ('fr', 'en')),
    model           TEXT,
    prompt_version  TEXT,
    content_key     TEXT,
    cv_pdf_key      TEXT,
    cv_docx_key     TEXT,
    letter_pdf_key  TEXT,
    letter_docx_key TEXT,
    error_code      TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_micro_usd  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (job_key, version)
);
CREATE INDEX idx_documents_status ON documents(status, id);

-- One row per cron pass that did something (a pass with nothing pending writes none).
CREATE TABLE document_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    outcome     TEXT NOT NULL CHECK (outcome IN
                  ('ok', 'stopped', 'budget', 'credit', 'no_master', 'failed')),
    http_status INTEGER,
    counters    TEXT NOT NULL
);

-- The documents version that went with the application, set when the status becomes "applied".
ALTER TABLE applications ADD COLUMN sent_documents_version INTEGER;

-- ai_usage now carries the model: the documents (Sonnet) and the rerank (Haiku) share the
-- provider but not the price, and the monthly budget is computed per model. SQLite cannot
-- change a primary key in place, so the table is rebuilt (0003 pattern).
CREATE TABLE ai_usage_new (
    day        TEXT NOT NULL,
    provider   TEXT NOT NULL CHECK (provider IN ('anthropic', 'workers_ai')),
    model      TEXT NOT NULL,
    calls      INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider, model)
);
INSERT INTO ai_usage_new (day, provider, model, calls, tokens_in, tokens_out)
    SELECT day, provider,
           CASE provider WHEN 'anthropic' THEN 'claude-haiku-5-5'
                         ELSE '@cf/meta/llama-3.3-70b-instruct-fp8-fast' END,
           calls, tokens_in, tokens_out
    FROM ai_usage;
DROP TABLE ai_usage;
ALTER TABLE ai_usage_new RENAME TO ai_usage;
