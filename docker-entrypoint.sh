#!/bin/sh
set -e

echo "==> Running database migrations (alembic upgrade head)..."
python -m alembic upgrade head || {
    echo "Warning: alembic upgrade failed or not connected yet, retrying..."
    sleep 2
    python -m alembic upgrade head
}

echo "==> Starting application..."
exec python -m app.main
