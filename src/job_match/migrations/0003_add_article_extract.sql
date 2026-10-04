-- M10: short extract of the article body (never the full text).
ALTER TABLE articles ADD COLUMN extract TEXT;

CREATE INDEX IF NOT EXISTS articles_collected_at ON articles(collected_at);
