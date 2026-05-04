# Production verification

Use this with [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) before going live or after infrastructure changes.

## Environment matrix

| Check | Variable / setting | Expected |
|-------|-------------------|----------|
| Production mode | `EVENT_DISCOVERY_ENV=production` (or `EVENT_DISCOVERY_PRODUCTION=1`) | Set on public deploys |
| Session signing | `EVENTS_SESSION_SECRET` | 16+ random characters (32+ recommended); never reuse across environments |
| Cookie transport | `EVENTS_SESSION_HTTPS_ONLY=1` | Set behind TLS |
| Cross-origin API | `EVENTS_CORS_ORIGINS` | Comma-separated origins if the browser loads the UI from a different host than the API; same-origin can leave unset (see `event_discovery/web.py` CORS wiring) |
| Auth data | Either unset `DATABASE_URL` (SQLite `auth.db` under data root) or `DATABASE_URL` (PostgreSQL auth) | One mode per environment; do not flip without migration plan |
| Discovery data | `OUTPUT_DIR` / `RAILWAY_VOLUME_MOUNT_PATH` aligned with Railway [railway.toml](../railway.toml) `requiredMountPath` (`/data`) | Persistent volume attached so per-account SQLite files survive redeploys |
| Read-only freeze | `EVENTS_WEB_READ_ONLY` | Leave unset or `0` unless intentionally locking writes |

## Smoke path (manual)

1. `GET /health` returns `{"status":"ok",...}` without auth.
2. Sign up + login (unless `EVENT_DISCOVERY_DISABLE_AUTH` or signup disabled).
3. Add a website source in **Sites**; run **Test** (dry run) successfully.
4. **Run full crawl** or per-site **Re-check**; confirm a `crawl_jobs` row moves from `queued` → `running` → `succeeded` (or inspect **Calendar** / **Review**).
5. Patch an event’s review state and reload list.

## Scheduled crawls (cron)

Background jobs run inside the web process and use the **same** mounted volume as the web service (`event_discovery/crawl_runner.py`). Do not rely on a second Railway service + its own volume for the same SQLite files.

Option A: External HTTPS cron calling `POST /api/crawl-jobs` with `EVENTS_CRAWL_API_TOKEN` and `X-Crawl-Account-Id` (see [README.md](../README.md)).

Option B: CLI / worker sharing the same filesystem as production (advanced).

## Auth backend decision

| Mode | When to use |
|------|-------------|
| SQLite `auth.db` | Single instance, simplest ops; backup volume includes `auth.db`. |
| `DATABASE_URL` (Postgres) | Managed auth, replicas, or when auth DB must live off the volume. Discovery SQLite files remain on the volume unless you change architecture. |

Postgres auth schema is applied at web startup from versioned files in `event_discovery/pg_auth_migrations/` (`event_discovery/pg_auth.py`).

## Backups and restore

- **Railway volume (`/data`)** — Treat the whole mount as the unit of backup: it holds `accounts/<id>/` discovery SQLite files and, when `DATABASE_URL` is unset, `auth.db`. Restoring an older snapshot is the primary rollback for event/triage data.
- **PostgreSQL auth** — If `DATABASE_URL` is set, use your provider’s automated backups and PITR; the volume still holds discovery SQLite unless you relocate it.
- **Optional CI check** — Set `PYTEST_PG_DSN` to a disposable database URL to run `test_pg_auth_migrations.TestPgAuthMigrations.test_apply_auth_migrations_pg_idempotent` locally or in a pipeline job.

## Logs and operations

- Crawl lifecycle: web logs when jobs are queued (`event_discovery/web.py`); the worker logs when a job starts and on failure (`event_discovery/crawl_runner.py`). Use `X-Request-ID` from responses to correlate requests in logs.
- **Do not** scale the web service to multiple replicas sharing one SQLite volume without an external locking/coordination strategy; background job dedupe is per-process (`event_discovery/crawl_runner.py`).
