#!/usr/bin/env bash
# Nightly off-server copy (task 8.2c, plan docs/plans/8.2c_plan.md §5): every local dump made by
# backup.sh that is not on OneDrive yet is encrypted with age (public keys only) and uploaded with
# rclone into Ari's folder GeoExpert-Backups/db, the upload size is checked, copies older than
# 30 days are deleted (the newest 7 always stay), and healthchecks.io gets an "ok" or "fail" ping.
# Runs every day at 03:20 Ulaanbaatar time from deploy/systemd/ocp-offsite.timer (docs/deploy.md §12).
#
# By hand (server):  systemctl start ocp-offsite.service   (reads the ping URL from offsite.env)
# Settings (env; the defaults are the server's):
#   BACKUP_DIR         local dumps from backup.sh               (default: /root/backups)
#   RCLONE_CONFIG      rclone config with the ocp-offsite remote (default: /root/.config/rclone/rclone.conf)
#   RECIPIENTS         the two age PUBLIC keys, one per line    (default: /root/.config/ocp/age_recipients.txt)
#   OFFSITE_KEEP_DAYS  days of copies kept on OneDrive          (default: 30)
#   OFFSITE_MIN_KEEP   copies always kept, however old          (default: 7)
#   MAX_LOCAL_AGE_H    newest local dump must be younger (hours) (default: 3)
#   OFFSITE_PING_URL   healthchecks.io ping URL, from offsite.env (unset = no ping, e.g. in tests)
#   OFFSITE_FENCE      root_folder_id (default): the remote's root IS GeoExpert-Backups, files go to
#                      ocp-offsite:db; fixed_path: PM-approved fallback if root_folder_id does not work
#                      on OneDrive Personal, files go to ocp-offsite:GeoExpert-Backups/db.
#                      Any other value is refused. The remote path itself can never be set from outside.
# Exit 0 = everything uploaded and checked; 1 = a step failed (the log says which, /fail ping sent).
set -euo pipefail
umask 077  # the temp copies (encrypted) are readable by root only

BACKUP_DIR="${BACKUP_DIR:-/root/backups}"
RCLONE_CONFIG="${RCLONE_CONFIG:-/root/.config/rclone/rclone.conf}"
RECIPIENTS="${RECIPIENTS:-/root/.config/ocp/age_recipients.txt}"
OFFSITE_KEEP_DAYS="${OFFSITE_KEEP_DAYS:-30}"
OFFSITE_MIN_KEEP="${OFFSITE_MIN_KEEP:-7}"
MAX_LOCAL_AGE_H="${MAX_LOCAL_AGE_H:-3}"
OFFSITE_PING_URL="${OFFSITE_PING_URL:-}"
OFFSITE_FENCE="${OFFSITE_FENCE:-root_folder_id}"
EXPECTED_RECIPIENTS=2  # Mac key + paper key (plan Q4)
DUMP_RE='^oil_change_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}\.sql\.gz$'
COPY_RE='^oil_change_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}\.sql\.gz\.age$'

step="check"
work=""
reported=""
rc_error=""

# Ping healthchecks.io ($1 = "" for ok, "/fail"). curl's own output is thrown away, so the URL
# (it works like a password for fake pings) never reaches the log. A failed ping only warns.
ping_hc() {
  [[ -n "$OFFSITE_PING_URL" ]] || return 0
  if curl -fs -m 10 --retry 3 "$OFFSITE_PING_URL$1" > /dev/null 2>&1; then
    echo "offsite: ping sent" >&2
  else
    echo "offsite: WARNING ping failed" >&2
  fi
}

fail() {
  echo "offsite: FAILED step=$step $*" >&2
  reported=1
  ping_hc /fail
  exit 1
}

on_exit() {
  local code=$?
  [[ -z "$work" ]] || rm -rf "$work"
  if [[ $code -ne 0 && -z "$reported" ]]; then
    echo "offsite: FAILED step=$step unexpected error (exit $code)" >&2
    ping_hc /fail
  fi
}
trap on_exit EXIT

