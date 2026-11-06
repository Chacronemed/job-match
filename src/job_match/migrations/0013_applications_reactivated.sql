-- Mirror of D1's applications.reactivated_at (worker/migrations/0009, ADR 0028): the
-- « Réactiver » date of an auto-archived application, from which its kept counter restarts.
ALTER TABLE applications ADD COLUMN reactivated_at TEXT;
