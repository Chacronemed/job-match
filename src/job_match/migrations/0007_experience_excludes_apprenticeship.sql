-- "hors stage et alternance": the experience requirement excludes internships and
-- work-study years. Written by the jobs upsert like the other experience_* columns.
ALTER TABLE jobs ADD COLUMN experience_excludes_apprenticeship INTEGER NOT NULL DEFAULT 0;
