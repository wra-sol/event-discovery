-- Reject triage: excluded from calendar alongside non-reviewed rows
ALTER TABLE discovered_events ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0;
