---
name: video-slice
description: Split a video file into ≤10s segments using PySceneDetect, extract representative frames, and optionally transcribe audio. Use when the user wants to "process this video" or "slice this clip" for indexing.
---

# video-slice skill

This skill wraps PySceneDetect 0.7 (AdaptiveDetector, F1=91.6%) and
ffmpeg to split videos into bounded segments suitable for embedding.

## When to use

- User wants to index a video (single file → many segments)
- User wants to detect scene boundaries
- User wants to extract keyframes
- User wants to transcribe video audio

## When NOT to use

- Video is < 5s (just embed as a single image)
- User wants to edit the video (use ffmpeg directly)
- User wants streaming video (we batch-process files only)

## Tools

### `slice`

Split a video into segments, extract frames, optionally transcribe.

**Input**:
```json
{
  "video_path": "/path/to/video.mp4",
  "max_segment_sec": 10,
  "detector": "adaptive|threshold|content",
  "extract_frames": true,
  "transcribe": true,
  "transcribe_model": "tiny"  // "tiny" (M1) or "large-v3" (workstation)
}
```

**Output**:
```json
{
  "segments": [
    {
      "start_sec": 0.0,
      "end_sec": 8.5,
      "middle_frame": "/tmp/video_seg_0.jpg",
      "transcript": "Hello, welcome to my talk..."
    }
  ],
  "n_segments": 12,
  "duration_sec": 95.3
}
```

### `keyframes`

Extract keyframes only (no scene detection, just I-frames).

**Input**:
```json
{"video_path": "/path/to/video.mp4", "fps": 1}
```

**Output**:
```json
{"keyframes": ["/tmp/kf_001.jpg", "/tmp/kf_002.jpg", ...], "n_keyframes": 30}
```

### `transcribe`

Transcribe video audio only (no scene detection).

**Input**:
```json
{"video_path": "/path/to/video.mp4", "language": "zh|en", "model": "tiny"}
```

**Output**:
```json
{"transcript": "...", "segments": [{"start": 0.0, "end": 5.2, "text": "..."}]}
```

## Pipeline

```
video file
  └─→ ffprobe → duration, codec
  └─→ PySceneDetect.AdaptiveDetector → raw scene list
  └─→ Split into ≤10s segments
  └─→ For each segment:
       ├─→ ffmpeg → middle frame (JPEG)
       └─→ whisper → transcript (optional)
  └─→ Return list of segments
```

## Implementation

See `src/video_slice_server.py` for the MCP server.
See `tests.py` for unit tests.