# rclone with fixed flags. Never -v / --dump (they can print the token). On error rc_error holds
# rclone's last message line, minus any line that mentions a token.
rc() {
  if rclone --config "$RCLONE_CONFIG" -q --retries 3 --low-level-retries 10 --contimeout 30s \
      --timeout 5m "$@" 2> "$work/rclone.err"; then
    return 0
  fi
  rc_error="$(grep -viE 'token|bearer' "$work/rclone.err" | tail -n 1 || true)"
  rc_error="${rc_error:-rclone failed (message hidden: it mentioned a token)}"
  return 1
}

# Exit 0 if the [ocp-offsite] section of the rclone config has a non-empty key $1. Reads only that
# key and prints nothing, so the token in the same file never reaches the log.
conf_has_key() {
  awk -v want="$1" '
    /^[[:space:]]*\[/ { sect = $0; gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "", sect); next }
    sect == "ocp-offsite" {
      line = $0; sub(/^[[:space:]]*/, "", line)
      if (index(line, want) == 1) {
        rest = substr(line, length(want) + 1)
        if (sub(/^[[:space:]]*=[[:space:]]*/, "", rest) && rest != "") found = 1
      }
    }
    END { exit found ? 0 : 1 }' "$RCLONE_CONFIG"
}

conf_has_section() { grep -qE '^[[:space:]]*\[ocp-offsite\][[:space:]]*$' "$RCLONE_CONFIG"; }

file_mode() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }    # GNU (server) or BSD (Mac)
file_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }
file_size() { wc -c < "$1" | tr -d ' '; }
days_ago() {  # date N days ago in Ulaanbaatar, YYYY-MM-DD
  TZ=Asia/Ulaanbaatar date -d "-$1 days" +%Y-%m-%d 2>/dev/null || TZ=Asia/Ulaanbaatar date -v-"$1"d +%Y-%m-%d
}
human() { awk -v b="$1" 'BEGIN { if (b < 1024) printf "%dB", b; else if (b < 1048576) printf "%.0fK", b / 1024; else printf "%.1fM", b / 1048576 }'; }
dump_is_complete() { gzip -t "$1" 2>/dev/null && [[ "$(gunzip -c "$1" | tail -n 5)" == *"PostgreSQL database dump complete"* ]]; }

work="$(mktemp -d "${TMPDIR:-/tmp}/ocp-offsite.XXXXXX")"  # mode 700; on_exit deletes it

# ---- 1. Guards -----------------------------------------------------------------------------------
# The folder fence (plan §2a): two fixed paths, nothing else.
case "$OFFSITE_FENCE" in
  root_folder_id) REMOTE_DIR="ocp-offsite:db" ;;
  fixed_path)     REMOTE_DIR="ocp-offsite:GeoExpert-Backups/db" ;;
  *) fail "OFFSITE_FENCE must be root_folder_id or fixed_path" ;;
esac

[[ -f "$RECIPIENTS" ]] || fail "recipients file $RECIPIENTS missing"
if grep -q 'AGE-SECRET-KEY' "$RECIPIENTS"; then
  fail "recipients file holds a PRIVATE key; remove it from the server (only age1... public keys belong here)"
fi
n_keys="$(grep -cE '^age1[0-9a-z]+$' "$RECIPIENTS" || true)"
n_other="$({ grep -vE '^age1[0-9a-z]+$|^[[:space:]]*(#.*)?$' "$RECIPIENTS" || true; } | wc -l | tr -d ' ')"
[[ "$n_keys" == "$EXPECTED_RECIPIENTS" && "$n_other" == 0 ]] \
  || fail "recipients file must hold exactly $EXPECTED_RECIPIENTS age1... lines (found $n_keys, plus $n_other other lines)"

[[ -f "$RCLONE_CONFIG" ]] || fail "rclone config $RCLONE_CONFIG missing"
[[ "$(file_mode "$RCLONE_CONFIG")" == 600 ]] || fail "rclone config must be mode 600 (chmod 600 $RCLONE_CONFIG)"
conf_has_section || fail "rclone config has no [ocp-offsite] remote"
if [[ "$OFFSITE_FENCE" == root_folder_id ]]; then
  conf_has_key root_folder_id || fail "folder fence missing: [ocp-offsite] has no root_folder_id (deploy.md §12 step 6)"
