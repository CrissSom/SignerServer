#!/bin/sh
# Launch uvicorn. Every knob is an environment variable so the server can be
# tuned entirely from a Portainer stack's env-var panel, with no command edits.
set -eu

exec /app/venv/bin/uvicorn app.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8080}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --log-level "${LOG_LEVEL:-info}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
