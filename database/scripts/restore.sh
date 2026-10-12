#!/usr/bin/env bash
# Restore the Plane database (and optionally uploads) from backups made by backup.sh.
#
#   ./scripts/restore.sh <plane-db-*.dump> [plane-uploads-*.tar.gz]
#
# Stop the app first so nothing writes during the restore:
#   cd /opt/plane && docker compose -p plane --env-file plane.env down
# Then start it again afterwards (or re-run its deploy).

set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml)

fail() { echo "[restore] ERROR: $*" >&2; exit 1; }

db_file="${1:-}"
uploads_file="${2:-}"
[ -n "$db_file" ] || fail "usage: $0 <plane-db-*.dump> [plane-uploads-*.tar.gz]"
[ -f "$db_file" ] || fail "$db_file not found"
[ -z "$uploads_file" ] || [ -f "$uploads_file" ] || fail "$uploads_file not found"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found in $(pwd)"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "This REPLACES the current Plane database${uploads_file:+ and uploaded files} with:"
echo "  $db_file${uploads_file:+
  $uploads_file}"
read -r -p "Type 'restore' to continue: " answer
[ "$answer" = "restore" ] || fail "cancelled"

echo "[restore] Restoring database..."
"${COMPOSE[@]}" exec -T plane-db \
  pg_restore -U "${POSTGRES_USER:-plane}" -d "${POSTGRES_DB:-plane}" --clean --if-exists --no-owner <"$db_file"

if [ -n "$uploads_file" ]; then
  echo "[restore] Restoring uploads..."
  minio_container="$("${COMPOSE[@]}" ps -q plane-minio)"
  docker run --rm --volumes-from "$minio_container" \
    -v "$(cd "$(dirname "$uploads_file")" && pwd)":/backup:ro \
    alpine:3 sh -c "rm -rf /export/* /export/.[!.]* 2>/dev/null; tar xzf /backup/$(basename "$uploads_file") -C /export"
  "${COMPOSE[@]}" restart plane-minio
fi

echo "[restore] Done. Start the app again."
