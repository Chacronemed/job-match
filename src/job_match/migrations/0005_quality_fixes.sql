-- Quality fixes: which source query returned a job; explicit country of a funding event.
ALTER TABLE jobs           ADD COLUMN search_query TEXT;
ALTER TABLE funding_events ADD COLUMN country TEXT;
