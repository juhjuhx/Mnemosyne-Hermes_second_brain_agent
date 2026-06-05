#!/usr/bin/env bash
# snapshot.sh — Snapshot the entire project directory to _archive/
#
# Usage:
#   ./snapshot.sh                          # snapshot to _archive/YYYY-MM-DD-HHMM/
#   ./snapshot.sh /path/to/output          # snapshot to specific dir

set -euo pipefail

SOURCE="${1:-}"
if [[ -z "$SOURCE" ]]; then
  SOURCE="$(cd "$(dirname "$0")/../.." && pwd)"
fi

TS=$(date +%Y-%m-%d-%H%M)
DEST="${2:-${SOURCE}/_archive/${TS}}"

echo "[$(date +%H:%M:%S)] Snapshot: ${SOURCE} → ${DEST}"
mkdir -p "${DEST}"

# Use rsync; --delete to make snapshot a true mirror
rsync -a --delete \
  --exclude='.git' \
  --exclude='_archive' \
  --exclude='*.pyc' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='models/' \
  --exclude='data/' \
  --exclude='*.log' \
  "${SOURCE}/" "${DEST}/"

SIZE=$(du -sh "${DEST}" | cut -f1)
echo "[$(date +%H:%M:%S)] Done. Size: ${SIZE}"
