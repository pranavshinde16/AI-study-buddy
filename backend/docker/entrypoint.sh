#!/bin/sh
# Container start: bring the database schema up to date, then run the API (no --reload in Docker).
set -e

echo "Applying database migrations..."
alembic upgrade head

# One worker on purpose: lecture processing runs as in-process background tasks.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
