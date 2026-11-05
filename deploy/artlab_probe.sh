#!/usr/bin/env bash
# Read-only Artlab probe on the server, one section per run (task 9.6c-2, docs/plans/9.6c_plan.md).
# Runs scripts/artlab_probe.py in the artlab-sync container (the only one with ARTLAB_*) and saves
# the JSON ONLY under /root/artlab_probe/ (outside the repo, owner-only). The active Artlab connection
# (test or real DB?) is printed on the screen first. Then a privacy check runs on the new file.
#
#   deploy/artlab_probe.sh paymethods
#   deploy/artlab_probe.sh months                      # bill count per month, last 24 months
#   deploy/artlab_probe.sh bills --from 2026-10-28 --to 2026-11-04
#   deploy/artlab_probe.sh acc-txn --account <code> --from 2026-10-05 --to 2026-11-04
#   deploy/artlab_probe.sh check /root/artlab_probe/<file>.json   # privacy check only (9.6c-2b)
#
# The privacy check is scripts/probe_privacy_check.py on the HOST python3 (9.6c-2b: the old grep
# failed on the server's locale and still said "none found"). If it cannot run, this script says
# so and exits 4; it never prints "none found" by itself.
#
# It never installs or starts a timer and never touches our database (--no-deps).
set -euo pipefail

OUT_DIR=/root/artlab_probe
REPO="$(cd "${BASH_SOURCE[0]%/*}/.." && pwd)"

# privacy_check FILE -> 0 clean, 3 plate-like text, 4 the check could not run.
privacy_check() {
  local rc=0
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found: plate check could NOT run; do NOT share $1" >&2
    return 4
  fi
  python3 -I "$REPO/scripts/probe_privacy_check.py" "$1" || rc=$?
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then
    echo "ERROR: plate check could NOT run (exit $rc); do NOT share $1" >&2
    return 4
  fi
  return "$rc"
}

section="${1:-}"
case "$section" in
  check)
    [ $# -eq 2 ] || { echo "usage: $0 check FILE.json" >&2; exit 2; }
    rc=0; privacy_check "$2" || rc=$?
    exit "$rc" ;;
  paymethods|bills|acc-txn|months) shift ;;
  *) echo "usage: $0 paymethods|bills|acc-txn|months [--from YYYY-MM-DD --to YYYY-MM-DD] [--account CODE]" >&2
     echo "       $0 check FILE.json" >&2
     exit 2 ;;
esac

if ls /etc/systemd/system 2>/dev/null | grep -qi artlab; then
  echo "WARNING: Artlab systemd units are installed; 9.6c expects none (systemctl list-timers --all 'ocp-artlab-*')" >&2
fi

umask 077
mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
out="$OUT_DIR/$(date +%Y%m%d-%H%M%S)_${section}.json"

cd "$REPO"
if ! docker compose -f docker-compose.prod.yml --profile sync run --rm --no-deps -T artlab-sync \
    python -m scripts.artlab_probe --section "$section" "$@" > "$out"; then
  rm -f "$out"
  echo "probe failed: nothing saved" >&2
  exit 1
fi
echo "saved: $out"

rc=0; privacy_check "$out" || rc=$?
exit "$rc"
