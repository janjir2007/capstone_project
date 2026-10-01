#!/usr/bin/env bash
# Start Label Studio for task 3.1 (plate labeling) — local only, private.
#
# - Runs from its own venv (~/.venvs/label-studio), NOT the project .venv.
# - Photos are read straight from data/raw/photos/ on disk (never uploaded).
# - Label Studio's database (annotations = real plate strings) lives in
#   data/labelstudio/, which is git-ignored (data/**).
# - Listens on 127.0.0.1 only (default would be 0.0.0.0 = whole Wi-Fi network).
# - Telemetry to tele.labelstud.io and the PyPI version check are turned off.
#
# Usage (from anywhere):  bash docs/labeling/start_label_studio.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LS_BIN="${HOME}/.venvs/label-studio/bin/label-studio"
PORT="${LS_PORT:-8080}"

if [[ ! -x "${LS_BIN}" ]]; then
  echo "Label Studio not found at ${LS_BIN}. Install it first (see docs/labeling/LABELING_GUIDE.md)." >&2
  exit 1
fi

# Where Label Studio keeps its SQLite DB, exports and media (git-ignored).
export LABEL_STUDIO_BASE_DATA_DIR="${REPO_ROOT}/data/labelstudio"

# Allow serving local files, but only from below data/raw/.
export LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true
export LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="${REPO_ROOT}/data/raw"

# Privacy: no usage analytics, no "new version available" check.
export LABEL_STUDIO_COLLECT_ANALYTICS=false
export LABEL_STUDIO_LATEST_VERSION_CHECK=false

mkdir -p "${LABEL_STUDIO_BASE_DATA_DIR}"

echo "Label Studio: http://localhost:${PORT}   (Ctrl+C to stop)"
echo "Local files root: ${LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT}"
exec "${LS_BIN}" start --internal-host 127.0.0.1 --port "${PORT}"
