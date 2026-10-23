#!/bin/sh
set -eu
cd "$(dirname "$0")"
docker compose up --build -d
printf '%s\n' 'Open http://localhost:8000 after the container becomes healthy.' 'Logs: docker compose logs -f web'

