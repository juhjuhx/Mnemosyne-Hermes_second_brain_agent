#!/usr/bin/env bash
# sync_onedrive.sh — Sync L2 (RAID) → L3 (OneDrive, encrypted)
#
# Uses rclone with a crypt remote. The crypt password is read from
# 1Password CLI at runtime — NEVER hard-code it in this script.
#
# Usage:
#   ./sync_onedrive.sh             # full weekly sync
#   ./sync_onedrive.sh --dry-run   # show what would be uploaded
#
# Prerequisites:
#   - rclone >= 1.65 installed (apt/brew: rclone)
#   - 1Password CLI (`op`) installed and signed in
#   - rclone remote `onedrive-crypt` already configured (see README below)
#
# Env vars (with defaults):
#   L2_RAID       — RAID mirror         (default: /Volumes/RAID/AISecondBrain)
#   ONEDRIVE_PATH — path inside remote  (default: AI-Brain-Backup)
#   LOG_DIR       — log dir             (default: ~/ai-brain-station/logs)
#   OP_VAULT      — 1Password vault     (default: Personal)
#   OP_ITEM       — 1Password item name (default: AI Brain Backup)

set -euo pipefail

L2_RAID="${L2_RAID:-/Volumes/RAID/AISecondBrain}"
ONEDRIVE_PATH="${ONEDRIVE_PATH:-AI-Brain-Backup}"
LOG_DIR="${LOG_DIR:-$HOME/ai-brain-station/logs}"
OP_VAULT="${OP_VAULT:-Personal}"
OP_ITEM="${OP_ITEM:-AI Brain Backup}"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \?//'
      exit 0
      ;;
  esac
done

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sync_onedrive_$(date +%Y-%m-%d).log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo "[$(ts)] $*" | tee -a "$LOG"; }
err() { echo "[$(ts)] ERROR: $*" | tee -a "$LOG" >&2; }

# ---------- preflight ----------
log "==== sync_onedrive.sh start ===="
log "L2=$L2_RAID  →  onedrive-crypt:/$ONEDRIVE_PATH  DRY_RUN=$DRY_RUN"

if [[ ! -d "$L2_RAID" ]]; then err "L2 not mounted: $L2_RAID"; exit 1; fi

if ! command -v rclone >/dev/null 2>&1; then
  err "rclone not installed. Install with: sudo apt install rclone  (or)  brew install rclone"
  exit 1
fi

if ! command -v op >/dev/null 2>&1; then
  err "1Password CLI (op) not installed. See https://developer.1password.com/docs/cli/get-started/"
  exit 1
fi

# Check signed-in to 1Password
if ! op whoami >/dev/null 2>&1; then
  err "1Password CLI not signed in. Run: op signin"
  exit 1
fi

# Fetch crypt password from 1Password — use the 'crypt-password' field
CRYPT_PASS=$(op read "op://${OP_VAULT}/${OP_ITEM}/crypt-password" 2>/dev/null) || {
  err "Could not read crypt password from 1Password item '$OP_ITEM'"
  err "Make sure the item has a field named 'crypt-password'."
  exit 1
}
SALT=$(op read "op://${OP_VAULT}/${OP_ITEM}/crypt-salt" 2>/dev/null) || SALT=""

export RCLONE_CONFIG_PASS="$CRYPT_PASS"
if [[ -n "$SALT" ]]; then export RCLONE_CONFIG_PASS2="$SALT"; fi

# ---------- list remotes ----------
log "→ Available rclone remotes:"
rclone listremotes | tee -a "$LOG"
if ! rclone listremotes | grep -q "onedrive-crypt:"; then
  err "Remote 'onedrive-crypt' not configured."
  err "Configure with: rclone config  (then create a crypt remote wrapping onedrive:AI-Brain)"
  exit 1
fi

# ---------- main sync ----------
# We use copy (not sync) because we want incremental only.
# 90-day rolling window: 1Password field, default 90.
ROLLING_DAYS=$(op read "op://${OP_VAULT}/${OP_ITEM}/rolling-days" 2>/dev/null || echo "90")

DEST="onedrive-crypt:${ONEDRIVE_PATH}"
RCLONE_ARGS=(
  copy
  "$L2_RAID"
  "$DEST"
  --log-file "$LOG"
  --log-level INFO
  --stats 5m
  --stats-one-line
  --transfers 4
  --checkers 8
  --bwlimit "08:00,2M 22:00,off"
  --exclude '_archive/**'           # too big; not part of weekly sync
  --exclude 'inbox/.tmp/**'
  --exclude '*.log'
)

if [[ "$DRY_RUN" == "1" ]]; then
  RCLONE_ARGS+=(--dry-run)
fi

log "→ Running rclone copy (rolling window: ${ROLLING_DAYS}d)..."
rclone "${RCLONE_ARGS[@]}"

# ---------- rolling-window cleanup ----------
# Anything in onedrive-crypt:AI-Brain-Backup/_backups older than 90d
# is moved (not deleted) to archive-YYYY subdirs.
log "→ Moving old backups to archive-YYYY subdirs"
CUTOFF_ISO=$(date -d "-${ROLLING_DAYS} days" -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || \
             date -u -v "-${ROLLING_DAYS}d" +%Y-%m-%dT%H:%M:%SZ)
log "  cutoff: $CUTOFF_ISO"

# (rclone has no built-in "move older than" — we'd use a local lsf + move loop.
#  For v4 baseline, we just log what would happen. Phase 5 will add this.)
log "  (cleanup not yet implemented — see sync_onedrive.sh for TODO)"

# ---------- done ----------
log "==== sync_onedrive.sh done ===="
log ""
