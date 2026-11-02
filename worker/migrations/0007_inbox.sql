-- D1: recruiter replies pushed by n8n (ADR 0018, M27). One row per email, keyed by its
-- Message-ID; the body is never stored (only the sender's domain and a short subject), the
-- model's verdict is, and what was done with it. `state`: applied (the application was
-- updated), to_confirm (waiting for me in the dashboard), corrected, ignored.
CREATE TABLE inbox_items (
    message_id     TEXT PRIMARY KEY,
    received_at    TEXT NOT NULL,
    sender_domain  TEXT,
    subject        TEXT CHECK (subject IS NULL OR length(subject) <= 200),
    kind           TEXT CHECK (kind IS NULL OR kind IN
                     ('entretien', 'refus', 'accuse_reception', 'relance_recruteur', 'autre')),
    confidence     REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    interview_at   TEXT,
    proposed_key   TEXT,
    state          TEXT NOT NULL CHECK (state IN ('applied', 'to_confirm', 'corrected', 'ignored')),
    applied_key    TEXT,
    applied_at     TEXT,
    ai_outcome     TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX idx_inbox_state ON inbox_items(state, received_at);

-- The interview date, set by a confirmed « entretien » reply or by hand in the record panel.
ALTER TABLE applications ADD COLUMN interview_at TEXT;
