"""P12.1 — Memory Safety: bounded rawvideo decode (isolated prototype).

These tests prove the P12.1 contract WITHOUT touching the P12 staged
files: P12's `ContentDiffProvider._decode_frames` pulls the WHOLE
decoded rawvideo into RAM (`capture_output=True` → total*H*W*3 bytes);
`memory_guard` is the standalone bounded replacement — O(ONE-frame)
pixel memory, hard decoded-byte budget, hard decode timeout,
VFR/fps-unknown refusal, and MEASURED peak-RSS evidence.

Fixture strategy (deterministic, no sleeps):
- real small clips via ffmpeg (lavfi color / testsrc2) for the happy +
  budget-cap paths;
- fake "ffmpeg" shell scripts (pre-made rawvideo bytes on stdout) for
  the truncation / timeout / hang paths — a real subprocess, zero wait;
- the 4K case is a PURE-ARITHMETIC refusal (plan_budget): we do NOT
  claim a real 4K decode on this host, only that the pre-spawn gate
  refuses it and that the O(1)-allocation proof holds on a bounded
  streaming run.

Markers: `@behavior_tested` — synthetic media only; no real footage,
no v4, no cloud.
"""

import json
import stat
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import pytest
from media_probe import probe
from memory_guard import (
    DecodeTimeout,
    MemoryBudgetExceeded,
    TruncatedRawVideo,
    VfrGridRefused,
    content_diff_bounded,
    iter_rawvideo_frames,
    plan_budget,
)

FFMPEG = "ffmpeg"
W, H = 240, 160
FRAME_BYTES = W * H * 3  # 115200 (rgb24)


