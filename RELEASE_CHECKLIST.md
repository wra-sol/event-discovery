# Release checklist

See **[docs/PRODUCTION.md](docs/PRODUCTION.md)** for the full environment matrix and smoke path.

1. **Secrets** — Rotate any keys that ever lived in git; confirm `.env` is not committed. If using scheduled crawls, rotate `EVENTS_CRAWL_API_TOKEN` on the same schedule as other service secrets.
2. **Env** — `EVENT_DISCOVERY_ENV=production`, `EVENTS_SESSION_SECRET` (16+ chars), `EVENTS_SESSION_HTTPS_ONLY=1`, `EVENTS_CORS_ORIGINS` for your public UI origin.
3. **Database** — If using `DATABASE_URL`, Postgres auth migrations run at web startup (`apply_auth_migrations_pg`). Run discovery SQLite migrations via first request or `python -m event_discovery --migrate-only`.
4. **Volume** — Railway volume mounted at `/data` (or set `OUTPUT_DIR` / `RAILWAY_VOLUME_MOUNT_PATH` consistently). Back up the whole volume (per-account discovery DBs + `auth.db` if using SQLite auth).
5. **Smoke** — `/health` returns `ok`, sign-up/login, add source, dry-run test, background crawl job completes.
6. **Rollback** — Keep previous image tag; restore DB snapshot if using Postgres; restore volume snapshot for SQLite discovery data.
