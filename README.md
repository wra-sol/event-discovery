# Event discovery

FastAPI app plus static UI to manage crawl sources, run discovery against public event listings, triage results in SQLite (or optional PostgreSQL for **auth**), and browse a simple calendar.

## Quick start (local)

```bash
uv sync
cp .env.example .env
# Set EVENTS_SESSION_SECRET to a random 32+ char string for auth mode.
uv run python -m event_discovery.web
```

Open `http://127.0.0.1:8000`, sign up (unless disabled), then use **Sites** to add sources and **Re-check** / **Run full crawl** (background jobs).

## Tests

```bash
uv run python -m pytest
```

## Environment

See [.env.example](.env.example). Important variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | When set, **accounts/users** use PostgreSQL instead of `auth.db` on disk. Discovery DBs stay per-account SQLite under `OUTPUT_DIR` unless you standardize on external tooling. |
| `EVENTS_SESSION_SECRET` | Required in production (`EVENT_DISCOVERY_ENV=production`) for cookie signing. |
| `EVENTS_CRAWL_API_TOKEN` | Optional. When set, `POST /api/crawl-jobs`, `GET /api/crawl-jobs*`, and `POST /api/websites/{id}/recheck` accept `Authorization: Bearer …` plus `X-Crawl-Account-Id` for cron/automation. |
| `EVENTS_CORS_ORIGINS` | Comma-separated browser origins when calling the API cross-origin. |
| `EVENTS_SESSION_HTTPS_ONLY` | Set `1` behind HTTPS. |
| `EVENT_DISCOVERY_ENV` | Set to `production` for stricter startup checks. |

## Railway

- Default process: `python -m event_discovery.web` (see `railway.toml`).
- Attach a volume at `/data` for SQLite data roots unless you only use Postgres auth and accept ephemeral discovery files (not typical).
- For scheduled full crawls plus web UI, prefer a shared operational pattern: same `OUTPUT_DIR` volume on one service, or call `POST /api/crawl-jobs` with `EVENTS_CRAWL_API_TOKEN` + `X-Crawl-Account-Id` (see **Scheduled crawls** above).

## Release checklist

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) and the expanded [docs/PRODUCTION.md](docs/PRODUCTION.md).

## Scheduled crawls (cron / automation)

Crawl jobs run in the **web** process and read/write the **same** per-account SQLite files on the mounted volume. A separate Railway cron service **without** that volume will not see your data.

Set `EVENTS_CRAWL_API_TOKEN` to a long random secret, then call:

```bash
curl -sS -X POST "$BASE_URL/api/crawl-jobs" \
  -H "Authorization: Bearer $EVENTS_CRAWL_API_TOKEN" \
  -H "X-Crawl-Account-Id: 1" \
  -H "Content-Type: application/json" \
  -d '{"kind":"full"}'
```

Use the numeric **account** id (same as the logged-in user’s account). Optional: `GET /api/crawl-jobs` and `GET /api/crawl-jobs/{id}` accept the same headers for polling. Session cookie auth still works from the browser for the same routes.