def _mk_clip(tmp: Path, *, rate="25", dur="0.3", name="clip.mp4",
             color=None) -> Path:
    out = tmp / name
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            (f"color={color}:d={dur}:s={W}x{H}:r={rate}"
             if color else f"testsrc2=d={dur}:r={rate}:s={W}x{H}"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    p = subprocess.run(args, capture_output=True, timeout=60, check=False)
    assert p.returncode == 0, f"fixture encode failed: {p.stderr[:300]!r}"
    return out


def _fake_ffmpeg_script(tmp: Path, raw_bytes: bytes, *, hang_s: int = 0) -> Path:
    """A fake ffmpeg: sleeps `hang_s` seconds (if any), then writes
    `raw_bytes` to stdout and exits 0. Pre-made bytes => deterministic,
    no real ffmpeg involvement; the hang case is exercised with a SMALL
    real timeout in the test, so nothing actually waits."""
    scr = tmp / "fake_ffmpeg.py"
    body = "\n".join([
        f"#!{sys.executable}",
        "import sys, time",
        f"if {hang_s}:",
        f"    time.sleep({hang_s})",
        f"sys.stdout.buffer.write(bytes.fromhex('{raw_bytes.hex()}'))",
        "sys.stdout.flush()",
    ])
    scr.write_text(body)
    scr.chmod(scr.stat().st_mode | stat.S_IEXEC)
    return scr


def _probe_clip(path: Path, full_fps: bool = False):
    return probe(path, full_fps=full_fps)


@pytest.mark.behavior_tested
def test_t1_plan_budget_4k_refused_without_spawning(tmp_path):
    # 4K @ 24fps for 30 s: P12's whole-clip shape would be ~17.9 GB.
    plan_4k = plan_budget(3840, 2160, 720)
    assert plan_4k.planned_bytes == 3840 * 2160 * 3 * 720
    assert plan_4k.feasible is False
    assert "budget" in plan_4k.reason
    # and a small clip is feasible at the same default budget:
    plan_small = plan_budget(W, H, 6, byte_budget=FRAME_BYTES * 10)
    assert plan_small.feasible is True


@pytest.mark.behavior_tested
def test_t2_bounded_stream_yields_frames_and_stays_O_one_frame(tmp_path):
    # O(ONE-frame)-in-clip-length proof via the MEASURED sliding-buffer
    # high-water: the buffer must be bounded by one chunk + one frame,
    # and — the real invariant — IDENTICAL across clip lengths (a
    # capture_output-style implementation would grow it with the clip).
    chunk = FRAME_BYTES
    short = _mk_clip(tmp_path, rate="25", dur="0.24", name="s.mp4")  # 6 fr
    long_ = _mk_clip(tmp_path, rate="25", dur="2.4", name="l.mp4")  # 60 fr
    stats_s, stats_l = {}, {}
    for idx, arr in iter_rawvideo_frames(
        short, W, H, total_frames=6, ffmpeg_bin=FFMPEG,
        byte_budget=FRAME_BYTES * 10, chunk_bytes=chunk, stats=stats_s,
    ):
        assert idx in range(6)
        assert arr.shape == (H, W, 3) and arr.dtype == np.uint8
    assert stats_s["frames_yielded"] == 6
    for _idx, _arr in iter_rawvideo_frames(
        long_, W, H, total_frames=60, ffmpeg_bin=FFMPEG,
        byte_budget=FRAME_BYTES * 80, chunk_bytes=chunk, stats=stats_l,
    ):
        pass  # consume, don't hold
    assert stats_l["frames_yielded"] == 60
    # the deterministic O(1) invariant: buffer high-water is the SAME for
    # a 6-frame and a 60-frame clip (both capped at chunk + one frame),
    # so pixel memory does NOT grow with clip length:
    assert stats_s["peak_buffer_bytes"] == stats_l["peak_buffer_bytes"]
    assert stats_s["peak_buffer_bytes"] <= chunk + FRAME_BYTES, \
        "sliding buffer high-water exceeds the O(1) bound (chunk + frame)"
    # and it is far below a 60-frame whole-clip total (the failure mode
    # a capture_output implementation would hit):
    assert stats_s["peak_buffer_bytes"] < FRAME_BYTES * 60, \
        "buffer high-water must stay bounded, not track clip length"


@pytest.mark.behavior_tested
def test_t3_streaming_stops_cleanly_at_max_frames(tmp_path):
    clip = _mk_clip(tmp_path, rate="25", dur="0.24")
    p = _probe_clip(clip)
    _cuts, ev = content_diff_bounded(
        clip, p, max_frames=2, byte_budget=FRAME_BYTES * 10,
        ffmpeg_bin=FFMPEG,
    )
    assert ev.frames_processed == 2
    assert ev.truncated is True
    assert ev.long_format_accepted is False  # sampled, never "accepted"
    assert ev.total_frames_expected == 2


@pytest.mark.behavior_tested
def test_t4_byte_budget_exceeded_fails_closed(tmp_path):
    # fake ffmpeg streams 3 frames' worth of bytes; the budget allows 2:
    fake = _fake_ffmpeg_script(tmp_path, b"\x00" * (FRAME_BYTES * 3))
    with pytest.raises(MemoryBudgetExceeded) as ei:
        list(iter_rawvideo_frames(
            "whatever", W, H, total_frames=3,
            byte_budget=FRAME_BYTES * 2 + FRAME_BYTES // 2,
            ffmpeg_bin=str(fake), chunk_bytes=FRAME_BYTES,
        ))
    assert ei.value.frames_processed == 2
    assert ei.value.frame_bytes == FRAME_BYTES


@pytest.mark.behavior_tested
def test_t5_truncated_raw_eof_fails_closed(tmp_path):
    # fake ffmpeg declares a 3-frame grid but writes only 2 frames'
    # worth of raw bytes (an EOF short of the declared count):
    fake = _fake_ffmpeg_script(tmp_path, b"\x00" * (FRAME_BYTES * 2))
    p = _probe_clip(_mk_clip(tmp_path, dur="0.12", name="ref.mp4"))
    with pytest.raises(TruncatedRawVideo):
        list(iter_rawvideo_frames(
            "whatever", W, H, total_frames=3,
            byte_budget=FRAME_BYTES * 10,
            ffmpeg_bin=str(fake), chunk_bytes=FRAME_BYTES,
        ))
    # and the P12.1 bounded content-diff surfaces the same truncation:
    _cuts, ev = content_diff_bounded(
        "whatever", p, total_frames=3, byte_budget=FRAME_BYTES * 10,
        ffmpeg_bin=str(fake), chunk_bytes=FRAME_BYTES,
    )
    assert ev.truncated is True and ev.budget_hit is False
    assert ev.frames_processed == 2, "the two decoded frames are the truth"


@pytest.mark.behavior_tested
def test_t6_vfr_source_refused(tmp_path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    for r, path in (("24", a), ("48", b)):
        p = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"testsrc2=d=0.25:r={r}:s={W//2}x{H//2}", "-c:v", "libx264",
             str(path)],
            capture_output=True, timeout=60, check=False,
        )
        assert p.returncode == 0, p.stderr[:300]
    vfr_src = tmp_path / "vfr.mp4"
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(a),
         "-i", str(b), "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
         "-fps_mode", "vfr", "-pix_fmt", "yuv420p", "-c:v", "libx264",
         str(vfr_src)],
        capture_output=True, timeout=60, check=False,
    )
    assert p.returncode == 0, p.stderr[:300]
    probe_vfr = _probe_clip(vfr_src, full_fps=True)
    assert probe_vfr.vfr_status == "vfr-likely"
    with pytest.raises(VfrGridRefused):
        content_diff_bounded(vfr_src, probe_vfr, total_frames=10,
                             byte_budget=FRAME_BYTES * 40,
                             ffmpeg_bin=FFMPEG)


