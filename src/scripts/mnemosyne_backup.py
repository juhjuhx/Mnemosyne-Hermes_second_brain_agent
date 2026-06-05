#!/usr/bin/env python3
"""
mnemosyne_backup.py — Backup the Mnemosyne SQLite database.

Uses sqlite3's .backup command for safe hot backup.

Usage:
    python mnemosyne_backup.py --db ~/ai-brain/hermes_config/mnemosyne/mnemosyne.db \
        --output /mnt/raid/_backups/mnemosyne/2026-06-05.db
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("mnemosyne_backup")


def backup_sqlite(db_path: str, output_path: str) -> bool:
    """Use sqlite3 .backup for atomic hot backup."""
    if not Path(db_path).exists():
        log.error(f"DB not found: {db_path}")
        return False
    try:
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(output_path)
        with dest:
            source.backup(dest)
        source.close()
        dest.close()
        size_kb = Path(output_path).stat().st_size / 1024
        log.info(f"Backup OK: {output_path} ({size_kb:.1f}KB)")
        return True
    except Exception as e:
        log.exception(f"Backup failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not backup_sqlite(args.db, str(output_path)):
        sys.exit(1)


if __name__ == "__main__":
    main()
