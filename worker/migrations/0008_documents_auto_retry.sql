-- D1: a failed row whose cause was a cut or a timeout (error_code api_error) is put back to
-- pending once by the cron; this marks it so the retry happens a single time (ADR 0019).
ALTER TABLE documents ADD COLUMN auto_retried INTEGER NOT NULL DEFAULT 0;