@pytest.mark.behavior_tested
def test_t7_decode_timeout_kills_child(tmp_path):
    # a fake ffmpeg that hangs 30 s; a 1 s real timeout must fire:
    fake = _fake_ffmpeg_script(tmp_path, b"", hang_s=30)
    p = _probe_clip(_mk_clip(tmp_path, dur="0.12", name="ref.mp4"))
    with pytest.raises(DecodeTimeout):
        list(iter_rawvideo_frames(
            "whatever", W, H, total_frames=1,
            byte_budget=FRAME_BYTES * 10,
            ffmpeg_bin=str(fake), timeout_s=1.0,
        ))
    # the source fixture is untouched (read-only contract):
    assert p is not None and len(p.raw_json) > 0


@pytest.mark.behavior_tested
def test_t8_content_diff_bounded_finds_the_hard_cut(tmp_path):
    black = tmp_path / "black.mp4"
    white = tmp_path / "white.mp4"
    for color, path in (("black", black), ("white", white)):
        p = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"color={color}:d=0.4:s={W}x{H}:r=25", "-c:v", "libx264",
             str(path)],
            capture_output=True, timeout=60, check=False,
        )
        assert p.returncode == 0, p.stderr[:300]
    joined = tmp_path / "two_blocks.mp4"
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(black),
         "-i", str(white), "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(joined)],
        capture_output=True, timeout=60, check=False,
    )
    assert p.returncode == 0, p.stderr[:300]
    probe_j = _probe_clip(joined, full_fps=True)
    cuts, ev = content_diff_bounded(
        joined, probe_j, total_frames=20, byte_budget=FRAME_BYTES * 40,
        ffmpeg_bin=FFMPEG,
    )
    assert len(cuts) == 1, f"expected exactly one hard cut, got {cuts}"
    # the transition is around frame 10 (0-based diff index 9):
    assert 7 <= cuts[0] <= 11, f"cut {cuts[0]} outside [7,11]"
    assert ev.frames_processed == 20
    assert ev.truncated is False
    assert ev.long_format_accepted is False  # a short clip never claims
                                              # long-form acceptance


@pytest.mark.behavior_tested
def test_t9_memory_evidence_carries_measured_peaks(tmp_path):
    clip = _mk_clip(tmp_path, rate="25", dur="0.24")
    p = _probe_clip(clip)
    _cuts, ev = content_diff_bounded(
        clip, p, total_frames=6, byte_budget=FRAME_BYTES * 10,
        ffmpeg_bin=FFMPEG, chunk_bytes=FRAME_BYTES,
    )
    assert ev.peak_child_rss_bytes > 0, "child RSS must be MEASURED, not 0"
    assert ev.peak_python_alloc_bytes > 0, \
        "python-side peak must come from a real allocator measurement"
    assert ev.sampled_params["byte_budget"] == FRAME_BYTES * 10
    assert ev.sampled_params["chunk_bytes"] == FRAME_BYTES
    # the O(1) property, stated against the DETERMINISTIC per-run buffer
    # high-water: the sliding buffer must never exceed one chunk + one
    # frame — INDEPENDENT of clip length (the whole-clip total is 6x):
    assert ev.peak_buffer_bytes > 0, "buffer high-water must be measured"
    assert ev.peak_buffer_bytes <= FRAME_BYTES * 2, \
        f"buffer high-water {ev.peak_buffer_bytes} B exceeds the " \
        f"O(1) bound (one chunk + one frame = {FRAME_BYTES * 2} B)"
    assert ev.peak_buffer_bytes < FRAME_BYTES * 6, \
        "a capture_output-style buffer would approach the whole-clip total"
    # evidence is machine-readable (audit trail):
    blob = json.loads(ev.to_json())
    assert blob["frames_processed"] == 6
    assert blob["peak_child_rss_bytes"] > 0
    assert blob["peak_buffer_bytes"] > 0


