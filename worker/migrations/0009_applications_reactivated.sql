-- D1: « Réactiver » on an auto-archived « À candidater » application (ADR 0028). The archive
-- itself is never stored: the page and the Worker derive it; this date restarts the kept
-- counter and switches the published-age rule off for that application.
ALTER TABLE applications ADD COLUMN reactivated_at TEXT;
