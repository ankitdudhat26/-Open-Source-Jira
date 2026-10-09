#!/bin/bash
# Run Plane locally without Docker (macOS / Homebrew).
#
# Services:  Postgres 17 (Homebrew, port 5434), Redis (6379, also the Celery broker),
#            MinIO (9000, console 9090)
# Backend:   Django API (8000), Celery worker, Celery beat
# Frontend:  web (3000), admin (3001), space (3002), live (3100) via `pnpm dev`
#
# Usage: ./run-local.sh          start everything (Ctrl+C stops the app processes)
#        ./run-local.sh backend  start only services + Django/Celery

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/.local-logs"
mkdir -p "$LOG_DIR"
export PATH="$HOME/.local/bin:/opt/homebrew/opt/postgresql@17/bin:/opt/homebrew/bin:$PATH"

# --- Infrastructure -----------------------------------------------------------
brew services start postgresql@17 >/dev/null 2>&1 || true
brew services start redis >/dev/null 2>&1 || true
if ! nc -z 127.0.0.1 9000 2>/dev/null; then
  mkdir -p "$HOME/.plane-minio/data"
  MINIO_ROOT_USER=access-key MINIO_ROOT_PASSWORD=secret-key \
    nohup minio server "$HOME/.plane-minio/data" --address 127.0.0.1:9000 \
    --console-address 127.0.0.1:9090 >"$HOME/.plane-minio/minio.log" 2>&1 &
fi
until pg_isready -q -h localhost -p 5434; do sleep 1; done
until redis-cli ping >/dev/null 2>&1; do sleep 1; done
echo "✓ Postgres :5434, Redis :6379, MinIO :9000"

# --- Backend -----------------------------------------------------------------
cd "$ROOT/apps/api"
set -a; source .env; set +a
export DJANGO_SETTINGS_MODULE=plane.settings.local
PY="$ROOT/apps/api/.venv/bin/python"

"$PY" manage.py migrate --noinput >"$LOG_DIR/migrate.log" 2>&1
"$PY" manage.py clear_cache >/dev/null 2>&1 || true

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null; echo "Stopped."; }
trap cleanup EXIT INT TERM

"$PY" manage.py runserver 0.0.0.0:8000 >"$LOG_DIR/api.log" 2>&1 & pids+=($!)
.venv/bin/celery -A plane worker -l info >"$LOG_DIR/worker.log" 2>&1 & pids+=($!)
.venv/bin/celery -A plane beat -l info >"$LOG_DIR/beat.log" 2>&1 & pids+=($!)
echo "✓ API http://localhost:8000 (logs in .local-logs/)"

# --- Frontend ----------------------------------------------------------------
if [ "$1" != "backend" ]; then
  cd "$ROOT"
  pnpm dev
else
  wait
fi
