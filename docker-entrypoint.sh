#!/bin/sh
# Apply additive DB migrations / create tables before starting the server.
# init_db.py is idempotent: it only adds missing tables, columns and seed rows,
# so this is safe to run on every container start (fresh or existing DB).
set -e

echo "[entrypoint] Running database init/migration..."
python init_db.py

echo "[entrypoint] Starting: $*"
exec "$@"
