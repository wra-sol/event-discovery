-- Human triage (handbook §14); not overwritten by crawler upserts
ALTER TABLE discovered_events ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE discovered_events ADD COLUMN notes TEXT;
