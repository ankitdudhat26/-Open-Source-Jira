#!/bin/bash
# Run Plane locally without Docker (macOS / Homebrew).
#
# Services:  Postgres 17 (Homebrew, port 5434), Redis (6379, also the Celery broker),
#            MinIO (9000, console 9090)
# Backend:   Django API (8000), Celery worker, Celery beat
# Frontend:  web (3000), admin (3001), space (3002), live (3100) via `pnpm dev`
#
# Usage: ./run-local.sh          start everything (Ctrl+C stops everything it started)
#        ./run-local.sh backend  start only services + Django/Celery
#        ./run-local.sh stop     stop a copy that is still running (e.g. in another terminal)

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/.local-logs"
mkdir -p "$LOG_DIR"
export PATH="$HOME/.local/bin:/opt/homebrew/opt/postgresql@17/bin:/opt/homebrew/bin:$PATH"
APP_PORTS=(8000 3000 3001 3002 3100)

busy_ports() {
  local p
  for p in "${APP_PORTS[@]}"; do nc -z 127.0.0.1 "$p" 2>/dev/null && echo "$p"; done
}

if [ "$1" = "stop" ]; then
  for pid in $(pgrep -f "run-local.sh" || true); do
    [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
  done
  pkill -f "manage.py runserver 0.0.0.0:8000" 2>/dev/null || true
  pkill -f "celery -A plane" 2>/dev/null || true
  sleep 2
  lsof -ti "tcp:$(IFS=,; echo "${APP_PORTS[*]}")" 2>/dev/null | xargs kill 2>/dev/null || true
  echo "Stopped Plane."
  exit 0
fi

# Refuse to start twice: a second copy can't bind the ports and leaves the frontends without an API.
# In backend mode only the API port matters, so it can run next to a separate `pnpm dev` / `npm run dev`.
[ "$1" = "backend" ] && APP_PORTS=(8000)
busy="$(busy_ports | tr '\n' ' ')"
if [ -n "$busy" ]; then
  echo "✗ Plane already seems to be running (ports in use: $busy)."
  echo "  Use the running copy, or stop it first with:  ./run-local.sh stop"
  exit 1
fi

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
cd "$ROOT/1-main/backend"
set -a; source .env; set +a
export DJANGO_SETTINGS_MODULE=plane.settings.local
PY="$ROOT/1-main/backend/.venv/bin/python"

"$PY" manage.py migrate --noinput >"$LOG_DIR/migrate.log" 2>&1
"$PY" manage.py clear_cache >/dev/null 2>&1 || true

# On exit (Ctrl+C or an error) stop every process this script started, including
# children such as Django's auto-reloader and the Vite dev servers.
cleanup() {
  trap - EXIT INT TERM
  echo "Stopping Plane..."
  kill 0 2>/dev/null
}
trap cleanup EXIT INT TERM

"$PY" manage.py runserver 0.0.0.0:8000 >"$LOG_DIR/api.log" 2>&1 &
api_pid=$!
.venv/bin/celery -A plane worker -l info >"$LOG_DIR/worker.log" 2>&1 &
.venv/bin/celery -A plane beat -l info >"$LOG_DIR/beat.log" 2>&1 &

# Wait for the API before starting the frontends, and show why if it fails.
for _ in $(seq 1 90); do
  curl -fs -o /dev/null http://localhost:8000/api/instances/ && break
  if ! kill -0 "$api_pid" 2>/dev/null; then break; fi
  sleep 1
done
if ! curl -fs -o /dev/null http://localhost:8000/api/instances/; then
  echo "✗ The API did not start. Last lines of .local-logs/api.log:"
  tail -20 "$LOG_DIR/api.log"
  exit 1
fi
echo "✓ API http://localhost:8000 (logs in .local-logs/)"

# --- Frontend ----------------------------------------------------------------
if [ "$1" != "backend" ]; then
  cd "$ROOT"
  pnpm dev
else
  wait
fi
