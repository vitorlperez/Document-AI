#!/bin/sh
set -eu

# Render's free tier cannot host the always-on Celery process. The API remains
# stateless; the worker below is intentionally run from the operator's Docker
# host against the same managed PostgreSQL and Redis endpoints.
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
