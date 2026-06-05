#!/usr/bin/env bash
# restore.sh — Reconstruct the v4 repo from a working copy that matches
# the manifest in this directory.
#
# This is a meta-script: it tells you HOW to restore, it doesn't
# actually copy anything (the manifest is not a copy of the files).
#
# For automated byte-level verification, use verify.py.

set -euo pipefail

ARCHIVE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$ARCHIVE_DIR/../.." && pwd)"
MANIFEST="$ARCHIVE_DIR/manifest.json"

cat <<EOF
Archive restore helper
======================

Archive:  $ARCHIVE_DIR
Manifest: $MANIFEST
Repo:     $REPO_ROOT

This archive does NOT contain file copies. It contains a SHA-256 manifest
of the v4 plan as it existed on 2026-06-05. To restore:

  1. Get a working copy of the repo from ANY source (git, OneDrive,
     backup, friend's machine).

  2. Run the verification:
       python3 $ARCHIVE_DIR/verify.py /path/to/copy

  3. If verify.py reports all OK, the copy is bit-for-bit identical
     to the 2026-06-05 snapshot.

  4. If verify.py reports CHANGED or MISSING, the copy has drifted
     from the snapshot. This is normal if work has continued.

EOF

# Offer to run verify.py against the live repo
echo "→ Running verify.py against $REPO_ROOT ..."
python3 "$ARCHIVE_DIR/verify.py" "$REPO_ROOT"
