#!/usr/bin/env bash
# Daily event discovery: crawl + brief. Run on the same host/volume as the web app,
# or pass REMOTE_BASE_URL to hit the deployed API.
set -euo pipefail

cd "$(dirname "$0")/.."

CONFIG="${EVENT_DISCOVERY_CONFIG:-event_discovery/config.campaign.example.yaml}"
FORMAT="${BRIEF_FORMAT:-markdown}"
ACCOUNT_ID="${DISCOVERY_ACCOUNT_ID:-1}"

if [[ -n "${REMOTE_BASE_URL:-}" ]]; then
  exec uv run python -m event_discovery automation-run \
    --remote "$REMOTE_BASE_URL" \
    --account-id "$ACCOUNT_ID" \
    --format "$FORMAT" \
    "$@"
fi

exec uv run python -m event_discovery automation-run \
  --config "$CONFIG" \
  --account-id "$ACCOUNT_ID" \
  --format "$FORMAT" \
  "$@"
