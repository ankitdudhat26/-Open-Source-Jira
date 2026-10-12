#!/usr/bin/env bash
# Start or update the Plane database stack on this server.
#
# Called by .github/workflows/deploy.yml over SSH, or by hand:
#   ./scripts/deploy.sh
#
# Safe to run repeatedly: containers are only recreated when their image or
# settings change, and data lives in named Docker volumes that are never removed.

set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"

log() { echo "[database] $*"; }
fail() { echo "[database] ERROR: $*" >&2; exit 1; }

# --- Preflight ---------------------------------------------------------------
command -v docker >/dev/null || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin is not installed"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found in $(pwd). Copy .env.example to .env and fill it in."
if grep -qE '=CHANGE-ME$' "$ENV_FILE"; then
  fail "$ENV_FILE still contains CHANGE-ME values: $(grep -E '=CHANGE-ME$' "$ENV_FILE" | cut -d= -f1 | tr '\n' ' ')"
fi

# --- Start -------------------------------------------------------------------
"${COMPOSE[@]}" pull --quiet
"${COMPOSE[@]}" up -d --remove-orphans

log "Waiting up to ${HEALTH_TIMEOUT}s for Postgres, Redis and RabbitMQ to be healthy..."
deadline=$((SECONDS + HEALTH_TIMEOUT))
for service in plane-db plane-redis plane-mq; do
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$("${COMPOSE[@]}" ps -q "$service")" 2>/dev/null)" = "healthy" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      "${COMPOSE[@]}" ps -a
      "${COMPOSE[@]}" logs --tail 50 "$service"
      fail "$service did not become healthy in time"
    fi
    sleep 3
  done
  log "✓ $service healthy"
done

"${COMPOSE[@]}" ps
log "Database stack is up."
