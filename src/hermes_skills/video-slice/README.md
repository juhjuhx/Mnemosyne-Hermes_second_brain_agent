# video-slice

Video segmentation with PySceneDetect — one of the 3 example skills in the Personal AI Second Brain.

## Quick example

```python
from src.mcp_servers.video_slice_server import VideoSliceMCPServer

server = VideoSliceMCPServer()

# Slice a video
result = server.slice(
    video_path="/path/to/video.mp4",
    max_segment_sec=10,
    detector="adaptive",
    extract_frames=True,
    transcribe=True,
)
print(f"Found {result['n_segments']} segments in {result['duration_sec']:.1f}s")
for i, seg in enumerate(result["segments"]):
    print(f"  [{i}] {seg['start_sec']:.1f}s - {seg['end_sec']:.1f}s: {seg.get('middle_frame')}")

# Cleanup
import shutil
shutil.rmtree(result["_tmpdir"])
```

## Tools exposed

- `slice` — split into segments
- `keyframes` — extract keyframes only
- `transcribe` — transcribe audio only

## Environment variables

| Var | Default | Description |
|---|---|---|
| `FFMPEG_PATH` | `ffmpeg` | ffmpeg binary |
| `WHISPER_PATH` | `whisper` | whisper.cpp binary |
| `DEFAULT_DETECTOR` | `adaptive` | Scene detector |

## See also

- [`SKILL.md`](SKILL.md) — full agent-facing documentation
- [`manifest.json`](manifest.json) — MCP server config
- [`tests.py`](tests.py) — unit tests
