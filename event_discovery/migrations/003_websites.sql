-- Configurable scrape sources (canonical when at least one row has enabled=1)
CREATE TABLE websites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    source_label TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_websites_enabled ON websites (enabled);
CREATE INDEX idx_websites_order ON websites (display_order, source_key COLLATE NOCASE);

ALTER TABLE discovered_events ADD COLUMN website_id INTEGER REFERENCES websites (id) ON DELETE SET NULL;

CREATE INDEX idx_discovered_events_website ON discovered_events (website_id);
