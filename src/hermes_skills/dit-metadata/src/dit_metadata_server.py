"""
dit_metadata_server.py — MCP server for camera metadata extraction.

Parses EXIF, XMP, and camera-specific metadata from film/video media.
Supports ARRI, RED, Blackmagic, Sony, Canon, Panasonic, and ProRes.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

# ── ffprobe metadata extraction ──────────────────────────────────────

def ffprobe_metadata(filepath: str) -> dict:
    """Extract metadata using ffprobe (works for all video/audio formats)."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def extract_video_metadata(filepath: str) -> dict:
    """Extract comprehensive video metadata."""
    probe = ffprobe_metadata(filepath)
    if "error" in probe:
        return {"error": probe["error"]}

    meta = {
        "file": str(filepath),
        "filename": Path(filepath).name,
        "size_bytes": Path(filepath).stat().st_size,
        "format": {},
        "video_stream": {},
        "audio_stream": {},
        "camera": {},
    }

    # Format info
    fmt = probe.get("format", {})
    meta["format"] = {
        "format_name": fmt.get("format_name", ""),
        "format_long_name": fmt.get("format_long_name", ""),
        "duration_sec": float(fmt.get("duration", 0)),
        "bit_rate": int(fmt.get("bit_rate", 0)),
        "size": int(fmt.get("size", 0)),
    }

    # Parse format tags (camera-specific metadata lives here)
    tags = fmt.get("tags", {})
    meta["format"]["tags"] = tags

    # Detect camera brand from tags
    meta["camera"] = detect_camera(tags, probe.get("streams", []))

    # Video stream
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            meta["video_stream"] = {
                "codec": stream.get("codec_name", ""),
                "codec_long": stream.get("codec_long_name", ""),
                "width": stream.get("width", 0),
                "height": stream.get("height", 0),
                "fps": eval_fps(stream.get("r_frame_rate", "0/1")),
                "bit_rate": int(stream.get("bit_rate", 0)) if stream.get("bit_rate") else None,
                "pix_fmt": stream.get("pix_fmt", ""),
                "color_space": stream.get("color_space", ""),
                "color_range": stream.get("color_range", ""),
                "color_transfer": stream.get("color_transfer", ""),
                "color_primaries": stream.get("color_primaries", ""),
                "profile": stream.get("profile", ""),
                "level": stream.get("level", ""),
            }
            # Parse video tags
            video_tags = stream.get("tags", {})
            meta["video_stream"]["tags"] = video_tags
            break

    # Audio stream
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            meta["audio_stream"] = {
                "codec": stream.get("codec_name", ""),
                "sample_rate": int(stream.get("sample_rate", 0)),
                "channels": stream.get("channels", 0),
                "bit_rate": int(stream.get("bit_rate", 0)) if stream.get("bit_rate") else None,
            }
            break

    return meta


def eval_fps(fps_str: str) -> float:
    """Evaluate fps string like '24000/1001' to float."""
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return round(int(num) / int(den), 3)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return 0.0

# ── Camera detection ─────────────────────────────────────────────────

def detect_camera(tags: dict, streams: list) -> dict:
    """Detect camera brand and model from metadata tags."""
    camera = {
        "brand": "unknown",
        "model": "",
        "serial": "",
        "lens": "",
        "iso": "",
        "white_balance": "",
        "color_profile": "",
        "recording_format": "",
    }

    # Flatten all tags for search
    all_tags = {}
    all_tags.update(tags)
    for stream in streams:
        all_tags.update(stream.get("tags", {}))

    tag_str = json.dumps(all_tags).lower()

    # ARRI detection
    if any(k in tag_str for k in ["arriflex", "alexa", "amira", "arrifilename"]):
        camera["brand"] = "ARRI"
        camera["model"] = _find_tag(all_tags, ["com.apple.quicktime.make", "make", "encoder"])
        camera["serial"] = _find_tag(all_tags, ["com.apple.quicktime.serial", "serial"])
        camera["recording_format"] = _find_tag(all_tags, ["com.apple.quicktime.version", "encoder"]) or "ProRes/H.265"
        camera["color_profile"] = _find_tag(all_tags, ["color_profile"]) or "ARRI LogC4 / ARRI Wide Gamut 4"

    # RED detection
    elif any(k in tag_str for k in ["red", "redcode", "r3d"]):
        camera["brand"] = "RED"
        camera["model"] = _find_tag(all_tags, ["make", "com.apple.quicktime.make"]) or "RED"
        camera["recording_format"] = "REDCODE RAW"
        camera["color_profile"] = _find_tag(all_tags, ["color_profile"]) or "REDWideGamutRGB / Log3G10"

    # Blackmagic detection
    elif any(k in tag_str for k in ["blackmagic", "braw", "bmpcc"]):
        camera["brand"] = "Blackmagic Design"
        camera["model"] = _find_tag(all_tags, ["make", "com.apple.quicktime.make"]) or "Blackmagic"
        camera["recording_format"] = "BRAW" if ".braw" in tag_str else "ProRes"
        camera["color_profile"] = _find_tag(all_tags, ["color_profile"]) or "Blackmagic Film"

    # Sony detection
    elif any(k in tag_str for k in ["sony", "ilce", "pxw", "fdr"]):
        camera["brand"] = "Sony"
        camera["model"] = _find_tag(all_tags, ["make", "com.apple.quicktime.make"])
        camera["recording_format"] = _find_tag(all_tags, ["recording_format"]) or "XAVC"
        camera["color_profile"] = _find_tag(all_tags, ["color_profile"]) or "S-Log3 / S-Gamut3.Cine"

    # Canon detection
    elif any(k in tag_str for k in ["canon", "eos", "c300", "c500", "c70"]):
        camera["brand"] = "Canon"
        camera["model"] = _find_tag(all_tags, ["make", "com.apple.quicktime.make"])
        camera["recording_format"] = _find_tag(all_tags, ["recording_format"]) or "Cinema RAW Light"
        camera["color_profile"] = _find_tag(all_tags, ["color_profile"]) or "Canon Log 3"

    # Panasonic detection
    elif any(k in tag_str for k in ["panasonic", "lumix", "varicam", "eva1"]):
        camera["brand"] = "Panasonic"
        camera["model"] = _find_tag(all_tags, ["make", "com.apple.quicktime.make"])
        camera["recording_format"] = _find_tag(all_tags, ["recording_format"]) or "ProRes"
        camera["color_profile"] = _find_tag(all_tags, ["color_profile"]) or "V-Log / V-Gamut"

    # Generic QuickTime
    else:
        make = _find_tag(all_tags, ["make", "com.apple.quicktime.make"])
        if make:
            camera["brand"] = make
            camera["model"] = make

    # Common fields
    camera["lens"] = _find_tag(all_tags, ["lens_model", "lens_make", "com.apple.quicktime.lens.model"])
    camera["iso"] = _find_tag(all_tags, ["iso_speed", "iso", "Sensitivity"])
    camera["white_balance"] = _find_tag(all_tags, ["white_balance", "WhiteBalance"])

    return camera


