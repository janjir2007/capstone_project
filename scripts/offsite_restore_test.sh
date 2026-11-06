#!/usr/bin/env bash
# Monthly restore test of the OFF-SERVER copy, on Ari's Mac (task 8.2c, plan §8).
# Gets one encrypted copy (newest from OneDrive, or a file you give), decrypts it with your private
# age key, loads it into a THROW-AWAY Postgres container (data only in memory, no port opened) and
# compares every table's row count with the rows stored in the dump. Prints only table names and
# counts, never data. Everything is deleted at the end, also after an error or Ctrl+C.
#
# Usage (Mac, repo folder):
#   scripts/offsite_restore_test.sh --key ~/ocp-keys/ocp-offsite-ari.key            # newest via rclone
#   scripts/offsite_restore_test.sh --key <key> ~/Downloads/oil_change_<…>.sql.gz.age  # a downloaded file
# Settings (env):
#   RCLONE_CONFIG   Mac rclone config with a READ-ONLY ocp-offsite remote (default: ~/.config/rclone/rclone.conf)
#   OFFSITE_FENCE   root_folder_id (default) or fixed_path, same meaning as in offsite_backup.sh
#   MAX_AGE_DAYS    the test passes only if the dump is at most this old (default: 2)
#   PG_IMAGE        Postgres image, same major as production (default: postgres:16)
# Exit 0 = every table matches AND the dump is fresh; 1 = otherwise.
set -euo pipefail
umask 077

RCLONE_CONFIG="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
OFFSITE_FENCE="${OFFSITE_FENCE:-root_folder_id}"
MAX_AGE_DAYS="${MAX_AGE_DAYS:-2}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"
AWK_COUNTS="$(cd "$(dirname "$0")" && pwd)/dump_row_counts.awk"
COPY_RE='^oil_change_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}\.sql\.gz\.age$'

die() { echo "offsite_restore_test: FAILED: $*" >&2; exit 1; }
usage() { sed -n '9,11p' "$0" | sed 's/^# \{0,1\}//'; }

key=""
file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --key) key="${2:-}"; shift 2 || die "--key needs a file" ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; die "unknown option $1" ;;
    *) [[ -z "$file" ]] || die "give at most one file"; file="$1"; shift ;;
  esac
done
[[ -n "$key" ]] || { usage >&2; die "--key <private key file> is required"; }
[[ -f "$key" ]] || die "key file $key not found"

