#!/usr/bin/env bash
# Restore test (task 8.2b): load a backup into a THROW-AWAY database inside the db container and
# compare every table's row count with the number of rows stored in the dump. The live database is
# only read (its counts are shown for information). The scratch database is dropped at the end.
#
# Usage (server, repo folder):  scripts/restore_test.sh [backup.sql.gz]   (default: newest backup)
# Same settings as backup.sh: REPO_DIR, COMPOSE_FILE, BACKUP_DIR.
# Exit 0 = every table restored with exactly the rows in the dump; 1 = a difference or an error.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-/root/backups}"

file="${1:-$(ls -1t "$BACKUP_DIR"/oil_change_*.sql.gz 2>/dev/null | head -n 1)}"
[[ -s "$file" ]] || { echo "restore_test: no backup file found (${file:-$BACKUP_DIR})" >&2; exit 1; }
scratch="restore_check_$(date +%s)"

dc() { docker compose --project-directory "$REPO_DIR" -f "$REPO_DIR/$COMPOSE_FILE" "$@"; }
# psql in the db container on database $1; the SQL comes on stdin. -X: ignore any .psqlrc.
psql_on() { dc exec -T db sh -c 'psql -X -q -v ON_ERROR_STOP=1 -At -F " " -U "$POSTGRES_USER" -d "$1"' _ "$1"; }
cleanup() { dc exec -T db sh -c 'dropdb --if-exists -U "$POSTGRES_USER" "$1"' _ "$scratch" || true; }
trap cleanup EXIT

# Read once, stdin closed: a `docker compose exec` inside a pipe would swallow the SQL meant for psql.
live_db="$(dc exec -T db sh -c 'printf %s "$POSTGRES_DB"' < /dev/null)"
echo "restore_test: $file -> scratch database $scratch (live: $live_db, only read)" >&2
dc exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' _ "$scratch"
gunzip -c "$file" | psql_on "$scratch" > /dev/null

# Rows per table IN THE DUMP: pg_dump writes one "COPY public.t (...) FROM stdin;" block per table
# (also for empty tables), one line per row (newlines inside values are escaped), ended by "\.".
expected="$(gunzip -c "$file" | awk '
  /^COPY / { table = $2; rows = 0; inside = 1; next }
  inside && /^\\\.$/ { print table, rows; inside = 0; next }
  inside { rows++ }' | sort)"
[[ -n "$expected" ]] || { echo "restore_test: FAILED: no tables in the dump" >&2; exit 1; }

# One count(*) query per table, run on the scratch DB and (for information) on the live DB.
count_sql="$(echo "$expected" | awk '{ printf "%sSELECT %s, count(*) FROM %s", (NR > 1 ? " UNION ALL " : ""), "'\''" $1 "'\''", $1 } END { print ";" }')"
restored="$(echo "$count_sql" | psql_on "$scratch" | sort)"
live="$(echo "$count_sql" | psql_on "$live_db" | sort)"
tables_restored="$(echo "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';" | psql_on "$scratch")"

status=0
printf '%-24s %10s %10s %10s  %s\n' table in_dump restored live_now result
while read -r table want; do
  got="$(echo "$restored" | awk -v t="$table" '$1 == t { print $2 }')"
  now="$(echo "$live" | awk -v t="$table" '$1 == t { print $2 }')"
  if [[ "$got" == "$want" ]]; then result="OK"; else result="DIFFERENT"; status=1; fi
  [[ "$now" == "$want" ]] || result="$result (live changed since backup)"
  printf '%-24s %10s %10s %10s  %s\n' "$table" "$want" "$got" "$now" "$result"
done <<< "$expected"

n_dump="$(echo "$expected" | wc -l | tr -d ' ')"
if [[ "$tables_restored" != "$n_dump" ]]; then
  echo "restore_test: FAILED: $tables_restored tables restored, $n_dump in the dump" >&2
  status=1
fi
if [[ $status -eq 0 ]]; then
  echo "restore_test: OK, $n_dump tables, every row count matches the dump" >&2
else
  echo "restore_test: FAILED" >&2
fi
exit $status
