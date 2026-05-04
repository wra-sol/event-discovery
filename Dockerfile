# Burlington event discovery — Railway: attach a volume to the service; mount path
# is passed as RAILWAY_VOLUME_MOUNT_PATH — docker-entrypoint.sh sets OUTPUT_DIR and
# DISCOVERY_DB_PATH under that path so SQLite persists across deploys.
# Local: bind-mount a host dir to /data if you want SQLite to persist (no VOLUME
# directive — Railway forbids it; use a Railway volume on the service instead).
# Optional WEBHOOK_URL for Slack/Discord JSON hooks.
#
# Crawler (CLI): CMD python -m event_discovery
# Web UI:        startCommand in railway.toml or python -m event_discovery.web
# Optional: EVENTS_WEB_READ_ONLY=1 to disable writes
# If the image runs as a non-root user, set RAILWAY_RUN_UID=0 on Railway.
#
# Omit BuildKit cache mounts: Railway's Dockerfile builder rejects many cache id shapes.
# For Railway, prefer RAILPACK (see railway.toml). This file is for local docker build.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    OUTPUT_DIR=/data \
    DISCOVERY_DB_PATH=/data/discovery.db

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

COPY pyproject.toml uv.lock ./
COPY event_discovery ./event_discovery
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "event_discovery"]
