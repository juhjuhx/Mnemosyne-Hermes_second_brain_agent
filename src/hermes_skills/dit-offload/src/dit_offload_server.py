"""
dit_offload_server.py — MCP server for DIT data offload.

Handles verified copy (checksum), multi-destination backup,
and offload report generation for film/video production.
"""

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Checksum algorithms ──────────────────────────────────────────────

def compute_md5(filepath: str, chunk_size: int = 8192) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def compute_xxhash(filepath: str, chunk_size: int = 8192) -> str:
    """Compute xxHash64 of a file. Falls back to MD5 if xxhash unavailable."""
    try:
        import xxhash
        h = xxhash.xxh64()
        with open(filepath, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()
    except ImportError:
        return compute_md5(filepath)


def compute_checksums(filepath: str) -> dict:
    """Compute both MD5 and xxHash64 for a file."""
    md5 = compute_md5(filepath)
    xxh = compute_xxhash(filepath)
    return {
        "md5": md5,
        "xxhash": xxh,
    }

# ── File discovery ───────────────────────────────────────────────────

# Common camera media extensions
CAMERA_EXTENSIONS = {
    # Video
    ".mov", ".mp4", ".mxf", ".avi", ".mkv", ".m4v",
    # RAW
    ".ari", ".ariq", ".r3d", ".raw", ".braw", ".crm",
    # Image
    ".jpg", ".jpeg", ".tif", ".tiff", ".dng", ".png", ".exr", ".hdr",
    # Audio
    ".wav", ".bwav", ".mp3", ".aac", ".m4a",
    # Metadata / sidecar
    ".xml", ".sidecar", ".md", ".txt", ".log",
}


def discover_media(root: str, extensions: Optional[set] = None) -> list:
    """Walk a directory tree and return all media files."""
    if extensions is None:
        extensions = CAMERA_EXTENSIONS
    root_path = Path(root)
    if not root_path.exists():
        return []
    files = []
    for f in sorted(root_path.rglob("*")):
        if f.is_file() and f.suffix.lower() in extensions:
            files.append(str(f))
    return files

# ── Offload engine ───────────────────────────────────────────────────

def offload_file(
    src: str,
    dst_dir: str,
    verify: bool = True,
    checksum_algo: str = "both",
) -> dict:
    """
    Copy a single file to destination with optional checksum verification.

    Returns a dict with copy result and checksums.
    """
    src_path = Path(src)
    dst_path = Path(dst_dir) / src_path.name

    # Handle name collision
    if dst_path.exists():
        stem = dst_path.stem
        suffix = dst_path.suffix
        counter = 1
        while dst_path.exists():
            dst_path = Path(dst_dir) / f"{stem}_{counter:04d}{suffix}"
            counter += 1

    # Compute source checksum before copy
    src_checksums = compute_checksums(src) if verify else None

    start = time.time()
    shutil.copy2(str(src_path), str(dst_path))
    elapsed = time.time() - start

    # Verify destination checksum
    dst_checksums = None
    verified = None
    if verify:
        dst_checksums = compute_checksums(str(dst_path))
        verified = src_checksums["md5"] == dst_checksums["md5"]

    return {
        "source": str(src_path),
        "destination": str(dst_path),
        "size_bytes": src_path.stat().st_size,
        "copy_time_sec": round(elapsed, 3),
        "source_checksums": src_checksums,
        "dest_checksums": dst_checksums,
        "verified": verified,
    }


def offload_card(
    card_path: str,
    destinations: list,
    job_name: Optional[str] = None,
    checksum_algo: str = "both",
    verify: bool = True,
) -> dict:
    """
    Offload an entire camera card to one or more destinations.

    Args:
        card_path: Path to camera card root (e.g. /Volumes/CF_A001)
        destinations: List of destination directory paths
        job_name: Optional job/project name for the report
        checksum_algo: "md5", "xxhash", or "both"
        verify: Whether to verify checksums after copy

    Returns:
        Offload report dict
    """
    card = Path(card_path)
    if not card.exists():
        return {"error": f"Card path not found: {card_path}"}

    # Discover all media files
    files = discover_media(str(card))
    if not files:
        return {"error": f"No media files found on card: {card_path}"}

    # Build report
    report = {
        "job_name": job_name or f"offload_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "card_path": str(card),
        "card_name": card.name,
        "destinations": destinations,
        "total_files": len(files),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "destinations_result": {},
        "summary": {},
    }

    total_size = 0
    total_errors = 0
    verified_count = 0

    for dest in destinations:
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)

        dest_results = {
            "path": str(dest_path),
            "files_copied": 0,
            "files_verified": 0,
            "errors": [],
            "total_bytes": 0,
            "total_time_sec": 0,
        }

        for filepath in files:
            result = offload_file(filepath, str(dest_path), verify=verify)
            total_size += result["size_bytes"]
            dest_results["total_bytes"] += result["size_bytes"]
            dest_results["total_time_sec"] += result["copy_time_sec"]

            if result.get("verified"):
                dest_results["files_verified"] += 1
                verified_count += 1
            elif result.get("verified") is False:
                dest_results["errors"].append({
                    "file": filepath,
                    "error": "CHECKSUM_MISMATCH",
                    "source_md5": result["source_checksums"]["md5"],
                    "dest_md5": result["dest_checksums"]["md5"],
                })
                total_errors += 1

            dest_results["files_copied"] += 1

            # Add to per-file report (only once, from first destination)
            if dest == destinations[0]:
                report["files"].append({
                    "source": filepath,
                    "filename": Path(filepath).name,
                    "size_bytes": result["size_bytes"],
                    "md5": result.get("source_checksums", {}).get("md5"),
                    "xxhash": result.get("source_checksums", {}).get("xxhash"),
                })

        dest_results["copy_speed_mbps"] = round(
            dest_results["total_bytes"] / (dest_results["total_time_sec"] * 1024 * 1024)
            if dest_results["total_time_sec"] > 0 else 0, 2
        )
        report["destinations_result"][dest] = dest_results

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = {
        "total_size_bytes": total_size,
        "total_size_gb": round(total_size / (1024**3), 2),
        "total_files": len(files),
        "destinations_count": len(destinations),
        "all_verified": total_errors == 0,
        "verification_errors": total_errors,
    }

    return report


