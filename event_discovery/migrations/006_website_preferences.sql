-- Per-website discovery overrides (http, scoring, enrichment), deep-merged over account defaults.
ALTER TABLE websites ADD COLUMN preferences_json TEXT NOT NULL DEFAULT '{}';
