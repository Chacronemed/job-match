-- The ai_usage mirror gains the model (D1 migration 0005, ADR 0017): the documents (Sonnet)
-- and the rerank (Haiku) share the provider, not the price. The mirror is replaced wholesale
-- by `job-match tracking import`, so the table is simply recreated.
DROP TABLE IF EXISTS ai_usage;
CREATE TABLE ai_usage (
    day        TEXT NOT NULL,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    calls      INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider, model)
);
