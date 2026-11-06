#!/bin/sh
# Container entrypoint. Render (and most PaaS) pass the port in $PORT; locally it defaults to 8000.
set -e

# Render's free plan has no pre-deploy step, so migrations can run here instead. Alembic upgrades are
# idempotent; with a single instance there is no race. Off by default (docker compose has its own migrate job).
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "running migrations"
  alembic upgrade head
fi

# The platform's proxy terminates TLS and sets X-Forwarded-For; trust it so the sign-up limit sees the
# real client IP instead of the proxy's. Override FORWARDED_ALLOW_IPS if the app is ever exposed directly.
exec uvicorn app.main:create_app --factory \
  --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --timeout-keep-alive 65
