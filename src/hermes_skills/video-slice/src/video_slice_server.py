"""
video_slice_server.py — MCP server for video segmentation.

Implementation behind the `video-slice` skill.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def ffprobe_duration(video_path: str, ffmpeg_path: str = "ffmpeg") -> float:
    """Get video duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def detect_scenes(
    video_path: str,
    max_segment_sec: int = 10,
    detector: str = "adaptive",
) -> list:
    """Use PySceneDetect to find scene boundaries."""
    from scenedetect import open_video, SceneManager
    detector_cls = {
        "adaptive": "AdaptiveDetector",
        "threshold": "ThresholdDetector",
        "content": "ContentDetector",
    }[detector]

    video = open_video(video_path)
    sm = SceneManager()
    detector_obj = getattr(
        __import__("scenedetect.detectors", fromlist=[detector_cls]),
        detector_cls,
    )()
    sm.add_detector(detector_obj)
    sm.detect_scenes(video)
    raw = sm.get_scene_list()

    segments = []
    for start, end in raw:
        start_sec = start.get_seconds()
        end_sec = end.get_seconds()
        if end_sec - start_sec > max_segment_sec:
            t = start_sec
            while t < end_sec:
                segments.append((t, min(t + max_segment_sec, end_sec)))
                t += max_segment_sec
        else:
            segments.append((start_sec, end_sec))
    return segments


def extract_middle_frame(
    video_path: str, start_sec: float, end_sec: float, output: str
) -> str:
    """Extract the middle frame of a segment."""
    mid = (start_sec + end_sec) / 2
    cmd = [
        "ffmpeg", "-y", "-ss", str(mid), "-i", video_path,
        "-frames:v", "1", "-q:v", "2", output
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output


def transcribe_segment(
    audio_path: str,
    language: str = "auto",
    model: str = "tiny",
    whisper_path: str = "whisper",
) -> str:
    """Transcribe an audio file using whisper.cpp."""
    cmd = [
        whisper_path, audio_path,
        "--model", model,
        "--language", language,
        "--output-format", "txt",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    # whisper.cpp writes to <audio_path>.txt
    txt_path = audio_path + ".txt"
    if os.path.exists(txt_path):
        with open(txt_path) as f:
            return f.read().strip()
    return ""


class VideoSliceMCPServer:
    def __init__(
        self,
        ffmpeg_path: Optional[str] = None,
        whisper_path: Optional[str] = None,
    ):
        self.ffmpeg_path = ffmpeg_path or os.environ.get("FFMPEG_PATH", "ffmpeg")
        self.whisper_path = whisper_path or os.environ.get("WHISPER_PATH", "whisper")

    def slice(
        self,
        video_path: str,
        max_segment_sec: int = 10,
        detector: str = "adaptive",
        extract_frames: bool = True,
        transcribe: bool = False,
        transcribe_model: str = "tiny",
    ) -> dict:
        if not Path(video_path).exists():
            return {"error": f"video not found: {video_path}"}

        duration = ffprobe_duration(video_path)
        scenes = detect_scenes(video_path, max_segment_sec, detector)

        segments = []
        tmpdir = tempfile.mkdtemp(prefix="vidslice_")
        try:
            for i, (start, end) in enumerate(scenes):
                seg = {"start_sec": start, "end_sec": end}
                if extract_frames:
                    frame_path = os.path.join(tmpdir, f"seg_{i:04d}.jpg")
                    try:
                        extract_middle_frame(video_path, start, end, frame_path)
                        seg["middle_frame"] = frame_path
                    except subprocess.CalledProcessError:
                        seg["middle_frame"] = None
                if transcribe:
                    audio_path = os.path.join(tmpdir, f"seg_{i:04d}.wav")
                    # Extract audio for this segment
                    cmd = [
                        self.ffmpeg_path, "-y", "-ss", str(start), "-i", video_path,
                        "-to", str(end - start), "-vn", "-acodec", "pcm_s16le",
                        audio_path,
                    ]
                    subprocess.run(cmd, capture_output=True)
                    seg["transcript"] = transcribe_segment(
                        audio_path, "auto", transcribe_model, self.whisper_path
                    )
                segments.append(seg)
        finally:
            # Keep tmpdir; caller can clean up via shutil.rmtree
            pass

        return {
            "segments": segments,
            "n_segments": len(segments),
            "duration_sec": duration,
            "_tmpdir": tmpdir,
        }

    def keyframes(self, video_path: str, fps: float = 1.0) -> dict:
        if not Path(video_path).exists():
            return {"error": f"video not found: {video_path}"}
        tmpdir = tempfile.mkdtemp(prefix="keyframes_")
        out_pattern = os.path.join(tmpdir, "kf_%04d.jpg")
        cmd = [
            self.ffmpeg_path, "-y", "-i", video_path,
            "-vf", f"fps={fps}", out_pattern,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        keyframes = sorted(Path(tmpdir).glob("kf_*.jpg"))
        return {
            "keyframes": [str(p) for p in keyframes],
            "n_keyframes": len(keyframes),
            "_tmpdir": tmpdir,
        }

    def transcribe(
        self,
        video_path: str,
        language: str = "auto",
        model: str = "tiny",
    ) -> dict:
        if not Path(video_path).exists():
            return {"error": f"video not found: {video_path}"}
        tmpdir = tempfile.mkdtemp(prefix="vtx_")
        audio_path = os.path.join(tmpdir, "audio.wav")
        cmd = [
            self.ffmpeg_path, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", audio_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        text = transcribe_segment(audio_path, language, model, self.whisper_path)
        return {"transcript": text, "_tmpdir": tmpdir}


def main():
    import json
    import sys
    server = VideoSliceMCPServer()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if req.get("method") == "tools/call":
                tool = req["params"]["name"]
                args = req["params"].get("arguments", {})
                if hasattr(server, tool):
                    result = getattr(server, tool)(**args)
                    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}))
                else:
                    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": f"unknown tool: {tool}"}))
            elif req.get("method") == "initialize":
                print(json.dumps({
                    "jsonrpc": "2.0", "id": req["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "video-slice", "version": "1.0.0"},
                        "capabilities": {"tools": {}}
                    }
                }))
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "error": str(e)}))


if __name__ == "__main__":
    main()