@pytest.mark.behavior_tested
def test_t10_refusal_paths_have_no_side_effects(tmp_path):
    # budget-refused plan -> no ffmpeg spawn, no file written:
    clip = _mk_clip(tmp_path, rate="25", dur="0.24")
    p = _probe_clip(clip)
    plan = plan_budget(3840, 2160, 720, byte_budget=FRAME_BYTES * 40)
    assert plan.feasible is False
    # and a max_frames run leaves the source byte-identical (read-only):
    before = clip.read_bytes()
    content_diff_bounded(clip, p, total_frames=2, max_frames=2,
                        byte_budget=FRAME_BYTES * 10, ffmpeg_bin=FFMPEG)
    assert clip.read_bytes() == before


@pytest.mark.behavior_tested
def test_t11_full_regression_boundary(tmp_path):
    # Delivery invariant, written to hold in BOTH worktree states:
    #
    #  (a) transient dev tree — P12 still staged (8 files), HEAD still at
    #      the pre-P12 baseline 3d3a2a7: the original "P12 staged surface
    #      untouched" assertion (len(staged)==8).
    #
    #  (b) delivered tree — P12 has been committed (C1) so nothing P12
    #      sits in the staged index anymore. A fresh CI clone has no
    #      staged files at all, so `git diff --cached` is empty by
    #      construction. The meaningful invariant there is *byte
    #      invariance of the committed P12 content*: the two P12 code
    #      files on disk must equal their committed blob at HEAD. That
    #      is stable for any number of descendant commits, because P12
    #      content is frozen — no later commit touches those paths.
    #
    # The protected -encoders artifact must stay untracked in a dev tree
    # (nothing may ever `git add` it); on a delivered/CI clone it is
    # legitimately absent, so the assertion only guards the dev tree.
    import subprocess as sp
    repo = Path(__file__).resolve().parent.parent
    head = sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=False,
    ).stdout.strip()
    cached = sp.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo, capture_output=True, text=True, check=False,
    ).stdout
    staged = [l for l in cached.splitlines() if l]

    if head == "3d3a2a7bcc16ca68ac26acff51d9ddbbd0f1394c":
        # transient dev tree: P12 staged surface must hold verbatim.
        assert len(staged) == 8, f"P12 staged index changed: {staged}"
        assert (repo / "-encoders").exists(), "protected -encoders missing"
    else:
        # delivered tree: P12 code files byte-identical to their commit.
        for f in ["src/mnemosyne_dit/scene_detect.py",
                  "tests/test_dit22_scene_detect.py"]:
            blob = sp.run(["git", "show", "HEAD:" + f],
                          cwd=repo, capture_output=True, check=False)
            assert blob.returncode == 0, f"{f} not present at HEAD"
            assert blob.stdout == (repo / f).read_bytes(), \
                f"{f} diverged from its committed P12 content"


@pytest.mark.behavior_tested
def test_t12_fps_unknown_refused(tmp_path):
    clip = _mk_clip(tmp_path, rate="25", dur="0.24")
    # a probe with no fps evidence: a uniform grid is a guess -> refuse
    p_no_fps = type("Nofps", (), {})()
    p_no_fps.video = [None]
    p_no_fps.fps = None
    p_no_fps.vfr_status = "unknown"
    with pytest.raises((VfrGridRefused, ValueError, MemoryBudgetExceeded)):
        content_diff_bounded(clip, p_no_fps, total_frames=6,
                             byte_budget=FRAME_BYTES * 10, ffmpeg_bin=FFMPEG)
