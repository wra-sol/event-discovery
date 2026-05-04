-- Background crawl job tracking (per-account discovery database)
CREATE TABLE IF NOT EXISTS crawl_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    website_id INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT,
    event_count INTEGER,
    error_message TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_crawl_jobs_created ON crawl_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawl_jobs_status ON crawl_jobs (status, created_at DESC);
