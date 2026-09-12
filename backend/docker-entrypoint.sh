#!/bin/sh
set -e

# Railway's private DNS can lag a few seconds behind container start, and alembic
# connecting on the first tick would fail the whole deploy. Retry before giving up.
attempt=0
until alembic upgrade head; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 10 ]; then
        echo "migrations failed after $attempt attempts" >&2
        exit 1
    fi
    sleep 3
done

# Only the platform's proxy can reach this container, so its X-Forwarded-For is
# the real client IP — without trusting it, ratelimit.py keys every request to
# the proxy and the login limit becomes global instead of per-IP.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