elif conf_has_key root_folder_id; then
  fail "OFFSITE_FENCE=fixed_path but [ocp-offsite] has a root_folder_id; use one fence, not both"
fi

# A1: tonight's dump must exist, not be empty and be fresh. Names sort by date (oldest first).
dumps="$(ls -1 "$BACKUP_DIR" 2>/dev/null | grep -E "$DUMP_RE" | sort || true)"
[[ -n "$dumps" ]] || fail "no local dump in $BACKUP_DIR - did ocp-backup run?"
newest="$(echo "$dumps" | tail -n 1)"
[[ -s "$BACKUP_DIR/$newest" ]] || fail "newest dump $newest is empty - did ocp-backup run?"
age_h=$(( ($(date +%s) - $(file_mtime "$BACKUP_DIR/$newest")) / 3600 ))
if [[ -n "$(find "$BACKUP_DIR/$newest" -mmin +$((MAX_LOCAL_AGE_H * 60)))" ]]; then
  fail "newest dump $newest is $age_h h old (limit $MAX_LOCAL_AGE_H h) - did ocp-backup run?"
fi

# ---- 2. What is on OneDrive already --------------------------------------------------------------
step="list"
rc lsf --files-only "$REMOTE_DIR" > "$work/remote.txt" || fail "$rc_error"

# ---- 3. Catch-up: every local dump not on OneDrive yet, oldest first -----------------------------
uploaded=0
damaged=0
last=""
while read -r name; do
  grep -qxF "$name.age" "$work/remote.txt" && continue
  step="check"
  if ! dump_is_complete "$BACKUP_DIR/$name"; then
    echo "offsite: FAILED step=check dump $name is damaged, not uploaded" >&2
    damaged=$((damaged + 1))
    continue
  fi
  step="encrypt"
  enc="$work/$name.age"
  age -R "$RECIPIENTS" -o "$enc" "$BACKUP_DIR/$name" 2> /dev/null || fail "age could not encrypt $name"
  [[ -s "$enc" && "$(head -n 1 "$enc")" == "age-encryption.org/v1" ]] || fail "$name.age is not an age file"
  step="upload"
  rc copyto "$enc" "$REMOTE_DIR/$name.age" || fail "$name.age: $rc_error"
  step="verify"  # A2: the copy on OneDrive must have exactly our size
  rc lsjson --files-only "$REMOTE_DIR/$name.age" > "$work/one.json" || fail "$name.age: $rc_error"
  remote_size="$(sed -n 's/.*"Size":\([0-9][0-9]*\).*/\1/p' "$work/one.json" | head -n 1)"
  local_size="$(file_size "$enc")"
  [[ "$remote_size" == "$local_size" ]] || fail "$name.age: remote ${remote_size:-?} bytes, local $local_size bytes"
  echo "$name.age" >> "$work/remote.txt"
  uploaded=$((uploaded + 1))
  last="${name%.sql.gz}, $(human "$local_size")"
  rm -f "$enc"
done <<< "$dumps"
step="check"
[[ $damaged -eq 0 ]] || fail "$damaged damaged local dump(s) not uploaded, nothing pruned"

# ---- 4. Retention (only after a fully good run): date from the NAME, newest MIN_KEEP always stay --
step="prune"
cutoff="$(days_ago "$OFFSITE_KEEP_DAYS")"
deleted=0
i=0
while read -r name; do
  [[ -n "$name" ]] || continue
  i=$((i + 1))
  [[ $i -gt $OFFSITE_MIN_KEEP ]] || continue
  day="${name:11:10}"  # oil_change_YYYY-MM-DD_...
  if [[ "$day" < "$cutoff" ]]; then
    rc deletefile "$REMOTE_DIR/$name" || fail "$name: $rc_error"
    deleted=$((deleted + 1))
  fi
done <<< "$(grep -E "$COPY_RE" "$work/remote.txt" | sort -r || true)"
kept=$(( $(grep -cE "$COPY_RE" "$work/remote.txt" || true) - deleted ))

# ---- 5. Report + ping ----------------------------------------------------------------------------
echo "offsite: OK uploaded $uploaded${last:+ ($last)} -> $REMOTE_DIR, $kept kept, $deleted deleted" >&2
ping_hc ""
