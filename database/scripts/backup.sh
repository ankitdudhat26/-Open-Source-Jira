#!/usr/bin/env bash
# Back up the Plane database (Postgres) and uploaded files (MinIO).
#
#   ./scripts/backup.sh            database + uploads
#   ./scripts/backup.sh --db-only  database only (fast; used before app deploys)
#
# Writes to BACKUP_DIR (from .env, default ./backups):
#   plane-db-<timestamp>.dump        Postgres custom-format dump (restore with scripts/restore.sh)
#   plane-uploads-<timestamp>.tar.gz MinIO data
# Files older than BACKUP_RETENTION_DAYS (default 14) are deleted.
#
# Example cron entry (daily at 02:30):
#   30 2 * * * /opt/plane-database/scripts/backup.sh >> /opt/plane-database/backups/backup.log 2>&1

set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml)

log() { echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }
fail() { echo "[backup] ERROR: $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found in $(pwd)"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

db_container="$("${COMPOSE[@]}" ps -q plane-db)"
[ -n "$db_container" ] || fail "plane-db is not running"

# --- Postgres ----------------------------------------------------------------
db_file="$BACKUP_DIR/plane-db-$STAMP.dump"
log "Dumping database to $db_file"
"${COMPOSE[@]}" exec -T plane-db \
  pg_dump -U "${POSTGRES_USER:-plane}" -d "${POSTGRES_DB:-plane}" --format=custom >"$db_file.partial"
mv "$db_file.partial" "$db_file"

# --- MinIO uploads -----------------------------------------------------------
if [ "${1:-}" != "--db-only" ]; then
  uploads_file="$BACKUP_DIR/plane-uploads-$STAMP.tar.gz"
  log "Archiving uploads to $uploads_file"
  docker run --rm \
    --volumes-from "$("${COMPOSE[@]}" ps -q plane-minio)":ro \
    -v "$(cd "$BACKUP_DIR" && pwd)":/backup \
    alpine:3 tar czf "/backup/$(basename "$uploads_file")" -C /export .
fi

# --- Retention ---------------------------------------------------------------
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'plane-db-*.dump' -o -name 'plane-uploads-*.tar.gz' \) \
  -mtime +"$RETENTION" -print -delete | sed 's/^/[backup] removed old backup: /'

log "Backup complete."
