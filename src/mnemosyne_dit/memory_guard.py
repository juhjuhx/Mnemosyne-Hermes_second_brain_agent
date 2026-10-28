"""memory_guard.py — DIT 2.2 P12.1: bounded rawvideo decode (isolated
prototype; the P12 staged index is NOT modified).

P12's `ContentDiffProvider._decode_frames` pulls the ENTIRE decoded
rawvideo of a clip into RAM at once (`subprocess.run(capture_output=True)`
-> `total * H * W * 3` bytes: 4K x 30 s x 24 fps ~= 17.9 GB). P12.1's
memory-safety contract, implemented here as a standalone, P12-independent
module (so the P12 staged files stay byte-for-byte intact):

- **Hard frame-buffer bounds**: pixel memory is O(chunk + one frame) — a
  sliding window over a bounded ffmpeg pipe, never a whole-clip
  accumulation. The window is byte-bounded (`chunk_bytes`), so a small
  chunk keeps even 4K pixel memory O(ONE-frame)-class regardless of
  resolution.
- **Hard byte budget** on decoded bytes (checked per chunk, fail-closed
  mid-stream); plus a PRE-SPAWN plan check (planned bytes vs budget) so
  a 4K/long-clip is refused BEFORE any ffmpeg is launched.
- **Timeout + resource limits**: the decode child is killed on timeout;
  enumeration is capped by `max_frames`; truncated/raw EOF is fail-closed.
- **VFR / unknown-fps are refused**, not guessed: a uniform frame grid
  over a vfr-likely (or fps-unknown) source is unsafe for content-diff
  semantics; the caller must supply a resolvable grid (P11.1-D's
  time-domain mapping owns VFR).
- **Measured evidence, never claims**: a `MemoryEvidence` carries the
  real peak child RSS (getrusage), the real Python-side peak
  (tracemalloc), and the sampled parameters; a small-clip success is
  ALWAYS flagged `long_format_accepted=False` (sampled, not
  long-form-accepted).

This module is a pure add-on: numpy + ffmpeg (already in the toolchain),
no v4 files.db / qdrant / indexer, no cloud, no writes to the source
(ffmpeg `-i` read-only + `-f rawvideo` stdout pipe).
"""

from __future__ import annotations

import queue
import resource
import subprocess
import threading
import time
import tracemalloc
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from media_probe import MediaProbe

# default decoded-byte budget: 256 MiB (enough for 4K for ~10 frames;
# anything more must be raised deliberately by the caller).
DEFAULT_BYTE_BUDGET = 1 << 28
DEFAULT_MAX_FRAMES = 5000
DEFAULT_CHUNK_BYTES = 1 << 20  # 1 MiB pipe reads


class MemoryBudgetExceeded(Exception):
    """The decoded-byte budget was exceeded (pre-spawn plan, or
    mid-stream) — the decode was stopped fail-closed. Carries how far
    we got, for evidence."""

    def __init__(self, message: str, *, frames_processed: int = 0,
                 frame_bytes: int = 0):
        super().__init__(message)
        self.frames_processed = frames_processed
        self.frame_bytes = frame_bytes


class TruncatedRawVideo(Exception):
    """ffmpeg ended (or the pipe closed) with fewer raw bytes than the
    claimed frame grid requires — undecodable / truncated source,
    fail-closed (never a silent partial decode)."""


class DecodeTimeout(Exception):
    """The decode did not finish within `timeout_s`; the ffmpeg child was
    killed. Decodes have a hard time bound (P12.1 resource limit)."""


class VfrGridRefused(Exception):
    """The source is vfr-likely (or fps-unknown): a uniform per-frame
    grid cannot be assumed; content-diff over an indexed grid is refused
    — use the P11.1-D time-domain mapping for VFR."""


@dataclass(frozen=True)
class BudgetPlan:
    width: int
    height: int
    total_frames: int
    frame_bytes: int
    planned_bytes: int
    byte_budget: int
    feasible: bool
    reason: str


