#!/bin/sh
set -e

# Render.com / cloud platforms inject postgresql:// or postgres:// — normalize to postgresql+asyncpg://
if [ -n "$DATABASE_URL" ]; then
    case "$DATABASE_URL" in
        postgres://*)
            export DATABASE_URL="postgresql+asyncpg://${DATABASE_URL#postgres://}"
            ;;
        postgresql://*)
            export DATABASE_URL="postgresql+asyncpg://${DATABASE_URL#postgresql://}"
            ;;
    esac
fi

# If Render provides PORT, bind SITE_PORT to PORT when running in polling mode with SITE_ENABLED=true
if [ "${SITE_ENABLED}" = "true" ] && [ "${RUN_MODE:-polling}" = "polling" ] && [ -n "${PORT}" ]; then
    export SITE_PORT="${PORT}"
fi

echo "==> Running database migrations (alembic upgrade head)..."
python -m alembic upgrade head || {
    echo "Warning: alembic upgrade failed or not connected yet, retrying..."
    sleep 2
    python -m alembic upgrade head
}

echo "==> Starting application..."
exec python -m app.main
