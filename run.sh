#!/bin/bash
set -e

if [ -n "$LITESTREAM_REPLICA_BUCKET" ]; then
    if [ -f /data/overwatch.db ]; then
        echo "Database already exists, skipping restore."
    else
        echo "Restoring database from Litestream replica..."
        litestream restore -if-replica-exists -config /etc/litestream.yml /data/overwatch.db
    fi
    echo "Starting with Litestream replication..."
    exec litestream replicate -exec "uvicorn overwatch.app:app --host 0.0.0.0 --port 8080" -config /etc/litestream.yml
else
    echo "No LITESTREAM_REPLICA_BUCKET set, running without replication..."
    exec uvicorn overwatch.app:app --host 0.0.0.0 --port 8080
fi
