-- D1: the validator codes of the first attempt, as a JSON list ([] when it passed): what
-- the prompt still gets wrong, read by scripts/docs-smoke.mjs. NULL before the first call.
ALTER TABLE documents ADD COLUMN first_errors TEXT;