def generate_report(report: dict, output_path: Optional[str] = None) -> str:
    """Generate a human-readable offload report (markdown)."""
    lines = []
    lines.append(f"# Offload Report — {report['job_name']}")
    lines.append(f"")
    lines.append(f"- **Card**: `{report['card_path']}` ({report['card_name']})")
    lines.append(f"- **Started**: {report['started_at']}")
    lines.append(f"- **Finished**: {report['finished_at']}")
    lines.append(f"- **Total files**: {report['summary']['total_files']}")
    lines.append(f"- **Total size**: {report['summary']['total_size_gb']} GB")
    lines.append(f"- **Verification**: {'✅ ALL PASSED' if report['summary']['all_verified'] else '❌ ERRORS FOUND'}")
    lines.append(f"")

    # Destinations
    lines.append("## Destinations")
    lines.append("")
    for dest, res in report["destinations_result"].items():
        lines.append(f"### `{dest}`")
        lines.append(f"- Files copied: {res['files_copied']}")
        lines.append(f"- Files verified: {res['files_verified']}")
        lines.append(f"- Speed: {res['copy_speed_mbps']} MB/s")
        if res["errors"]:
            lines.append(f"- **ERRORS**: {len(res['errors'])}")
            for err in res["errors"]:
                lines.append(f"  - `{err['filename']}`: {err['error']}")
                if "source_md5" in err:
                    lines.append(f"    - source: `{err['source_md5']}`")
                    lines.append(f"    - dest:   `{err['dest_md5']}`")
        lines.append("")

    # File manifest
    lines.append("## File Manifest")
    lines.append("")
    lines.append("| Filename | Size | MD5 |")
    lines.append("|----------|------|-----|")
    for f in report["files"]:
        size_mb = round(f["size_bytes"] / (1024**2), 2)
        lines.append(f"| `{f['filename']}` | {size_mb} MB | `{f['md5'][:12]}...` |")

    content = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")

    return content


# ── Quick verify (check existing offload) ────────────────────────────

def verify_offload(
    source_dir: str,
    dest_dir: str,
    sample_size: int = 0,
) -> dict:
    """
    Verify an existing offload by comparing checksums.

    Args:
        source_dir: Original source directory
        dest_dir: Destination to verify against
        sample_size: If >0, only verify this many random files (for large offloads)

    Returns:
        Verification result dict
    """
    source_files = {Path(f).name: f for f in discover_media(source_dir)}
    dest_files = {Path(f).name: f for f in discover_media(dest_dir)}

    missing = []
    checksum_mismatches = []
    verified = []

    for name, src_path in source_files.items():
        if name not in dest_files:
            missing.append(name)
            continue

        src_md5 = compute_md5(src_path)
        dst_md5 = compute_md5(dest_files[name])

        if src_md5 == dst_md5:
            verified.append(name)
        else:
            checksum_mismatches.append({
                "filename": name,
                "source_md5": src_md5,
                "dest_md5": dst_md5,
            })

    return {
        "source_dir": source_dir,
        "dest_dir": dest_dir,
        "total_source_files": len(source_files),
        "total_dest_files": len(dest_files),
        "verified": len(verified),
        "missing": missing,
        "checksum_mismatches": checksum_mismatches,
        "all_ok": len(missing) == 0 and len(checksum_mismatches) == 0,
    }


# ── MCP Server ───────────────────────────────────────────────────────

def handle_tool(name: str, args: dict) -> str:
    """Route MCP tool calls to implementation functions."""
    if name == "offload_card":
        result = offload_card(
            card_path=args["card_path"],
            destinations=args["destinations"],
            job_name=args.get("job_name"),
            verify=args.get("verify", True),
        )
    elif name == "offload_file":
        result = offload_file(
            src=args["src"],
            dst_dir=args["dst_dir"],
            verify=args.get("verify", True),
        )
    elif name == "verify_offload":
        result = verify_offload(
            source_dir=args["source_dir"],
            dest_dir=args["dest_dir"],
        )
    elif name == "discover_media":
        files = discover_media(args["root"])
        result = {"files": files, "count": len(files)}
    elif name == "generate_report":
        # Report generation needs the full report object
        result = {"error": "generate_report must be called with a report object"}
    else:
        result = {"error": f"Unknown tool: {name}"}

    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys
    # Simple stdio MCP server
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
            name = req.get("tool", "")
            args = req.get("args", {})
            print(handle_tool(name, args))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
