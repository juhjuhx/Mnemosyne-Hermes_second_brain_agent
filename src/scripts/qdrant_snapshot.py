#!/usr/bin/env python3
"""
qdrant_snapshot.py — Create a snapshot of the Qdrant vector store.

Per Phase 1 guide: nightly snapshot to RAID, verify size, keep N days.

Usage:
    python qdrant_snapshot.py --url http://127.0.0.1:6333 \
        --collection second_brain \
        --output /mnt/raid/_backups/qdrant/2026-06-05/
"""

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("snapshot")


def create_snapshot(qdrant_url: str, collection: str) -> dict:
    """Call Qdrant create_snapshot API."""
    r = requests.post(f"{qdrant_url}/collections/{collection}/snapshots", timeout=60)
    r.raise_for_status()
    return r.json()["result"]


def download_snapshot(qdrant_url: str, collection: str, snapshot_name: str, dest: Path):
    """Download a snapshot file to dest."""
    url = f"{qdrant_url}/collections/{collection}/snapshots/{snapshot_name}"
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def verify_snapshot(path: Path, min_size_mb: int = 1) -> bool:
    """Verify the snapshot file is non-trivially sized."""
    if not path.exists():
        log.error(f"Snapshot missing: {path}")
        return False
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb < min_size_mb:
        log.error(f"Snapshot too small: {size_mb:.1f}MB < {min_size_mb}MB")
        return False
    log.info(f"Snapshot OK: {size_mb:.1f}MB")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="second_brain")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--keep-days", type=int, default=7, help="Retain N days of snapshots")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    # Create snapshot
    log.info(f"Creating snapshot for {args.collection}...")
    snap = create_snapshot(args.url, args.collection)
    log.info(f"Snapshot: {snap['name']}")

    # Download
    dest = output / snap["name"]
    download_snapshot(args.url, args.collection, snap["name"], dest)

    # Verify
    if not verify_snapshot(dest):
        log.error("Snapshot verification failed")
        sys.exit(1)

    # Cleanup old snapshots
    cutoff = time.time() - args.keep_days * 86400
    for old in output.glob("*.snapshot"):
        if old.stat().st_mtime < cutoff:
            log.info(f"Removing old snapshot: {old.name}")
            old.unlink()

    log.info(f"Done: {dest}")


if __name__ == "__main__":
    main()