work=""
container=""
cleanup() {
  [[ -z "$container" ]] || docker rm -f "$container" > /dev/null 2>&1 || true
  [[ -z "$work" ]] || rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# The decrypted dump holds names and phones: it must never land in a folder that syncs to a cloud.
work="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/ocp-restore.XXXXXX")" && pwd -P)"
case "$work" in
  */Library/CloudStorage/*|*OneDrive*|*"Mobile Documents"*|*Dropbox*|*"Google Drive"*)
    die "temp folder $work is inside a cloud-synced folder; set TMPDIR to a local folder" ;;
esac

rc() { rclone --config "$RCLONE_CONFIG" -q "$@"; }
to_epoch() { TZ=UTC date -d "$1" +%s 2>/dev/null || TZ=UTC date -j -f %Y-%m-%d "$1" +%s; }

# ---- 1. Get the encrypted file -------------------------------------------------------------------
if [[ -n "$file" ]]; then
  [[ -s "$file" ]] || die "$file not found or empty"
  name="$(basename "$file")"
  [[ "$name" =~ $COPY_RE ]] || die "$name is not an oil_change_<date>_<time>.sql.gz.age file"
  cp "$file" "$work/$name"
else
  case "$OFFSITE_FENCE" in
    root_folder_id) base="ocp-offsite:";                   remote_dir="ocp-offsite:db" ;;
    fixed_path)     base="ocp-offsite:GeoExpert-Backups"; remote_dir="ocp-offsite:GeoExpert-Backups/db" ;;
    *) die "OFFSITE_FENCE must be root_folder_id or fixed_path" ;;
  esac
  [[ -f "$RCLONE_CONFIG" ]] || die "no rclone config at $RCLONE_CONFIG (or pass a downloaded .age file)"
  if [[ "$OFFSITE_FENCE" == root_folder_id ]] && \
     ! awk '/^[[:space:]]*\[/ { s = ($0 ~ /^[[:space:]]*\[ocp-offsite\]/) } s && /^[[:space:]]*root_folder_id[[:space:]]*=[[:space:]]*[^[:space:]]/ { f = 1 } END { exit !f }' "$RCLONE_CONFIG"; then
    die "folder fence missing: [ocp-offsite] in $RCLONE_CONFIG has no root_folder_id"
  fi
  name="$(rc lsf --files-only "$remote_dir" | grep -E "$COPY_RE" | sort | tail -n 1 || true)"
  [[ -n "$name" ]] || die "no oil_change_*.sql.gz.age in $remote_dir"
  rc copyto "$remote_dir/$name" "$work/$name"
  # R14: the fenced folder should hold only db (later photos). Names only.
  echo "top level of $base: $(rc lsf "$base" | tr '\n' ' ')"
fi

# ---- 2. Decrypt + check --------------------------------------------------------------------------
dump="$work/dump.sql.gz"
age -d -i "$key" -o "$dump" "$work/$name" || die "could not decrypt $name with $key (wrong key?)"
rm -f "$work/$name"
gzip -t "$dump" 2> /dev/null || die "decrypted file is not a valid gzip"
[[ "$(gunzip -c "$dump" | tail -n 5)" == *"PostgreSQL database dump complete"* ]] || die "dump is incomplete"

day="${name:11:10}"
age_days=$(( ($(to_epoch "$(TZ=Asia/Ulaanbaatar date +%Y-%m-%d)") - $(to_epoch "$day")) / 86400 ))
echo "dump: ${name%.sql.gz.age} ($day, $age_days days old)"

expected="$(gunzip -c "$dump" | awk -f "$AWK_COUNTS" | sort)"
[[ -n "$expected" ]] || die "no tables in the dump"

# ---- 3. Throw-away Postgres: --tmpfs = data in memory only, no -p = no port opened ---------------
suffix="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
password="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
container="ocp-restore-$suffix"
docker run -d --rm --name "$container" --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD="$password" "$PG_IMAGE" > /dev/null || die "docker run failed (is Docker Desktop running?)"
# TCP check: during first start the image runs a temporary server on the socket only, then restarts.
ready=""
for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -q -h 127.0.0.1 -U postgres > /dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ -n "$ready" ]] || die "Postgres did not start in 60 s"

psql_in() { docker exec -i "$container" psql -X -q -v ON_ERROR_STOP=1 -At -F " " -U postgres -d postgres; }
gunzip -c "$dump" | psql_in > /dev/null || die "restore into the throw-away database failed"

# ---- 4. Compare row counts -----------------------------------------------------------------------
count_sql="$(echo "$expected" | awk '{ printf "%sSELECT %s, count(*) FROM %s", (NR > 1 ? " UNION ALL " : ""), "'\''" $1 "'\''", $1 } END { print ";" }')"
restored="$(echo "$count_sql" | psql_in | sort)"
tables_restored="$(echo "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';" | psql_in)"

status=0
printf '%-24s %10s %10s  %s\n' table in_dump restored result
while read -r table want; do
  got="$(echo "$restored" | awk -v t="$table" '$1 == t { print $2 }')"
  if [[ "$got" == "$want" ]]; then result="OK"; else result="DIFFERENT"; status=1; fi
  printf '%-24s %10s %10s  %s\n' "$table" "$want" "${got:--}" "$result"
done <<< "$expected"

n_dump="$(echo "$expected" | wc -l | tr -d ' ')"
if [[ "$tables_restored" != "$n_dump" ]]; then
  echo "offsite_restore_test: $tables_restored tables restored, $n_dump in the dump" >&2
  status=1
fi
if [[ $age_days -gt $MAX_AGE_DAYS ]]; then
  echo "offsite_restore_test: dump is $age_days days old (pass needs <= $MAX_AGE_DAYS): is the nightly upload running?" >&2
  status=1
fi
if [[ $status -eq 0 ]]; then
  echo "offsite_restore_test: OK, $n_dump tables, every row count matches, dump $age_days days old" >&2
else
  echo "offsite_restore_test: FAILED" >&2
fi
exit $status
