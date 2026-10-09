#!/usr/bin/env bash
# Deploy (or roll back) Plane on this server.
#
# Called by .github/workflows/deploy-production.yml over SSH, or by hand:
#   APP_RELEASE=<image tag> ./deploy.sh
#
# Environment:
#   APP_RELEASE     image tag to deploy (required; e.g. a commit SHA or "latest")
#   IMAGE_PREFIX    e.g. ghcr.io/<owner>; defaults to the value already in plane.env
#   REGISTRY_USER   optional, with REGISTRY_TOKEN: log in to ghcr.io to pull private images
#   REGISTRY_TOKEN
#   HEALTH_TIMEOUT  seconds to wait for the API after start (default 600)
#   DATABASE_DIR    where the plane-database stack lives (default /opt/plane-database);
#                   its scripts/backup.sh runs before each deploy
#   SKIP_BACKUP=1   skip that pre-deploy backup

set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE="plane.env"
COMPOSE=(docker compose -p plane --env-file "$ENV_FILE" -f docker-compose.yml)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-600}"
DATABASE_DIR="${DATABASE_DIR:-/opt/plane-database}"

log() { echo "[deploy] $*"; }
fail() { echo "[deploy] ERROR: $*" >&2; exit 1; }

# Set KEY=VALUE in plane.env, replacing an existing line or appending a new one.
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    $0 ~ "^" k "=" { print k "=" v; found = 1; next }
    { print }
    END { if (!found) print k "=" v }
  ' "$ENV_FILE" >"$tmp"
  cat "$tmp" >"$ENV_FILE"
  rm -f "$tmp"
}

# --- Preflight ---------------------------------------------------------------
command -v docker >/dev/null || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin is not installed"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found in $(pwd). Copy plane.env.example to plane.env and fill it in."
[ -n "${APP_RELEASE:-}" ] || fail "APP_RELEASE is not set"
if grep -qE '^(SECRET_KEY|LIVE_SERVER_SECRET_KEY)=change-this-key-on-deployment$' "$ENV_FILE"; then
  fail "SECRET_KEY / LIVE_SERVER_SECRET_KEY in $ENV_FILE still have the example values"
fi
if grep -qE '^[A-Z_]+=.*CHANGE-ME' "$ENV_FILE"; then
  fail "$ENV_FILE still contains CHANGE-ME values: $(grep -E '^[A-Z_]+=.*CHANGE-ME' "$ENV_FILE" | cut -d= -f1 | tr '\n' ' ')"
fi

# The database runs in the separate plane-database stack; it must be up first.
docker network inspect plane-data >/dev/null 2>&1 \
  || fail "Docker network 'plane-data' not found. Deploy the plane-database stack first."
docker network inspect -f '{{range .Containers}}{{.Name}} {{end}}' plane-data | grep -q 'plane-db' \
  || fail "The plane-database stack is not running (no plane-db on network 'plane-data')."

# Back up the database before migrations run (skip with SKIP_BACKUP=1).
if [ "${SKIP_BACKUP:-0}" != "1" ] && [ -x "$DATABASE_DIR/scripts/backup.sh" ]; then
  log "Backing up the database before deploying..."
  "$DATABASE_DIR/scripts/backup.sh" --db-only || fail "Pre-deploy backup failed; nothing was changed."
fi

[ -n "${IMAGE_PREFIX:-}" ] && set_env IMAGE_PREFIX "$IMAGE_PREFIX"
set_env APP_RELEASE "$APP_RELEASE"
log "Deploying $(grep '^IMAGE_PREFIX=' "$ENV_FILE" | cut -d= -f2-):$APP_RELEASE"

# --- Pull images -------------------------------------------------------------
if [ -n "${REGISTRY_USER:-}" ] && [ -n "${REGISTRY_TOKEN:-}" ]; then
  echo "$REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin >/dev/null
  trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
fi
"${COMPOSE[@]}" pull --quiet

# --- Start -------------------------------------------------------------------
# The migrator runs database migrations and exits; the API waits for them.
"${COMPOSE[@]}" up -d --remove-orphans

log "Waiting up to ${HEALTH_TIMEOUT}s for the API to respond..."
deadline=$((SECONDS + HEALTH_TIMEOUT))
until "${COMPOSE[@]}" exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/instances/', timeout=5)" \
  >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    "${COMPOSE[@]}" ps -a
    "${COMPOSE[@]}" logs --tail 80 migrator api
    fail "API did not become healthy in time"
  fi
  sleep 5
done

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $APP_RELEASE" >>releases.log
docker image prune -f >/dev/null
"${COMPOSE[@]}" ps
log "Deployed $APP_RELEASE successfully."