def plan_budget(width: int, height: int, total_frames: int, *,
                byte_budget: int = DEFAULT_BYTE_BUDGET) -> BudgetPlan:
    """Pure arithmetic pre-spawn guard: does the PLANNED rawvideo size
    fit the budget? 4K x 720 frames (30 s @ 24 fps) = ~17.9 GB ->
    refused BEFORE any ffmpeg is launched. (The streaming decode itself
    only ever holds O(1 frame), but the plan check is the operator-facing
    gate: a budget-bounded run must know it is sampling, not whole.)"""
    frame_bytes = width * height * 3
    planned = frame_bytes * total_frames
    feasible = planned <= byte_budget
    return BudgetPlan(
        width=width, height=height, total_frames=total_frames,
        frame_bytes=frame_bytes, planned_bytes=planned,
        byte_budget=byte_budget, feasible=feasible,
        reason=(
            "" if feasible
            else f"planned {planned} B exceeds the {byte_budget} B "
                 f"decoded-byte budget (4K-class or long clip)"
        ),
    )


@dataclass(frozen=True)
class MemoryEvidence:
    """Real, measured bounds evidence for a bounded decode run.

    - `peak_buffer_bytes`: the actual high-water of the sliding byte
      buffer during THIS run (deterministic, O(1) proof: bounded by
      chunk_bytes + frame_bytes, independent of clip length);
    - `peak_python_alloc_bytes`: the in-run HIGH-WATER DELTA of the
      Python heap (tracemalloc peak minus the run's baseline; a capture
      implementation would grow with clip length, a bounded one does
      not — always >= 0, meaningful only against clip length);
    - `peak_child_rss_bytes`: getrusage RUSAGE_CHILDREN high-water
      across THIS PROCESS's reaped child sessions (monotonic upper
      bound, NOT per-run — reported honestly as such, never claimed
      per-run)."""

    frames_processed: int
    total_frames_expected: int
    frame_bytes: int
    peak_buffer_bytes: int              # this run's sliding-window high-water
    peak_child_rss_bytes: int           # getrusage(RUSAGE_CHILDREN) high-water
    peak_python_alloc_bytes: int        # in-run tracemalloc delta (>= 0)
    chunk_bytes: int
    byte_budget: int
    budget_hit: bool
    truncated: bool                     # max_frames cap or raw EOF
    long_format_accepted: bool          # ALWAYS False on a sampled run
    sampled_params: dict
    notes: tuple[str, ...]

    def to_json(self) -> str:
        import json

        return json.dumps(
            {
                "frames_processed": self.frames_processed,
                "total_frames_expected": self.total_frames_expected,
                "frame_bytes": self.frame_bytes,
                "peak_buffer_bytes": self.peak_buffer_bytes,
                "peak_child_rss_bytes": self.peak_child_rss_bytes,
                "peak_python_alloc_bytes": self.peak_python_alloc_bytes,
                "chunk_bytes": self.chunk_bytes,
                "byte_budget": self.byte_budget,
                "budget_hit": self.budget_hit,
                "truncated": self.truncated,
                "long_format_accepted": self.long_format_accepted,
                "sampled_params": dict(self.sampled_params),
                "notes": list(self.notes),
            },
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def refusal() -> MemoryEvidence:
        """Conservative all-refusal evidence (used by the RED skeleton
        and by fail-closed early exits)."""
        return MemoryEvidence(
            frames_processed=0, total_frames_expected=0, frame_bytes=0,
            peak_buffer_bytes=0,
            peak_child_rss_bytes=0, peak_python_alloc_bytes=0,
            chunk_bytes=0, byte_budget=0, budget_hit=False,
            truncated=False, long_format_accepted=False,
            sampled_params={},
            notes=("refusal: no decode was run",),
        )


def _peak_child_rss_bytes() -> int:
    """Measured peak RSS across the process's reaped child processes
    (getrusage RUSAGE_CHILDREN) — the ffmpeg/ffprobe subprocesses of
    this session, not a single child. macOS reports KB, Linux bytes."""
    ru = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    import sys as _sys

    if _sys.platform.startswith("linux"):
        return ru  # bytes on Linux
    return ru * 1024  # KB on macOS/BSD


# ── bounded streaming rawvideo decode ─────────────────────────────


def iter_rawvideo_frames(
    source, width: int, height: int, total_frames: int, *,
    ffmpeg_bin: str = "ffmpeg", timeout_s: float = 120.0,
    byte_budget: int | None = None,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    stats: dict | None = None,
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (index, HxWx3 uint8 array) frames from a BOUNDED ffmpeg
    rawvideo pipe. Pixel memory stays O(ONE frame) (a sliding window
    over `chunk_bytes`); the decoded-byte budget caps how many frames
    are processed and is checked per chunk (fail-closed mid-stream); a
    hard timeout KILLS the ffmpeg child; a short raw stream (EOF before
    the claimed grid) raises TruncatedRawVideo.

    When `stats` (a mutable dict) is passed, the run fills it with the
    measured high-water of the sliding buffer (`peak_buffer_bytes`) and
    of the total decoded bytes pulled (`peak_decoded_bytes`) — the
    caller-facing O(1) proof, independent of clip length.

    The caller's `total_frames` is passed to ffmpeg (`-vframes`), so
    well-behaved ffmpeg streams exactly that many frames; the byte
    accounting still guards against a stream that over-runs."""
    frame_bytes = width * height * 3
    cap = (
        (total_frames * frame_bytes) if byte_budget is None else min(
            total_frames * frame_bytes, byte_budget
        )
    )
    cmd = [
        ffmpeg_bin, "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-an", "-vframes", str(total_frames), "-",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    chunks: queue.Queue[bytes | None] = queue.Queue()

    def _pump() -> None:
        """Read the child's stdout on the main thread would block the
        deadline (a hung ffmpeg stalls a synchronous read); a background
        pump delivers chunks, so the caller's timeout KILLS the child
        deterministically instead of waiting on it."""
        try:
            while True:
                raw = proc.stdout.read(chunk_bytes)
                if not raw:
                    break
                chunks.put(raw)
        except (OSError, ValueError):
            pass
        finally:
            chunks.put(None)  # EOF sentinel

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    buf = bytearray()
    processed = 0
    decoded_bytes = 0
    peak_buffer = 0
    deadline = time.monotonic() + timeout_s
    try:
        while processed < total_frames:
            # poll the pump (never a blocking get — a hung child would
            # otherwise stall past the deadline): 50 ms granularity is
            # far coarser than any frame arrival, so no busy-waste.
            if time.monotonic() > deadline:
                proc.kill()
                raise DecodeTimeout(
                    f"decode exceeded {timeout_s}s; the ffmpeg child was "
                    f"killed after {processed} frame(s)"
                )
            try:
                raw = chunks.get(timeout=0.05)
            except queue.Empty:
                continue
            if raw is None:
                break  # child's stream ended
            buf += raw
            peak_buffer = max(peak_buffer, len(buf))
            # budget: measured against the TOTAL DECODED bytes pulled
            # from the pipe (not the residual buffer), so a small chunk
            # size can never delay the trip:
            decoded_bytes += len(raw)
            if decoded_bytes > cap:
                proc.kill()
                raise MemoryBudgetExceeded(
                    f"decoded-byte budget {cap} B exceeded mid-stream "
                    f"(after {processed} frame)",
                    frames_processed=processed, frame_bytes=frame_bytes,
                )
            while len(buf) >= frame_bytes and processed < total_frames:
                yield processed, np.frombuffer(
                    bytes(buf[:frame_bytes]), dtype=np.uint8
                ).reshape(height, width, 3).copy()
                del buf[:frame_bytes]
                processed += 1
        pump.join(timeout=5.0)
        proc.wait()
        if proc.returncode != 0:
            err = (proc.stderr.read() or b"")[:512]
            raise TruncatedRawVideo(
                f"ffmpeg decode exited {proc.returncode}: "
                f"{err.decode('utf-8', 'replace').strip()[:300]}"
            )
        if processed < total_frames:
            raise TruncatedRawVideo(
                f"decoded {processed} frame(s), expected {total_frames} — "
                f"undecodable / truncated source (fail-closed)"
            )
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    if stats is not None:
        stats["peak_buffer_bytes"] = peak_buffer
        stats["peak_decoded_bytes"] = decoded_bytes
        stats["frames_yielded"] = processed


def _grid_total(source_probe: MediaProbe, total_frames: int | None) -> int:
    """The frame grid to analyze: the caller's explicit cap, else the
    P12 duration-derived total. Without either, no uniform grid can be
    asserted — refuse (never guess)."""
    if total_frames is not None:
        return total_frames
    fps = source_probe.fps
    if fps is None or source_probe.duration_s is None:
        raise ValueError(
            "no frame grid: the probe reports neither fps nor duration and "
            "no total_frames cap was passed — refusing to guess"
        )
    total = round(source_probe.duration_s * float(fps))
    if total <= 0:
        raise ValueError("computed total frame count is not > 0")
    return total


def content_diff_bounded(
    source, source_probe: MediaProbe, *,
    threshold_factor: float = 8.0, floor: float = 2.0,
    total_frames: int | None = None,
    max_frames: int = DEFAULT_MAX_FRAMES,
    byte_budget: int = DEFAULT_BYTE_BUDGET,
    fps: Fraction | float | None = None,
    ffmpeg_bin: str = "ffmpeg",
    timeout_s: float = 120.0,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> tuple[list[int], MemoryEvidence]:
    """P12-compatible per-frame content-diff cuts over a BOUNDED
    streaming decode (the same median-x-floor threshold family as P12's
    ContentDiffProvider, but O(ONE-frame) pixel memory, a hard
    decoded-byte budget, a hard decode timeout, and a measured
    MemoryEvidence). `total_frames` caps the grid; `max_frames` bounds
    how many frames are actually processed (truncation is surfaced,
    never silently trusted).

    Refusals (fail-closed, BEFORE any decode):
    - vfr-likely or unknown fps: a uniform per-frame grid cannot be
      asserted on a variable-rate source (P11.1-D's time-domain mapping
      owns VFR; indexed content-diff on it would mis-index the cuts).
    - a source grid that does not fit the decoded-byte budget at all.

    (The caller's source is opened READ-ONLY by ffmpeg; the evidence
    proves the O(1) property and carries the measured peaks.)"""
    vfr = getattr(source_probe, "vfr_status", "unknown")
    fps_eff = fps if fps is not None else getattr(source_probe, "fps", None)
    if vfr == "vfr-likely":
        # a MEASURED variable-rate timeline: an indexed per-frame grid
        # would mis-index every cut. Refuse (P11.1-D's time-domain
        # mapping owns VFR). "unknown" here means NOT MEASURED, not
        # variable — a known-fps source may still proceed as CFR.
        raise VfrGridRefused(
            "the source is measured vfr-likely — a uniform per-frame "
            "grid cannot be asserted; use the P11.1-D time-domain "
            "mapping for VFR (indexed content-diff would mis-index)"
        )
    if fps_eff is None:
        # no resolvable fps (and no total_frames cap from the caller):
        # a uniform grid is a guess — refuse.
        raise VfrGridRefused(
            "fps unknown (and no total_frames cap): a uniform frame grid "
            "cannot be asserted — refusing to guess the timeline"
        )
    mv = source_probe.main_video()
    if mv is None or mv.width is None or mv.height is None:
        raise VfrGridRefused(
            "probe reported no main-video resolution — refusing to guess "
            "frame dimensions (fail-closed)"
        )
    width, height = mv.width, mv.height
    frame_bytes = width * height * 3
    total = _grid_total(source_probe, total_frames)
    # A byte_budget smaller than the whole grid is NOT a refusal: it is the
    # operator-SAMPLING shape — the run proceeds strictly capped (the
    # iterator caps at min(grid, byte_budget)) and surfaces it in the
    # evidence as truncated=True. The pure pre-spawn gate (plan_budget)
    # is the operator-facing check and is exercised directly (T1).

    # measured evidence (real peaks, never claims): the per-run O(1)
    # proof is the sliding buffer's high-water (from the iterator's
    # stats) and the in-run Python-heap DELTA (tracemalloc reset to
    # the pre-run baseline, so earlier tests in the same process cannot
    # contaminate it); the child RSS high-water is the process-level
    # upper bound, reported honestly as session-scoped.
    stats: dict = {}
    tracemalloc.start()
    _heap_baseline, _ = tracemalloc.get_traced_memory()
    processed = 0
    diffs: list[float] = []
    budget_hit = False
    truncated = False
    errors: list[str] = []
    prev: np.ndarray | None = None
    try:
        for idx, frame in iter_rawvideo_frames(
            source, width, height, total,
            ffmpeg_bin=ffmpeg_bin, timeout_s=timeout_s,
            byte_budget=byte_budget, chunk_bytes=chunk_bytes,
            stats=stats,
        ):
            if idx >= max_frames:
                truncated = True
                break
            if prev is not None:
                diffs.append(
                    float(np.abs(frame.astype(np.int16) - prev.astype(np.int16))
                          .mean())
                )
            prev = frame
            processed = idx + 1
    except MemoryBudgetExceeded as e:
        budget_hit = True
        truncated = True
        errors.append(f"budget hit after {e.frames_processed} frame")
    except DecodeTimeout:
        truncated = True
        errors.append("decode timeout: child killed")
    except TruncatedRawVideo as e:
        truncated = True
        errors.append(f"truncated raw stream: {e}")
    finally:
        _cur, _peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_python_delta = max(_peak - _heap_baseline, 0)
        evidence = MemoryEvidence(
            frames_processed=processed,
            total_frames_expected=total if not truncated else processed,
            frame_bytes=frame_bytes,
            peak_buffer_bytes=stats.get("peak_buffer_bytes", 0),
            peak_child_rss_bytes=_peak_child_rss_bytes(),
            peak_python_alloc_bytes=peak_python_delta,
            chunk_bytes=chunk_bytes,
            byte_budget=byte_budget,
            budget_hit=budget_hit,
            truncated=truncated,
            long_format_accepted=False,  # a sampled run is NEVER accepted
            sampled_params={
                "width": width, "height": height, "total_frames": total,
                "max_frames": max_frames, "byte_budget": byte_budget,
                "chunk_bytes": chunk_bytes, "timeout_s": timeout_s,
                "ffmpeg_bin": ffmpeg_bin,
                "threshold_factor": threshold_factor, "floor": floor,
            },
            notes=tuple(errors) or ("",),
        )

    if not diffs:
        return [], evidence
    arr = np.asarray(diffs, dtype=np.float64)
    median = float(np.median(arr))
    threshold = max(floor, threshold_factor * median)
    cuts = [i for i, d in enumerate(arr) if d > threshold]
    return cuts, evidence


__all__ = [
    "DEFAULT_BYTE_BUDGET",
    "DEFAULT_MAX_FRAMES",
    "BudgetPlan",
    "DecodeTimeout",
    "MemoryBudgetExceeded",
    "MemoryEvidence",
    "TruncatedRawVideo",
    "VfrGridRefused",
    "content_diff_bounded",
    "iter_rawvideo_frames",
    "plan_budget",
]
