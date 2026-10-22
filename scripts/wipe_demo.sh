#!/usr/bin/env bash
# Remove the demo data before real use (task 8.2d): 1) backup (stop if it fails), 2) the API image
# runs scripts/wipe_demo.py, which lists what goes and what stays and asks for a typed confirmation.
# Keeps destinations + schema_migrations. Server, repo folder:  scripts/wipe_demo.sh
# Same settings as backup.sh: REPO_DIR, COMPOSE_FILE, BACKUP_DIR.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

backup="$("$REPO_DIR/scripts/backup.sh")"  # set -e: a failed backup stops here, nothing deleted
[[ -s "$backup" ]] || { echo "wipe_demo: no backup file, nothing deleted" >&2; exit 1; }

# No -T: the confirmation is typed on this terminal.
docker compose --project-directory "$REPO_DIR" -f "$REPO_DIR/$COMPOSE_FILE" run --rm api \
  python -m scripts.wipe_demo --after-backup "$(basename "$backup")"
