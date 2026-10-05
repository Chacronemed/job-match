-- M11: funding extraction. Evidence per field, idempotent reprocess, lead priority.
ALTER TABLE articles       ADD COLUMN processed_at TEXT;   -- NULL = never extracted (M10 rows)
ALTER TABLE funding_events ADD COLUMN evidence_json TEXT;  -- {"amount": "<sentence>", ...}
ALTER TABLE leads          ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';

CREATE INDEX        IF NOT EXISTS articles_processed_at     ON articles(processed_at);
CREATE UNIQUE INDEX IF NOT EXISTS funding_events_article_co ON funding_events(article_id, company_id);
CREATE UNIQUE INDEX IF NOT EXISTS leads_funding_event       ON leads(funding_event_id);
CREATE INDEX        IF NOT EXISTS leads_company_created     ON leads(company_id, created_at);
