---
name: dit-offload
description: "DIT data offload with checksum verification, multi-destination backup, and offload report generation. Use when: offload、備份、 checksum、資料搬運、camera card、記憶卡、CFexpress、SSD、影像素材備份、DIT workflow。"
---

# dit-offload skill

Verified media offload for film/video production DIT workflow.

## When to use

- Offloading camera cards (CFexpress, CFast, SSD, SD) to storage
- Verifying existing offloads (checksum comparison)
- Generating offload reports for production records
- Discovering media files on a card or drive

## When NOT to use

- Searching for files by content — use `qdrant-search`
- Searching by metadata — use `filesystem-search`
- Analyzing video content — use `video-slice`

## Tools

### `offload_card`

Offload entire camera card to one or more destinations with checksum verification.

**Input**:
```json
{
  "card_path": "/Volumes/CF_A001",
  "destinations": ["/Volumes/RAID/DIT_ProjectX/A", "/Volumes/RAID/DIT_ProjectX/B"],
  "job_name": "ProjectX_Day1",
  "verify": true
}
```

**Output**: Full offload report with per-file checksums, verification status, and copy speed.

### `offload_file`

Copy a single file with MD5 + xxHash checksum verification.

**Input**:
```json
{
  "src": "/Volumes/CF_A001/DCIM/001Clip.mov",
  "dst_dir": "/Volumes/RAID/DIT_ProjectX/A",
  "verify": true
}
```

### `verify_offload`

Verify an existing offload by comparing checksums between source and destination.

**Input**:
```json
{
  "source_dir": "/Volumes/CF_A001",
  "dest_dir": "/Volumes/RAID/DIT_ProjectX/A"
}
```

**Output**:
```json
{
  "total_source_files": 47,
  "total_dest_files": 47,
  "verified": 47,
  "missing": [],
  "checksum_mismatches": [],
  "all_ok": true
}
```

### `discover_media`

Discover all camera media files in a directory tree.

**Input**:
```json
{
  "root": "/Volumes/CF_A001"
}
```

## Supported formats

**Video**: .mov, .mp4, .mxf, .avi, .mkv, .m4v
**RAW**: .ari, .ariq, .r3d, .raw, .braw, .crm
**Image**: .jpg, .jpeg, .tif, .tiff, .dng, .png, .exr, .hdr
**Audio**: .wav, .bwav, .mp3, .aac, .m4a
**Metadata**: .xml, .sidecar, .md, .txt, .log

## Checksum algorithms

- **MD5**: Universal compatibility, moderate speed
- **xxHash64**: 5-10x faster than MD5, used for quick verification
- Both are computed by default for maximum compatibility

## DIT workflow example

```
User: "幫我把 A 卡備份到兩個 SSD"
→ offload_card(
    card_path="/Volumes/CF_A001",
    destinations=["/Volumes/SSD_A", "/Volumes/SSD_B"],
    job_name="Day1_A卡"
  )

User: "驗證一下 SSD_A 的備份對不對"
→ verify_offload(
    source_dir="/Volumes/CF_A001",
    dest_dir="/Volumes/SSD_A"
  )

User: "這張卡裡有什麼檔案"
→ discover_media(root="/Volumes/CF_A001")
```
