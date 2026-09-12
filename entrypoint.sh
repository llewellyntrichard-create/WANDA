#!/bin/bash
set -e

echo "=== Starting Project Wanda 2 Production Node ==="

# Define database volume directory and SQLite path
DB_DIR="/app/data"
DB_PATH="${MONOLOG_DB_FILE:-/app/data/wanda2.db}"

mkdir -p "$DB_DIR"

# Check if Litestream replication bucket is set
if [ -n "$LITESTREAM_REPLICA_BUCKET" ]; then
    echo "[Litestream] Restoring SQLite database from S3 replica if available..."
    litestream restore -if-replica-exists -o "$DB_PATH" "s3://${LITESTREAM_REPLICA_BUCKET}/wanda2.db" || true
    
    echo "[Litestream] Starting background Litestream WAL replication process..."
    litestream replicate "$DB_PATH" "s3://${LITESTREAM_REPLICA_BUCKET}/wanda2.db" &
fi

# Set default port if not injected by Railway
PORT="${PORT:-8000}"

echo "[Uvicorn] Starting FastAPI application server on 0.0.0.0:${PORT}..."
exec uvicorn WANDA:app --host 0.0.0.0 --port "$PORT"
