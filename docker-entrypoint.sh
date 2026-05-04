#!/bin/sh
set -e
# Railway injects RAILWAY_VOLUME_MOUNT_PATH when a volume is attached. Keep DB and
# OUTPUT_DIR on that mount so SQLite survives redeploys regardless of mount path.
if [ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]; then
  export OUTPUT_DIR="$RAILWAY_VOLUME_MOUNT_PATH"
  export DISCOVERY_DB_PATH="$RAILWAY_VOLUME_MOUNT_PATH/discovery.db"
fi
exec "$@"
