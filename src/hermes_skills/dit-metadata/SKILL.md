---
name: dit-metadata
description: "Camera metadata extraction for DIT workflow — ARRI, RED, Blackmagic, Sony, Canon, Panasonic. Use when: metadata、camera info、鏡頭資訊、拍攝格式、色彩空間、解析度、幀率、DIT report、鏡頭型號、ISO。"
---

# dit-metadata skill

Extract and analyze camera metadata from film/video media files.

## When to use

- Need to know camera brand, model, lens, ISO, color profile
- Generating DIT reports with technical specs
- Checking resolution, fps, codec, color space
- Batch-analyzing multiple clips from a shoot
- Identifying unknown footage

## When NOT to use

- Wanting to search files by content — use `qdrant-search`
- Wanting to offload/backup files — use `dit-offload`
- Wanting to split videos — use `video-slice`

## Tools

### `extract_metadata`

Extract comprehensive video/image metadata.

**Input**:
```json
{"filepath": "/Volumes/RAID/footage/Day1/A001_C001.mov"}
```

**Output**:
```json
{
  "file": "/Volumes/RAID/footage/Day1/A001_C001.mov",
  "filename": "A001_C001.mov",
  "size_bytes": 2147483648,
  "format": {
    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    "duration_sec": 120.5,
    "bit_rate": 142000000
  },
  "video_stream": {
    "codec": "prores",
    "width": 4096,
    "height": 2160,
    "fps": 23.976,
    "pix_fmt": "yuv422p10le",
    "color_space": "bt2020",
    "profile": "ProRes 4444"
  },
  "camera": {
    "brand": "ARRI",
    "model": "ALEXA 35",
    "lens": "Panavision C-Series 50mm",
    "iso": "800",
    "color_profile": "ARRI LogC4 / ARRI Wide Gamut 4"
  }
}
```

### `batch_metadata`

Extract metadata from multiple files.

**Input**:
```json
{
  "file_paths": [
    "/Volumes/RAID/footage/Day1/A001_C001.mov",
    "/Volumes/RAID/footage/Day1/A001_C002.mov"
  ]
}
```

### `detect_camera`

Quick camera brand/model detection.

**Input**:
```json
{"filepath": "/Volumes/RAID/footage/Day1/A001_C001.mov"}
```

## Supported cameras

| Brand | Formats | Metadata |
|-------|---------|----------|
| **ARRI** | .mov, .ari, .ariq | LogC4, AWG4, lens, serial |
| **RED** | .r3d, .mov | REDCODE, REDWideGamutRGB, Log3G10 |
| **Blackmagic** | .braw, .mov | BRAW, ProRes, Film Gen 5 |
| **Sony** | .mov, .mp4 | XAVC, S-Log3, S-Gamut3.Cine |
| **Canon** | .mov, .mp4 | Cinema RAW Light, Canon Log 3 |
| **Panasonic** | .mov, .mp4 | V-Log, V-Gamut, ProRes |

## DIT workflow example

```
User: "這支影片是什麼相機拍的？"
→ detect_camera(filepath="/Volumes/RAID/A001_C001.mov")

User: "幫我出一份 DIT 報告，列出所有素材的技術規格"
→ batch_metadata(file_paths=[...])
→ generate_dit_report(metadatas, job_name="Day1")

User: "有多少支是 4K 的？"
→ batch_metadata(file_paths=[...])
→ (filter where width >= 3840)
```

## Requires

- `ffprobe` (part of ffmpeg) must be installed
- Optional: `exiftool` for deeper EXIF parsing (future enhancement)
