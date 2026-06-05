#!/usr/bin/env python3
"""
verify.py — Check a working copy of the repo against the manifest.

Usage:
    python3 verify.py [REPO_PATH]

If REPO_PATH is omitted, uses the parent of the directory containing
this file's _archive/2026-06-05-v4-plan/ subdir.

Exit code 0 if all files match the manifest, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=None,
                        help="Path to the repo to verify (default: parent of this archive)")
    args = parser.parse_args()

    archive_dir = Path(__file__).resolve().parent
    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        # Default: assume the repo is the parent of the _archive/ dir
        repo = archive_dir.parent.parent

    manifest_path = archive_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest.json not found at {manifest_path}", file=sys.stderr)
        return 2
    if not repo.exists():
        print(f"ERROR: repo path does not exist: {repo}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text())
    print(f"Verifying {len(manifest['files'])} files against {repo}")
    print(f"  manifest version: {manifest['version']}")
    print(f"  manifest date:    {manifest['date']}")
    print()

    n_ok = 0
    n_changed = 0
    n_missing = 0
    for entry in manifest["files"]:
        rel = entry["path"]
        path = repo / rel
        if not path.exists():
            print(f"[MISSING]  {rel}")
            n_missing += 1
            continue
        actual = sha256_of(path)
        if actual == entry["sha256"]:
            print(f"[OK]       {rel}")
            n_ok += 1
        else:
            print(f"[CHANGED]  {rel}  (expected {entry['sha256'][:12]}, got {actual[:12]})")
            n_changed += 1

    print()
    print(f"Summary: {n_ok} OK, {n_changed} CHANGED, {n_missing} MISSING")
    print(f"  total tracked: {len(manifest['files'])}")
    if n_changed or n_missing:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
