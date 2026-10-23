#!/bin/sh
set -eu
cd "${APP_ROOT:-/app}/backend"
python -m config.runtime
python "${APP_ROOT:-/app}/scripts/bootstrap_container.py"
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-240}" \
  --access-logfile - --error-logfile -