def _find_tag(tags: dict, keys: list) -> str:
    """Find first matching tag value from a list of possible keys."""
    for key in keys:
        # Try exact match first
        if key in tags:
            val = tags[key]
            if val and str(val).strip():
                return str(val).strip()
        # Try case-insensitive
        key_lower = key.lower()
        for tag_key, tag_val in tags.items():
            if tag_key.lower() == key_lower and tag_val and str(tag_val).strip():
                return str(tag_val).strip()
    return ""

# ── Batch metadata ───────────────────────────────────────────────────

def batch_metadata(file_paths: list) -> list:
    """Extract metadata from multiple files."""
    results = []
    for fp in file_paths:
        meta = extract_video_metadata(fp)
        results.append(meta)
    return results


def generate_dit_report(metadatas: list, job_name: str = "") -> str:
    """Generate a DIT-friendly metadata report (markdown)."""
    lines = []
    lines.append(f"# DIT Metadata Report — {job_name}")
    lines.append(f"")
    lines.append(f"- **Generated**: {__import__('datetime').datetime.now().isoformat()}")
    lines.append(f"- **Files**: {len(metadatas)}")
    lines.append(f"")

    # Summary
    cameras = {}
    total_duration = 0
    total_size = 0
    for m in metadatas:
        if "error" in m:
            continue
        brand = m.get("camera", {}).get("brand", "unknown")
        cameras[brand] = cameras.get(brand, 0) + 1
        total_duration += m.get("format", {}).get("duration_sec", 0)
        total_size += m.get("size_bytes", 0)

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total duration**: {format_duration(total_duration)}")
    lines.append(f"- **Total size**: {round(total_size / (1024**3), 2)} GB")
    lines.append(f"- **Cameras**: {cameras}")
    lines.append(f"")

    # Per-file detail
    lines.append("## File Details")
    lines.append("")
    lines.append("| File | Camera | Codec | Resolution | FPS | Duration | Size |")
    lines.append("|------|--------|-------|------------|-----|----------|------|")

    for m in metadatas:
        if "error" in m:
            lines.append(f"| `{Path(m.get('file','?')).name}` | ERROR | - | - | - | - | - |")
            continue
        cam = m.get("camera", {})
        vid = m.get("video_stream", {})
        fmt = m.get("format", {})
        size_mb = round(m.get("size_bytes", 0) / (1024**2), 1)
        dur = format_duration(fmt.get("duration_sec", 0))
        res = f"{vid.get('width',0)}×{vid.get('height',0)}"
        lines.append(
            f"| `{m.get('filename','?')}` "
            f"| {cam.get('brand','?')} "
            f"| {vid.get('codec','?')} "
            f"| {res} "
            f"| {vid.get('fps',0)} "
            f"| {dur} "
            f"| {size_mb} MB |"
        )

    return "\n".join(lines)


def format_duration(seconds: float) -> str:
    """Format seconds to HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ── MCP Server ───────────────────────────────────────────────────────

def handle_tool(name: str, args: dict) -> str:
    """Route MCP tool calls to implementation functions."""
    if name == "extract_metadata":
        result = extract_video_metadata(args["filepath"])
    elif name == "batch_metadata":
        result = batch_metadata(args["file_paths"])
    elif name == "detect_camera":
        probe = ffprobe_metadata(args["filepath"])
        tags = probe.get("format", {}).get("tags", {})
        result = detect_camera(tags, probe.get("streams", []))
    elif name == "generate_dit_report":
        # Needs pre-extracted metadata
        result = {"error": "generate_dit_report needs metadata list — use batch_metadata first"}
    else:
        result = {"error": f"Unknown tool: {name}"}

    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
            name = req.get("tool", "")
            args = req.get("args", {})
            print(handle_tool(name, args))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
