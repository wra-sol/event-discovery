-- Discovery run audit trail
CREATE TABLE discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    event_count INTEGER,
    error_message TEXT
);

-- One row per deduped public listing; upserted on each successful crawl
CREATE TABLE discovered_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    venue TEXT,
    raw_snippet TEXT,
    relevance_score REAL NOT NULL DEFAULT 0,
    relevance_reasons_json TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_run_id INTEGER,
    FOREIGN KEY (last_run_id) REFERENCES discovery_runs (id)
);

CREATE INDEX idx_discovered_events_score ON discovered_events (relevance_score DESC);
CREATE INDEX idx_discovered_events_source ON discovered_events (source);
CREATE INDEX idx_discovered_events_last_seen ON discovered_events (last_seen_at);
