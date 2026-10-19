-- M20: offer closure check. Both are lifecycle state like notified_at: never written by the
-- jobs upsert, so a re-collection or a reprocess keeps them. ISO-8601 UTC text.
ALTER TABLE jobs ADD COLUMN closed_at TEXT;
ALTER TABLE jobs ADD COLUMN last_checked_at TEXT;
