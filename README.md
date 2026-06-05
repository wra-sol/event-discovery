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

**Daily automation:** copy [config.campaign.example.yaml](event_discovery/config.campaign.example.yaml), customize `campaign:` / `sources:`, then:

```bash
EVENT_DISCOVERY_CONFIG=event_discovery/config.mine.yaml \
  uv run python -m event_discovery sync-websites --config event_discovery/config.mine.yaml

uv run python -m event_discovery automation-run --config event_discovery/config.mine.yaml --format markdown
```

See [docs/AUTOMATION.md](docs/AUTOMATION.md) for agent-friendly API usage, remote mode, and Cursor Automation wiring. The highest-level endpoint is `POST /api/automation/run`: it queues a full crawl, optionally waits, and returns the daily brief payload an agent can triage.

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
| `EVENTS_AGENT_API_TOKEN` | Optional broader Bearer token for headless agents to manage sources/settings for an account using `X-Agent-Account-Id`. |
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

**Daily triage automation:** after a crawl, `GET /api/daily-brief` (same Bearer token + account header) returns pending events with candidate message drafts and calendar entries. See [docs/AUTOMATION.md](docs/AUTOMATION.md) for Cursor Automation setup and the `campaign:` config overlay ([config.campaign.example.yaml](event_discovery/config.campaign.example.yaml)).

**Railway cron (crawl + webhook brief):** add a second stateless service that runs `python -m event_discovery cron-run` on a schedule. It HTTP-calls the web app and POSTs the daily brief to webhook destinations configured per account in the UI. See [docs/CRON.md](docs/CRON.md).
