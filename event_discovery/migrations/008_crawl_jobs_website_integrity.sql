-- When website_id is set, it must reference an existing websites row (SQLite has no ALTER ADD FK).
CREATE TRIGGER IF NOT EXISTS trg_crawl_jobs_website_insert
BEFORE INSERT ON crawl_jobs
WHEN NEW.website_id IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM websites WHERE id = NEW.website_id)
BEGIN
  SELECT RAISE(ABORT, 'crawl_jobs.website_id must reference websites.id');
END;

CREATE TRIGGER IF NOT EXISTS trg_crawl_jobs_website_update
BEFORE UPDATE OF website_id ON crawl_jobs
WHEN NEW.website_id IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM websites WHERE id = NEW.website_id)
BEGIN
  SELECT RAISE(ABORT, 'crawl_jobs.website_id must reference websites.id');
END;
