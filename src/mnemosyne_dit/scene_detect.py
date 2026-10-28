"""scene_detect.py — DIT 2.2 P12 shot boundary detection (providers).

Read-only scene/shot segmentation. Three strictly separated notions
(spec P12 §0 — never conflated):

- **fixed-interval cutting** (a tool, not detection): no confidence;
- **real shot boundary detection** (content-change or neural SBD):
  detector name + model/version + confidence 0..1;
- **semantic event segmentation** (P13): only a reserved enum slot here.

Providers are pluggable and fail closed when a dependency is missing
(`scenedetect`, `tensorflow`/TransNetV2 weights): `is_available()`
reports the honest reason and `detect()` raises `ProviderUnavailable`
rather than fabricating segments. No cloud, no v4 imports, no writes
to the source.

Spec: docs/engineering/spec/P12-shot-boundary-detection.md.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from pathlib import Path

import numpy as np
from media_probe import InvalidInputError as _ProbeInvalidInput
from media_probe import MediaProbe, _reject_url

_DEFAULT_TIMEOUT_S = 120.0


def _refuse_url(source: str) -> None:
    """URL refusal with scene_detect's own exception type (so callers who
    import from this module catch `scene_detect.InvalidInputError`)."""
    try:
        _reject_url(source)
    except _ProbeInvalidInput as e:
        raise InvalidInputError(
            f"refusing to process a network URL ({source!r}); pass a local "
            f"filesystem path"
        ) from e


# ── errors ──────────────────────────────────────────────────────────


class ProviderError(Exception):
    """The provider could not run on this input."""


class InvalidInputError(ProviderError):
    """The caller passed an input we refuse (URL / missing / empty)."""


class ProviderUnavailable(Exception):
    """The provider's optional dependency is not installed (or its
    weights are not bundled) — no silent fallback, no fake segments."""


# ── data model ──────────────────────────────────────────────────────


class BoundaryKind(str, Enum):
    FIXED_INTERVAL = "fixed_interval"  # a tool, NOT detection
    CONTENT_CUT = "content_cut"        # content-change shot detection
    NEURAL_SBD = "neural_sbd"         # neural SBD (TransNetV2 ...)
    SEMANTIC = "semantic"             # P13 slot — not implemented here


@dataclass(frozen=True)
class SceneSegment:
    index: int
    start_frame: int
    end_frame: int  # half-open [start, end)
    start_pts: int | None
    end_pts: int | None
    time_base: str | None
    source_asset_id: str | None
    camera_reel: str | None
    kind: BoundaryKind
    detector: str
    model_version: str | None
    confidence: float | None  # fixed => None; detection => 0..1
    span_seconds: float | None


def assert_contiguous(segments: list[SceneSegment], total_frames: int) -> None:
    """A segmentation of the whole clip must cover [0, total) exactly,
    in order, with no gaps or overlaps. Half-open intervals."""
    if not segments:
        raise ProviderError("no segments — total_frames must be > 0")
    prev_end = 0
    for i, seg in enumerate(segments):
        if seg.index != i or seg.start_frame != prev_end:
            raise ProviderError(
                f"segment {i}: expected start {prev_end}, got "
                f"{seg.start_frame} (contiguity violation)"
            )
        if seg.end_frame <= seg.start_frame:
            raise ProviderError(f"segment {i}: empty/invalid span")
        prev_end = seg.end_frame
    if prev_end != total_frames:
        raise ProviderError(
            f"segments end at {prev_end}, expected total {total_frames}"
        )


def _time_base_to_pts_per_frame(tb: str, fps: Fraction | float) -> int | None:
    """pts = frame * pts_per_frame, in the source time_base units.
    time_base 'num/den' + fps => 1/fps seconds = (1/fps)/(num/den) pts."""
    try:
        num_s, den_s = str(tb).split("/")
        num, den = int(num_s), int(den_s)
        if num <= 0 or den <= 0:
            return None
        fps_f = float(fps)
        if fps_f <= 0:
            return None
        return round((1.0 / fps_f) * (den / num))
    except (ValueError, ZeroDivisionError):
        return None


def _frame_context(m: MediaProbe, fps: Fraction | float | None) -> tuple[int, str | None]:
    """(total_frames, time_base) from a P10 probe + fps (the probe's fps
    is authoritative when the caller did not pass one)."""
    fps_eff = fps if fps is not None else m.fps
    if fps_eff is None:
        raise ValueError(
            "fps unknown (probe reported none and no fps was passed) — "
            "refusing to guess frame counts"
        )
    if m.duration_s is None:
        raise ProviderError("probe has no duration — cannot count frames")
    total = round(m.duration_s * float(fps_eff))
    if total <= 0:
        raise ProviderError("computed total frame count is not > 0")
    mv = m.main_video()
    tb = mv.time_base if mv else None
    return total, tb


# ── providers ───────────────────────────────────────────────────────


class FixedIntervalProvider:
    """Cut every N seconds. A TOOL, not shot detection: kind=
    FIXED_INTERVAL, confidence=None, model_version='fixed'. The last
    interval absorbs the remainder so coverage stays contiguous."""

    name = "fixed-interval"
    detector_label = "fixed-interval"
    model_version = "fixed"

    def __init__(self, seconds: float):
        if seconds <= 0:
            raise ValueError("interval must be > 0 seconds")
        self.seconds = float(seconds)

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def detect(
        self,
        source: str | Path,
        *,
        fps: Fraction | float | None = None,
        source_probe: MediaProbe | None = None,
        source_asset_id: str | None = None,
        camera_reel: str | None = None,
        params: dict | None = None,
    ) -> list[SceneSegment]:
        _refuse_url(str(source))
        if source_probe is None:
            raise ValueError(
                "FixedInterval.detect requires a P10 MediaProbe "
                "(duration is needed to count frames)"
            )
        total, tb = _frame_context(source_probe, fps)
        fps_f = float(fps if fps is not None else source_probe.fps)
        step = max(1, round(self.seconds * fps_f))
        pts_per = _time_base_to_pts_per_frame(tb, fps_f) if tb else None

        segments: list[SceneSegment] = []
        start = 0
        idx = 0
        while start < total:
            end = min(start + step, total)
            segments.append(
                SceneSegment(
                    index=idx,
                    start_frame=start,
                    end_frame=end,
                    start_pts=start * pts_per if pts_per else None,
                    end_pts=end * pts_per if pts_per else None,
                    time_base=tb,
                    source_asset_id=source_asset_id,
                    camera_reel=camera_reel,
                    kind=BoundaryKind.FIXED_INTERVAL,
                    detector=self.detector_label,
                    model_version=self.model_version,
                    confidence=None,
                    span_seconds=(end - start) / fps_f if fps_f else None,
                )
            )
            start = end
            idx += 1
        assert_contiguous(segments, total)
        return segments


class ContentDiffProvider:
    """Deterministic CPU reference SBD: per-frame mean absolute pixel
    difference (ffmpeg rawvideo decode, numpy) with a median-based
    threshold. kind=CONTENT_CUT; confidence in (0, 1] per detected cut.
    Pure CPU, zero new dependencies (numpy + ffmpeg already present).
    """

    name = "content-diff"
    detector_label = "content-diff"
    model_version = "median-x8-v1"

    def __init__(self, threshold_factor: float = 8.0, floor: float = 2.0):
        self.threshold_factor = float(threshold_factor)
        self.floor = float(floor)

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def _decode_frames(
        self,
        source: Path,
        total: int,
        width: int,
        height: int,
        ffmpeg_bin: str,
        timeout_s: float,
    ) -> np.ndarray:
        cmd = [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-an", "-vframes", str(total), "-",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"ffmpeg decode timed out after {timeout_s}s") from e
        if proc.returncode != 0:
            raise ProviderError(
                f"ffmpeg decode failed (exit {proc.returncode}): "
                f"{(proc.stderr or b'')[:500].decode('utf-8', 'replace').strip()}"
            )
        expected = total * height * width * 3
        if len(proc.stdout) < expected:
            raise ProviderError(
                f"decoded {len(proc.stdout)} bytes, expected {expected} "
                f"— undecodable / truncated source"
            )
        return (
            np.frombuffer(proc.stdout[:expected], dtype=np.uint8)
            .reshape(total, height, width, 3)
        )

    def detect(
        self,
        source: str | Path,
        *,
        fps: Fraction | float | None = None,
        source_probe: MediaProbe | None = None,
        source_asset_id: str | None = None,
        camera_reel: str | None = None,
        params: dict | None = None,
        ffmpeg_bin: str = "ffmpeg",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> list[SceneSegment]:
        """A detection provider MUST have fps (explicit or via probe).
        Refusing to run without it (spec #5: no probe + no fps => raise)."""
        _refuse_url(str(source))
        if source_probe is None:
            if fps is None:
                raise ValueError(
                    "ContentDiffProvider requires fps or a P10 MediaProbe; "
                    "refusing to guess the frame grid"
                )
            raise ValueError(
                "ContentDiffProvider requires a P10 MediaProbe "
                "(width/height/time_base + duration are needed to decode "
                "and count frames)"
            )
        src = Path(source)
        if not src.exists():
            raise InvalidInputError(f"no such source: {src}")
        if src.stat().st_size == 0:
            raise InvalidInputError(f"empty source: {src}")

        total, tb = _frame_context(source_probe, fps)
        fps_eff = fps if fps is not None else source_probe.fps
        assert fps_eff is not None  # _frame_context already guaranteed it
        fps_f = float(fps_eff)
        mv = source_probe.main_video()
        width = mv.width if mv is not None else None
        height = mv.height if mv is not None else None
        if width is None or height is None:
            raise ProviderError(
                "probe reported no main-video resolution — refusing to "
                "guess frame dimensions (fail-closed, spec P12 §2.4)"
            )
        pts_per = _time_base_to_pts_per_frame(tb, fps_eff) if tb else None

        frames = self._decode_frames(src, total, width, height, ffmpeg_bin, timeout_s)
        diffs = (
            np.abs(frames[1:].astype(np.int16) - frames[:-1].astype(np.int16))
            .mean(axis=(1, 2, 3))
        )
        median = float(np.median(diffs))
        threshold = max(self.floor, self.threshold_factor * median)
        cuts = [i for i, d in enumerate(diffs) if d > threshold]
        # cut i => boundary between frame i and i+1
        bounds = [0] + [c + 1 for c in cuts] + [total]

        segments: list[SceneSegment] = []
        for k in range(len(bounds) - 1):
            start, end = bounds[k], bounds[k + 1]
            # the confidence of segment k>0 comes from the cut that
            # STARTED it; the first segment's start is the source
            # beginning (not a detected boundary) => None. Honest.
            if k > 0:
                cut_idx = cuts[k - 1]
                conf = min(1.0, float(diffs[cut_idx]) / (threshold * 4))
            else:
                conf = None
            segments.append(
                SceneSegment(
                    index=k,
                    start_frame=start,
                    end_frame=end,
                    start_pts=start * pts_per if pts_per else None,
                    end_pts=end * pts_per if pts_per else None,
                    time_base=tb,
                    source_asset_id=source_asset_id,
                    camera_reel=camera_reel,
                    kind=BoundaryKind.CONTENT_CUT,
                    detector=self.detector_label,
                    model_version=self.model_version,
                    confidence=conf,
                    span_seconds=(end - start) / fps_f if fps_f else None,
                )
            )
        assert_contiguous(segments, total)
        return segments


class PySceneDetectProvider:
    """Adapter contract for PySceneDetect (MIT, clean-room re-usable).
    `scenedetect` is an OPTIONAL dependency: when absent the provider
    reports unavailable and detect() raises ProviderUnavailable — never
    a fabricated fallback. (Behavior with the package installed is
    exercised in an environment that has it; here the unavailable path
    is the pinned contract.)"""

    name = "pyscenedetect"

    def __init__(self, detector: str = "content", threshold: float = 27.0):
        self.detector = detector
        self.threshold = threshold

    def is_available(self) -> tuple[bool, str]:
        try:
            import scenedetect  # noqa: F401
        except ImportError:
            return False, "scenedetect not installed"
        return True, ""

    def detect(
        self,
        source: str | Path,
        *,
        fps: Fraction | float | None = None,
        source_probe: MediaProbe | None = None,
        source_asset_id: str | None = None,
        camera_reel: str | None = None,
        params: dict | None = None,
    ) -> list[SceneSegment]:
        _refuse_url(str(source))  # safety gate first: a URL is refused even
        # for a provider whose optional dependency happens to be present
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailable(
                f"PySceneDetectProvider unavailable: {reason}"
            )
        from scenedetect import detect  # available at this point

        det = _pysd_detector(self.detector, self.threshold)
        scenes = detect(str(source), det)  # list of (start, end) frames
        fps_eff = fps if fps is not None else (
            source_probe.fps if source_probe is not None else None
        )
        fps_f = float(fps_eff) if fps_eff else None
        _mv0 = source_probe.main_video() if source_probe is not None else None
        tb = _mv0.time_base if _mv0 is not None else None
        pts_per = _time_base_to_pts_per_frame(tb, fps_f) if tb and fps_f else None
        segments = [
            SceneSegment(
                index=i,
                start_frame=s,
                end_frame=e,
                start_pts=s * pts_per if pts_per else None,
                end_pts=e * pts_per if pts_per else None,
                time_base=tb,
                source_asset_id=source_asset_id,
                camera_reel=camera_reel,
                kind=BoundaryKind.CONTENT_CUT,
                detector="pyscenedetect",
                model_version=f"{self.detector}/th{self.threshold}",
                confidence=None,  # PySD reports cut positions, not 0..1 conf
                span_seconds=(e - s) / fps_f if fps_f else None,
            )
            for i, (s, e) in enumerate(scenes)
        ]
        if segments:
            assert_contiguous(segments, segments[-1].end_frame)
        return segments


def _pysd_detector(kind: str, threshold: float):
    from scenedetect.detectors import AdaptiveDetector, ContentDetector

    if kind == "adaptive":
        return AdaptiveDetector()
    return ContentDetector(threshold=threshold)


class TransNetV2Provider:
    """Adapter contract for TransNetV2 (neural SBD). Requires
    tensorflow + bundled weights; neither ships in this venv, so the
    pinned contract here is HONEST UNAVAILABILITY. A770 real-hardware
    benchmark is HARDWARE_BLOCKED (no GPU attached to this host) and
    is NOT filled in with fabricated numbers."""

    name = "transnetv2"
    a770_benchmark = "HARDWARE_BLOCKED"  # contract marker, not a number

    def __init__(self, model_dir: str | None = None, threshold: float = 0.5):
        self.model_dir = model_dir
        self.threshold = threshold

    def is_available(self) -> tuple[bool, str]:
        try:
            import tensorflow  # noqa: F401
        except ImportError:
            return False, "tensorflow not installed"
        if self.model_dir is None:
            return False, "TransNetV2 weights directory not provided"
        p = Path(self.model_dir)
        if not p.is_dir():
            return False, f"TransNetV2 weights missing at {p}"
        return True, ""

    def detect(
        self,
        source: str | Path,
        *,
        fps: Fraction | float | None = None,
        source_probe: MediaProbe | None = None,
        source_asset_id: str | None = None,
        camera_reel: str | None = None,
        params: dict | None = None,
    ) -> list[SceneSegment]:
        _refuse_url(str(source))  # safety gate runs regardless of availability
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailable(
                f"TransNetV2Provider unavailable: {reason}"
            )
        # tensorflow-based inference path: run only when available.
        from transnetv2 import TransNetV2  # provided alongside weights

        model = TransNetV2(model_dir=self.model_dir)
        _out, _single, many = model.predict_video(str(source))
        pred = many.numpy()
        boundaries = _transnet_boundaries(pred, self.threshold)
        fps_eff = fps if fps is not None else (
            source_probe.fps if source_probe is not None else None
        )
        fps_f = float(fps_eff) if fps_eff else None
        _mv0 = source_probe.main_video() if source_probe is not None else None
        tb = _mv0.time_base if _mv0 is not None else None
        pts_per = _time_base_to_pts_per_frame(tb, fps_f) if tb and fps_f else None
        segments = [
            SceneSegment(
                index=i,
                start_frame=s,
                end_frame=e,
                start_pts=s * pts_per if pts_per else None,
                end_pts=e * pts_per if pts_per else None,
                time_base=tb,
                source_asset_id=source_asset_id,
                camera_reel=camera_reel,
                kind=BoundaryKind.NEURAL_SBD,
                detector="transnetv2",
                model_version="transnetv2/so-czech",
                confidence=float(pred[s]) if s < len(pred) else None,
                span_seconds=(e - s) / fps_f if fps_f else None,
            )
            for i, (s, e) in enumerate(boundaries)
        ]
        if segments:
            assert_contiguous(segments, segments[-1].end_frame)
        return segments


def _transnet_boundaries(pred: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    """Frame-level predictions -> [start, end) scene pairs (0-based,
    half-open). The "many-hot" boundary signal marks frames that sit on a
    shot change; a cut is placed at EVERY index where the binary signal
    flips (0->1 at the boundary run's start, 1->0 at its end). Cuts are
    strictly increasing, so no segment is ever empty; the whole range is
    always covered, including an all-1s or all-0s input."""
    binary = (pred >= threshold).astype(int)
    total = len(pred)
    if total == 0:
        return []
    cuts = [0]
    for i in range(1, total):
        if binary[i] != binary[i - 1]:
            cuts.append(i)
    cuts.append(total)
    return [(cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1)]
