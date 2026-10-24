"""media_probe.py — DIT 2.2 P10 read-only FFprobe media probe.

Pure stdlib + `ffprobe -of json`. READ-ONLY by construction: this
module never opens an input (or sidecar) for writing. It shells out to
ffprobe via safe argv (no shell), refuses network URLs, applies a
timeout and an output-size cap, and degrades gracefully (VFR unknown,
color/HDR unknown, camera-family unverified) rather than guessing.

Spec: docs/engineering/spec/P10-media-probe.md.

Isolation: no v4 `files.db`, no qdrant, no indexer imports (same
isolation clause as P09/P05 — static import review proves it).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

# ── limits / policy ──────────────────────────────────────────────────

_MAX_OUTPUT_BYTES = 50 * 1024 * 1024  # 50MB cap on ffprobe JSON
_MAX_STDERR_BYTES = 2048  # truncate stderr into errors
_DEFAULT_TIMEOUT_S = 30.0

# sidecar extensions (lowercased)
_SIDECAR_EXTS = {
    ".sidecar.json", ".json", ".csv", ".m3u8", ".srt",
    ".xml", ".edl",
}
# treat these as media containers, not sidecars
_MEDIA_EXTS = {".mov", ".mp4", ".mxf", ".braw", ".x-ocn", ".dng",
               ".r3d", ".arri", ".prores", ".m2ts", ".m2t",
               ".wav", ".aif", ".m4a", ".ac3", ".aac"}


class ProbeError(Exception):
    """ffprobe could not parse the input (corrupt / unknown / empty)."""


class InvalidInputError(ProbeError):
    """The caller passed an input we refuse to probe (e.g. a URL)."""


class ProbeTimeout(ProbeError):
    """ffprobe did not finish within the timeout."""


# ── data model ───────────────────────────────────────────────────────


@dataclass
class VideoStream:
    index: int
    codec: str | None
    width: int | None
    height: int | None
    pix_fmt: str | None
    r_frame_rate: str | None
    avg_frame_rate: str | None
    time_base: str | None
    start_time: float | None
    color_primaries: str | None
    color_transfer: str | None
    color_space: str | None
    rotation: float | None = None
    hdr: str = "unknown"  # "sdr" | "hdr-sdr" | "unknown"

    @property
    def fps(self) -> Fraction | None:
        """Exact rational FPS from avg_frame_rate (or r_frame_rate)."""
        for raw in (self.avg_frame_rate, self.r_frame_rate):
            try:
                f = Fraction(raw or "")
                if f > 0:
                    return f
            except (ValueError, ZeroDivisionError):
                continue
        return None


@dataclass
class AudioStream:
    index: int
    codec: str | None
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None


@dataclass
class MediaProbe:
    path: str
    ffprobe_version: str
    container: str | None
    duration_s: float | None
    nb_streams: int
    video: list[VideoStream]
    audio: list[AudioStream]
    fps: Fraction | None
    fps_status: str  # "ok" | "unknown"
    vfr_status: str  # "cfr" | "vfr-likely" | "unknown"
    timecode: str | None  # "drop" | "non-drop" | None
    timecode_basis: str
    camera_family: str
    family_verified: bool
    sidecars: list[str] = field(default_factory=list)
    source_sha256: str | None = None
    raw_json: str = ""

    def main_video(self) -> VideoStream | None:
        return self.video[0] if self.video else None

    def to_evidence_json(self) -> str:
        """Reconstructable evidence: version + argv + raw ffprobe JSON
        + (optional) source sha256. Reproduce the same fields by
        re-parsing `raw_json` with the same binary."""
        return json.dumps(
            {
                "ffprobe_version": self.ffprobe_version,
                "argv_base": [
                    "ffprobe", "-hide_banner", "-loglevel", "error",
                    "-of", "json", "-show_format", "-show_streams",
                    self.path,
                ],
                "container": self.container,
                "fps": str(self.fps) if self.fps else None,
                "fps_status": self.fps_status,
                "vfr_status": self.vfr_status,
                "timecode": self.timecode,
                "camera_family": self.camera_family,
                "family_verified": self.family_verified,
                "source_sha256": self.source_sha256,
                "sidecars": self.sidecars,
                "raw": self.raw_json,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_evidence(evidence_json: str) -> MediaProbe:
        """Re-parse the raw ffprobe JSON captured in an evidence blob
        (no subprocess). Lets a reviewer reproduce stream-level fields
        offline from a prior probe."""
        ev = json.loads(evidence_json)
        return _build_probe_from_raw(
            ev.get("raw", "{}"),
            path=ev.get("argv_base", [""])[-1],
            ffprobe_version=ev.get("ffprobe_version", "unknown"),
            source_sha256=ev.get("source_sha256"),
        )


# ── classification helpers ──────────────────────────────────────────

_SDR_TRANSFER = {"bt709", "smpte170m", "bt470m", "bt470bg", "iec61966-2-1",
                 "smpte2085", "smpte2085-1"}
_SDR_PRIMARIES = {"bt709", "smpte170m", "bt470m", "bt470bg", "ntsc",
                  "smpte240m", "iec61966-2-1", "xvycc709", "smpte432"}
_HDR_TRANSFER = {"smpte2084", "arib-std-b67", "arib-std-b67-s2",
                 "arib-std-b67-s3", "arib-std-b67-s4"}


def classify_hdr(primaries: str | None, transfer: str | None,
                 space: str | None) -> str:
    """Conservative: only claim 'sdr' when BOTH transfer and primaries
    are SDR-family; claim 'hdr-sdr' when transfer is HDR (PQ/HLG);
    otherwise degrade to 'unknown' (never guess)."""
    t = (transfer or "").lower()
    p = (primaries or "").lower()
    if t in _HDR_TRANSFER:
        return "hdr-sdr"
    if t in _SDR_TRANSFER and p in _SDR_PRIMARIES:
        return "sdr"
    return "unknown"


_DROP_FPS = {Fraction(30), Fraction(30000, 1001)}
_NONDROP_FPS = {Fraction(24), Fraction(25), Fraction(48), Fraction(50),
                Fraction(60), Fraction(60000, 1001), Fraction(12),
                Fraction(15), Fraction(1000, 40)}


def classify_timecode(fps: Fraction | None) -> tuple[str | None, str]:
    """Return (timecode, basis). Drop-frame capable = 30fps family;
    24/25/48/50/60 = non-drop; unknown fps = (None, 'unresolved')."""
    if fps is None:
        return None, "unresolved"
    if fps in _DROP_FPS:
        return "drop", "fps-family"
    if fps in _NONDROP_FPS:
        return "non-drop", "fps-family"
    return "non-drop", "fps-value"  # fall back on value, still non-drop


def _classify_camera_family(container: str | None, video: list[VideoStream],
                            path: str) -> tuple[str, bool]:
    """Best-effort camera family from container/codec/filename.
    Families with NO real sample available are returned
    `verified=False` (never claim a real-camera match)."""
    name = (container or "").lower()
    stem = Path(path).stem.lower()
    suffix = Path(path).suffix.lower()
    vc = (video[0].codec or "").lower() if video else ""

    if suffix == ".braw" or "braw" in stem:
        return "sony-braw", False  # no sample
    if suffix == ".dng":
        return "cinemadng", False
    if "x-ocn" in name or suffix == ".x-ocn" or "ocn" in stem:
        return "blackmagic-ocn", False
    if suffix == ".r3d":
        return "red-mono", False
    if vc in ("prores", "apch", "apcn", "apco", "apcs"):
        return "prores", True
    if name == "matroska,webm" or suffix in (".mkv", ".webm"):
        return "generic-matroska", True
    if name == "mov,quicktime" or suffix == ".mov":
        return "quicktime", True
    if name == "mxf" or suffix == ".mxf":
        return "generic-mxf", True
    if name in ("mp4", "mov,mp4,m4a,3gp,3g2,mj2") or suffix == ".mp4":
        return "generic-mp4", True
    return "unknown", False


def vfr_status_from_pts(pts: list[float]) -> str:
    """CFR vs VFR from per-frame PTS. Degrades to 'unknown' when we
    don't have enough frames to measure; NEVER assumes cfr."""
    clean = [p for p in pts if p is not None and p >= 0]
    clean.sort()
    if len(clean) < 3:
        return "unknown"
    deltas = [b - a for a, b in pairwise(clean)]
    positive = [d for d in deltas if d > 0]
    if len(positive) < 2:
        return "unknown"
    median = sorted(positive)[len(positive) // 2]
    if median <= 0:
        return "unknown"
    # any delta deviating >5% from the median ⇒ variable frame rate
    if any(abs(d - median) / median > 0.05 for d in positive):
        return "vfr-likely"
    return "cfr"


def _extract_rotation(stream: dict) -> float | None:
    """Rotation from side data (Display Matrix) or stream tags. Best
    effort: returns None when ffprobe did not expose it."""
    for item in stream.get("side_data_list") or []:
        kind = item.get("side_data_type", "")
        if "Display" in kind or "rotation" in kind.lower():
            # ffprobe stores the value as a string like
            # "{rotation=90.000000}" (newer) or a bare number (older).
            val = item.get("side_data_value")
            if isinstance(val, str):
                m = re.search(r"rotation\s*=\s*([-0-9.]+)", val)
                if m:
                    try:
                        return float(m.group(1))
                    except ValueError:
                        pass
            if isinstance(val, (int, float)):
                return float(val)
    tags = stream.get("tags") or {}
    if isinstance(tags, dict):
        for k in ("rotation", "rotate", "Rotation"):
            if k in tags:
                try:
                    return float(str(tags[k]).replace("deg", ""))
                except ValueError:
                    return None
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _list_sidecars(base_dir: Path, media_name: str) -> list[str]:
    """Read-only directory scan: relative paths of files that look
    like sidecars (never the media file itself, never dirs)."""
    out: list[str] = []
    for entry in sorted(os.scandir(base_dir), key=lambda e: e.name):
        if entry.is_dir():
            continue
        low = entry.name.lower()
        # match multi-dot sidecar names
        is_sidecar = any(low.endswith(s) for s in _SIDECAR_EXTS)
        if not is_sidecar:
            continue
        if low == media_name.lower():
            continue
        out.append(entry.name)
    return out


def _reject_url(path: str) -> None:
    """Refuse any input that looks like a network URL — P10 must never
    implicitly open a remote resource."""
    lowered = path.lower()
    for scheme in ("http://", "https://", "ftp://", "ftps://",
                   "data:", "rtmp://", "rtp://", "srt://", "tcp://",
                   "udp://"):
        if lowered.startswith(scheme) or "://" in path:
            raise InvalidInputError(
                f"refusing to probe a network URL ({path!r}); pass a "
                f"local filesystem path"
            )


# ── parse ────────────────────────────────────────────────────────────


def _parse_streams(payload: dict) -> tuple[list[VideoStream], list[AudioStream]]:
    video: list[VideoStream] = []
    audio: list[AudioStream] = []
    for i, s in enumerate(payload.get("streams", [])):
        stype = s.get("codec_type")
        if stype == "video":
            prim = s.get("color_primaries")
            trans = s.get("color_transfer") or s.get("color_trc")
            space = s.get("color_space")
            video.append(
                VideoStream(
                    index=i,
                    codec=s.get("codec_name"),
                    width=s.get("width"),
                    height=s.get("height"),
                    pix_fmt=s.get("pix_fmt"),
                    r_frame_rate=s.get("r_frame_rate"),
                    avg_frame_rate=s.get("avg_frame_rate"),
                    time_base=s.get("time_base"),
                    start_time=s.get("start_time"),
                    color_primaries=prim,
                    color_transfer=trans,
                    color_space=space,
                    rotation=_extract_rotation(s),
                    hdr=classify_hdr(prim, trans, space),
                )
            )
        elif stype == "audio":
            raw_sr = s.get("sample_rate")
            try:
                sr = int(raw_sr) if raw_sr is not None else None
            except (TypeError, ValueError):
                sr = None
            raw_ch = s.get("channels")
            try:
                ch = int(raw_ch) if raw_ch is not None else None
            except (TypeError, ValueError):
                ch = None
            audio.append(
                AudioStream(
                    index=i,
                    codec=s.get("codec_name"),
                    sample_rate=sr,
                    channels=ch,
                    channel_layout=s.get("channel_layout"),
                )
            )
    return video, audio


def _build_probe_from_raw(raw: str, *, path: str, ffprobe_version: str,
                          source_sha256: str | None) -> MediaProbe:
    payload = json.loads(raw)
    fmt = payload.get("format", {})
    video, audio = _parse_streams(payload)
    mv = video[0] if video else None
    fps = mv.fps if mv else None
    fps_status = "ok" if fps else "unknown"
    tc, tc_basis = classify_timecode(fps)
    container = fmt.get("format_name")
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    nb = fmt.get("nb_streams", len(video) + len(audio))
    family, verified = _classify_camera_family(container, video, path)
    return MediaProbe(
        path=path,
        ffprobe_version=ffprobe_version,
        container=container,
        duration_s=duration,
        nb_streams=nb,
        video=video,
        audio=audio,
        fps=fps,
        fps_status=fps_status,
        vfr_status="unknown",
        timecode=tc,
        timecode_basis=tc_basis,
        camera_family=family,
        family_verified=verified,
        source_sha256=source_sha256,
        raw_json=raw,
    )


# ── subprocess helpers ──────────────────────────────────────────────


def _run_ffprobe(bin: str, args: list[str], timeout_s: float) -> str:
    try:
        proc = subprocess.run(
            [bin, *args],
            input=None,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ProbeTimeout(f"ffprobe timed out after {timeout_s}s") from e
    except FileNotFoundError as e:
        raise ProbeError(f"ffprobe binary not found: {bin!r}") from e
    if proc.returncode != 0:
        err = (proc.stderr or b"")[:_MAX_STDERR_BYTES].decode(
            "utf-8", "replace"
        )
        raise ProbeError(
            f"ffprobe exited {proc.returncode}: {err.strip()[:500]}"
        )
    out = proc.stdout
    if len(out) > _MAX_OUTPUT_BYTES:
        raise ProbeError("output limit exceeded (>50MB JSON)")
    return out.decode("utf-8", "replace")


def _ffprobe_version(bin: str) -> str:
    try:
        p = subprocess.run([bin, "-version"], capture_output=True, timeout=15,
                           check=False)
        first = (p.stdout or b"").decode("utf-8", "replace").splitlines()
        return first[0].strip() if first else "unknown"
    except (subprocess.SubprocessError, OSError):
        # version lookup is best-effort evidence metadata; a failure here
        # must not abort the probe — record "unknown" and carry on.
        return "unknown"


# ── public entry point ──────────────────────────────────────────────


def probe(
    path: str | Path,
    *,
    sidecar_dir: str | Path | None = None,
    sha256: bool = False,
    full_fps: bool = False,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    ffprobe_bin: str = "ffprobe",
) -> MediaProbe:
    """Read-only probe of `path`. Never writes to the input or its
    sidecars; refuses network URLs; degrades (unknown) rather than
    guessing on FPS/VFR/HDR/camera-family it cannot verify."""
    if shutil.which(ffprobe_bin) is None:
        raise ProbeError(f"ffprobe binary not found: {ffprobe_bin!r}")
    raw_input = str(path)
    _reject_url(raw_input)  # on the ORIGINAL string: Path() collapses
    # "http://" to "http:/" and would otherwise hide the scheme
    p = Path(raw_input)
    if not p.exists():
        raise InvalidInputError(f"no such file: {p}")
    if p.is_dir():
        raise InvalidInputError(f"not a media file (dir): {p}")
    if p.stat().st_size == 0:
        raise ProbeError(f"empty input: {p}")

    version = _ffprobe_version(ffprobe_bin)

    base_args = [
        "-hide_banner", "-loglevel", "error",
        "-of", "json", "-show_format", "-show_streams", str(p),
    ]
    raw = _run_ffprobe(ffprobe_bin, base_args, timeout_s)
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProbeError(f"malformed ffprobe JSON: {e}") from e

    source_hash = _sha256_file(p) if sha256 else None
    probe_obj = _build_probe_from_raw(
        raw, path=str(p), ffprobe_version=version, source_sha256=source_hash
    )

    # sidecars (read-only dir scan)
    sdir = Path(sidecar_dir) if sidecar_dir is not None else p.parent
    probe_obj.sidecars = _list_sidecars(sdir, p.name) if sdir.is_dir() else []

    # VFR: per-frame PTS of the first video stream, only when requested
    if full_fps and probe_obj.video:
        pts = _frame_pts(ffprobe_bin, p, timeout_s)
        probe_obj.vfr_status = vfr_status_from_pts(pts)

    return probe_obj


def _frame_pts(bin: str, path: Path, timeout_s: float) -> list[float]:
    args = [
        "-hide_banner", "-loglevel", "error",
        "-select_streams", "v:0",
        "-show_frames", "-show_entries", "frame=pts_time",
        "-of", "json", str(path),
    ]
    out = _run_ffprobe(bin, args, timeout_s)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return []
    pts: list[float] = []
    for fr in payload.get("frames", []):
        raw = fr.get("pts_time")
        try:
            pts.append(float(raw))
        except (TypeError, ValueError):
            continue
    return pts
