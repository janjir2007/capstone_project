#!/usr/bin/env bash
# Daily database backup (task 8.2): pg_dump inside the db container -> gzip -> dated file in
# BACKUP_DIR, checked before it counts, then backups older than KEEP_DAYS are deleted.
# Runs every day at 03:00 Ulaanbaatar time from deploy/systemd/ocp-backup.timer (docs/deploy.md §12).
#
# By hand (server, repo folder):  scripts/backup.sh
# Settings (env; the defaults are the server's):
#   REPO_DIR      folder with the compose file and .env   (default: the folder above this script)
#   COMPOSE_FILE  compose file inside REPO_DIR            (default: docker-compose.prod.yml)
#   BACKUP_DIR    where backups go, OUTSIDE the repo       (default: /root/backups)
#   KEEP_DAYS     days of daily backups kept               (default: 14)
# Output: progress on stderr; the new backup's path as the only stdout line (wipe_demo.sh reads it).
set -euo pipefail
umask 077  # backups hold driver names and phones: readable by root only (RISK-06)

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-/root/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
# Name in business time (the server clock may be UTC): oil_change_2026-10-23_030000.sql.gz
final="$BACKUP_DIR/oil_change_$(TZ=Asia/Ulaanbaatar date +%Y-%m-%d_%H%M%S).sql.gz"
tmp="$final.part"
trap 'rm -f "$tmp"' EXIT  # a failed run leaves no half file behind

# Inside the container pg_dump uses the local socket and the container's own POSTGRES_USER /
# POSTGRES_DB, so no password is needed here. Plain SQL (restore = gunzip | psql).
# pipefail: if pg_dump fails, the whole line fails, even though gzip succeeded. stdin closed: exec
# must not eat the keyboard input of a caller (wipe_demo.sh asks for a typed confirmation after this).
docker compose --project-directory "$REPO_DIR" -f "$REPO_DIR/$COMPOSE_FILE" exec -T db \
  sh -c 'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < /dev/null | gzip -9 > "$tmp"

# A backup only counts if the gzip is intact and pg_dump reached its last line.
gzip -t "$tmp"
if [[ "$(gunzip -c "$tmp" | tail -n 5)" != *"PostgreSQL database dump complete"* ]]; then
  echo "backup: FAILED: dump is incomplete, nothing kept, old backups untouched" >&2
  exit 1
fi
mv "$tmp" "$final"

# Retention only after a good backup. -mtime +N = older than N+1 full days, so +13 keeps 14 daily files.
# Only our own file names are matched; anything else in BACKUP_DIR is left alone.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'oil_change_*.sql.gz' -mtime "+$((KEEP_DAYS - 1))" -delete

kept="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'oil_change_*.sql.gz' | wc -l | tr -d ' ')"
echo "backup: OK $(du -h "$final" | cut -f1) -> $final ($kept kept, $KEEP_DAYS days)" >&2
echo "$final"
