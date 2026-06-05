#!/usr/bin/env bash
# sync_raid.sh — Sync L0 (inbox) + L1 (archive) → L2 (RAID)
#
# This is a *nightly mirror* — NEVER deletes on the destination side.
# To clean up old backups, see the rotation logic at the bottom.
#
# Usage:
#   ./sync_raid.sh                 # use defaults from env
#   ./sync_raid.sh --dry-run       # show what would be synced
#   VERBOSE=1 ./sync_raid.sh       # rsync -v
#
# Env vars (with defaults):
#   L0_INBOX  — workstation inbox            (default: ~/ai-brain-station/inbox)
#   L1_ARCHIVE — workstation archive         (default: ~/ai-brain-station/archive)
#   L2_RAID   — RAID mirror                  (default: /Volumes/RAID/AISecondBrain)
#   LOG_DIR   — where to write logs           (default: ~/ai-brain-station/logs)
#   RETAIN_DAYS — for rotation               (default: 90)

set -euo pipefail

# ---------- config ----------
L0_INBOX="${L0_INBOX:-$HOME/ai-brain-station/inbox}"
L1_ARCHIVE="${L1_ARCHIVE:-$HOME/ai-brain-station/archive}"
L2_RAID="${L2_RAID:-/Volumes/RAID/AISecondBrain}"
LOG_DIR="${LOG_DIR:-$HOME/ai-brain-station/logs}"
RETAIN_DAYS="${RETAIN_DAYS:-90}"

DRY_RUN=0
VERBOSE_FLAG=""
if [[ "${VERBOSE:-0}" == "1" ]]; then VERBOSE_FLAG="-v"; fi
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
LOG="$LOG_DIR/sync_raid_$(date +%Y-%m-%d).log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo "[$(ts)] $*" | tee -a "$LOG"; }
err() { echo "[$(ts)] ERROR: $*" | tee -a "$LOG" >&2; }

# ---------- preflight ----------
log "==== sync_raid.sh start ===="
log "L0=$L0_INBOX  L1=$L1_ARCHIVE  L2=$L2_RAID"
log "DRY_RUN=$DRY_RUN  VERBOSE=$VERBOSE_FLAG  RETAIN_DAYS=$RETAIN_DAYS"

if [[ ! -d "$L0_INBOX" ]]; then err "L0 missing: $L0_INBOX"; exit 1; fi
if [[ ! -d "$L1_ARCHIVE" ]]; then err "L1 missing: $L1_ARCHIVE"; exit 1; fi
if [[ ! -d "$L2_RAID" ]]; then
  err "L2 (RAID) not mounted: $L2_RAID"
  err "If you have intentionally disconnected RAID, fix this manually."
  exit 1
fi

# Ensure destination subdirs exist
for sub in inbox archive _backups; do
  mkdir -p "$L2_RAID/$sub"
done

# ---------- rsync wrapper ----------
do_sync() {
  local src="$1"
  local dst="$2"
  local label="$3"
  log "→ Syncing $label: $src → $dst"

  local rsync_args=(
    -ah
    --stats
    --no-perms --no-owner --no-group
    --exclude='.DS_Store'
    --exclude='*.tmp'
    --exclude='*.crdownload'
    --exclude='._*'
    --exclude='.Trashes'
    --exclude='.fseventsd'
  )

  if [[ -n "$VERBOSE_FLAG" ]]; then rsync_args+=("$VERBOSE_FLAG"); fi
  if [[ "$DRY_RUN" == "1" ]]; then rsync_args+=(--dry-run); fi

  rsync "${rsync_args[@]}" "$src/" "$dst/"
  log "  ✓ $label done"
}

# ---------- main sync ----------
do_sync "$L0_INBOX"   "$L2_RAID/inbox"   "L0 inbox"
do_sync "$L1_ARCHIVE" "$L2_RAID/archive" "L1 archive"

# ---------- backup dir sync (Mnemosyne + Qdrant outputs) ----------
# These are the OUTPUTS of mnemosyne_backup.py and qdrant_snapshot.py,
# which run via cron at 02:30 and 03:00. We just mirror them.
if [[ -d "$L0_INBOX/../_backups" ]]; then
  do_sync "$L0_INBOX/../_backups" "$L2_RAID/_backups" "L0 backups (raw)"
fi

# ---------- rotation: prune very old _backups (not the mirror itself) ----------
if [[ "$DRY_RUN" != "1" && -d "$L2_RAID/_backups/mnemosyne" ]]; then
  log "→ Pruning mnemosyne backups older than $RETAIN_DAYS days"
  find "$L2_RAID/_backups/mnemosyne" -maxdepth 1 -type f -name '*.db' -mtime +"$RETAIN_DAYS" -print -delete | tee -a "$LOG"
fi
if [[ "$DRY_RUN" != "1" && -d "$L2_RAID/_backups/qdrant" ]]; then
  log "→ Pruning qdrant snapshots older than 7 days (Qdrant keeps its own rolling 7-day window)"
  find "$L2_RAID/_backups/qdrant" -maxdepth 1 -type f -name '*.snapshot' -mtime +7 -print -delete | tee -a "$LOG"
fi

# ---------- disk usage report ----------
log "→ L2 disk usage:"
df -h "$L2_RAID" | tee -a "$LOG"
du -sh "$L2_RAID"/{inbox,archive,_backups} 2>/dev/null | tee -a "$LOG" || true

# ---------- done ----------
log "==== sync_raid.sh done ===="
log ""
