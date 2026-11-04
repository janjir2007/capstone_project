#!/usr/bin/env bash
# Read-only Artlab probe on the server, one section per run (task 9.6c-2, docs/plans/9.6c_plan.md).
# Runs scripts/artlab_probe.py in the artlab-sync container (the only one with ARTLAB_*) and saves
# the JSON ONLY under /root/artlab_probe/ (outside the repo, owner-only). The active Artlab connection
# (test or real DB?) is printed on the screen first. Then a privacy check runs on the new file.
#
#   deploy/artlab_probe.sh paymethods
#   deploy/artlab_probe.sh bills --from 2026-10-28 --to 2026-11-04
#   deploy/artlab_probe.sh acc-txn --account <code> --from 2026-10-05 --to 2026-11-04
#
# It never installs or starts a timer and never touches our database (--no-deps).
set -euo pipefail

OUT_DIR=/root/artlab_probe
section="${1:-}"
case "$section" in
  paymethods|bills|acc-txn) shift ;;
  *) echo "usage: $0 paymethods|bills|acc-txn [--from YYYY-MM-DD --to YYYY-MM-DD] [--account CODE]" >&2
     exit 2 ;;
esac

if ls /etc/systemd/system 2>/dev/null | grep -qi artlab; then
  echo "WARNING: Artlab systemd units are installed; 9.6c expects none (systemctl list-timers --all 'ocp-artlab-*')" >&2
fi

umask 077
mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
out="$OUT_DIR/$(date +%Y%m%d-%H%M%S)_${section}.json"

cd "$(dirname "$0")/.."
if ! docker compose -f docker-compose.prod.yml --profile sync run --rm --no-deps -T artlab-sync \
    python -m scripts.artlab_probe --section "$section" "$@" > "$out"; then
  rm -f "$out"
  echo "probe failed: nothing saved" >&2
  exit 1
fi
echo "saved: $out"

# Privacy check (plan §3.3). Masked shapes like "9999 ААА" are expected; a real-looking plate is not.
plates=$(grep -nE '[0-9]{4}[ -]?[А-ЯЁӨҮа-яёөү]{3}' "$out" | grep -vE '9999[ -]?ААА' || true)
if [ -n "$plates" ]; then
  echo "STOP: plate-like text found, do NOT share this file:" >&2
  echo "$plates" >&2
  exit 3
fi
echo "plate check: none found"
echo "8-digit numbers (each must be a sum / count / id / account code, never a phone):"
grep -nE '\b[6-9][0-9]{7}\b' "$out" | grep -v 99999999 || echo "  none"
