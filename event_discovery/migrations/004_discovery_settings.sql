-- HTTP client and scoring tuning (canonical when rows exist; seeded from YAML on first run)
CREATE TABLE discovery_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
