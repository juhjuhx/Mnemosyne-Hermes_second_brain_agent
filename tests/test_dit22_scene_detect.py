"""P12 shot boundary detection — contract tests for `scene_detect`.

Synthetic ffmpeg fixtures (tmp_path, zero real media). Spec:
docs/engineering/spec/P12-shot-boundary-detection.md.

Markers: `@behavior_tested` = real ffmpeg fixture + provider run;
`@fixture_only` = pure logic (providers without their optional
dependency installed — this venv has neither scenedetect nor
tensorflow, so the unavailable contract is what is pinned).

A770 real-hardware benchmark: HARDWARE_BLOCKED (no GPU on this host);
contract-only, no fabricated numbers.
"""

import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from media_probe import MediaProbe, VideoStream, probe
from scene_detect import (
    BoundaryKind,
    ContentDiffProvider,
    FixedIntervalProvider,
    InvalidInputError,
    ProviderError,
    ProviderUnavailable,
    PySceneDetectProvider,
    TransNetV2Provider,
    _transnet_boundaries,
    assert_contiguous,
)

FFMPEG = "ffmpeg"


def _mk(path: Path, *ffmpeg_args: str) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         *ffmpeg_args, str(path)],
        check=True,
    )
    assert path.exists() and path.stat().st_size > 0
    return path


def _two_scenes(tmp_path: Path, total_s: float = 2.0) -> tuple[Path, int]:
    """A/B hard-cut, `total_s` TOTAL (each half = total_s/2), cut at the
    half-point. Returns (path, cut_frame) at 24p. Zero real media."""
    half = total_s / 2
    a = _mk(tmp_path / "a.mp4",
            "-f", "lavfi", "-i", f"testsrc=duration={half}:size=320x240:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p")
    b = _mk(tmp_path / "b.mp4",
            "-f", "lavfi", "-i", f"smptebars=duration={half}:size=320x240:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p")
    (tmp_path / "list.txt").write_text(f"file '{a}'\nfile '{b}'\n")
    cut = round(half * 24)
    out = _mk(tmp_path / "two.mp4",
               "-f", "concat", "-safe", "0", "-i", str(tmp_path / "list.txt"),
               "-fps_mode", "cfr", "-c:v", "libx264", "-pix_fmt", "yuv420p")
    return out, cut


# ── 1. fixed interval: remainder absorbed, no detection semantics ──


@pytest.mark.behavior_tested
def test_fixed_interval_tool_semantics(tmp_path):
    src, _ = _two_scenes(tmp_path, total_s=1.0)
    m = probe(src)
    segs = FixedIntervalProvider(seconds=0.25).detect(
        src, source_probe=m, source_asset_id="asset-1", camera_reel="A001"
    )
    assert len(segs) == 4, "1.0s @24p in 0.25s steps => 4 segments"
    for s in segs:
        assert s.kind == BoundaryKind.FIXED_INTERVAL
        assert s.confidence is None, "a fixed tool has NO detection confidence"
        assert s.model_version == "fixed"
        assert s.source_asset_id == "asset-1" and s.camera_reel == "A001"
    assert segs[0].start_frame == 0 and segs[-1].end_frame == round(m.duration_s * float(m.fps))
    # pts mapping comes from the probe's time_base (tested precisely in #4):
    tb = segs[0].time_base
    assert tb and "/" in tb
    if segs[0].start_pts is not None:
        assert segs[0].end_pts is not None and segs[0].end_pts >= segs[0].start_pts


@pytest.mark.behavior_tested
def test_fixed_interval_remainder_absorbed(tmp_path):
    src, _ = _two_scenes(tmp_path, total_s=1.0)
    m = probe(src)
    total = round(m.duration_s * float(m.fps))
    segs = FixedIntervalProvider(seconds=0.3).detect(src, source_probe=m)
    assert segs[0].end_frame - segs[0].start_frame == round(0.3 * m.fps)
    assert segs[-1].end_frame == total, "last interval absorbs the remainder"
    assert segs[-1].end_frame - segs[-1].start_frame <= segs[0].end_frame - segs[0].start_frame


# ── 2. content diff detects the known hard cut ─────────────────────


@pytest.mark.behavior_tested
def test_content_diff_detects_known_hard_cut(tmp_path):
    src, cut = _two_scenes(tmp_path, total_s=1.0)
    m = probe(src)
    segs = ContentDiffProvider().detect(src, source_probe=m)
    assert len(segs) >= 2, "the known cut must split the clip"
    boundary = segs[0].end_frame
    assert abs(boundary - cut) <= 1, (
        f"detected cut {boundary} must land within 1 frame of the known "
        f"cut {cut}"
    )
    assert segs[0].kind == BoundaryKind.CONTENT_CUT
    assert segs[0].detector == "content-diff"
    assert segs[0].confidence is None, "segment 0 starts at the source " \
        "beginning — no detected boundary"
    assert segs[1].confidence is not None and 0 < segs[1].confidence <= 1
    assert_contiguous(segs, round(m.duration_s * float(m.fps)))


# ── 3. contiguity invariant ─────────────────────────────────────────


@pytest.mark.fixture_only
def test_assert_contiguous_rejects_gaps_overlaps_and_shortfall():
    from scene_detect import SceneSegment
    def seg(i, s, e):
        return SceneSegment(i, s, e, None, None, None, None, None,
                            BoundaryKind.FIXED_INTERVAL, "fixed", "fixed",
                            None, None)
    assert_contiguous([seg(0, 0, 5), seg(1, 5, 10)], 10)
    with pytest.raises(ProviderError):
        assert_contiguous([seg(0, 0, 5), seg(1, 6, 10)], 10)      # gap
    with pytest.raises(ProviderError):
        assert_contiguous([seg(0, 0, 5), seg(1, 5, 8)], 10)       # shortfall
    with pytest.raises(ProviderError):
        assert_contiguous([seg(0, 0, 5), seg(0, 5, 10)], 10)      # index mismatch
    with pytest.raises(ProviderError):
        assert_contiguous([], 10)


# ── 4. source correspondence copied from the probe ────────────────


@pytest.mark.behavior_tested
def test_source_correspondence_from_probe(tmp_path):
    src, _ = _two_scenes(tmp_path, total_s=1.0)
    m = probe(src)
    segs = ContentDiffProvider().detect(
        src, source_probe=m, source_asset_id="asset-9", camera_reel="B007"
    )
    for s in segs:
        assert s.source_asset_id == "asset-9" and s.camera_reel == "B007"
        assert s.time_base == m.main_video().time_base, \
            "time_base must come from the P10 probe verbatim"
        if s.start_pts is not None:
            assert s.end_pts is not None and s.end_pts >= s.start_pts
            pts_per = s.start_pts // s.start_frame if s.start_frame else s.end_pts // s.end_frame
            assert pts_per > 0
            # pts/frame must equal (timebase_den/timebase_num)/fps
            num, den = [int(x) for x in s.time_base.split("/")]
            expect_pps = round((den / num) / float(m.fps))
            assert abs(pts_per - expect_pps) <= 1, \
                f"pts/frame {pts_per} != expected {expect_pps}"


# ── 5. detection without fps: refuse, do not guess ────────────────


@pytest.mark.behavior_tested
def test_detection_without_probe_or_fps_refuses(tmp_path):
    src, _ = _two_scenes(tmp_path, total_s=0.5)
    p = ContentDiffProvider()
    with pytest.raises(ValueError, match="refus"):
        p.detect(src)  # no probe, no fps -> fail-closed


@pytest.mark.behavior_tested
def test_fixed_interval_requires_probe(tmp_path):
    src, _ = _two_scenes(tmp_path, total_s=0.5)
    with pytest.raises(ValueError, match="MediaProbe"):
        FixedIntervalProvider(seconds=0.25).detect(src)


@pytest.mark.fixture_only
def test_content_diff_refuses_unknown_resolution(tmp_path):
    """Review Minor #1 pin: when the probe has no main-video resolution
    (width/height None but fps+duration known), the provider must
    fail closed — never fabricate a 320x240 default grid."""
    src, _ = _two_scenes(tmp_path, total_s=0.5)
    unknown_mv = VideoStream(
        index=0, codec="h264", width=None, height=None,
        pix_fmt=None, r_frame_rate="24/1", avg_frame_rate="24/1",
        time_base="1/24000", start_time=0.0,
        color_primaries=None, color_transfer=None, color_space=None,
    )
    m = MediaProbe(
        path=str(src), ffprobe_version="9.0.2", container="mov",
        duration_s=0.5, nb_streams=1, video=[unknown_mv],
        audio=[], fps=Fraction(24, 1), fps_status="ok",
        vfr_status="cfr", timecode=None, timecode_basis="no-guess",
        camera_family="unknown", family_verified=False,
    )
    with pytest.raises(ProviderError, match="resolution"):
        ContentDiffProvider().detect(src, source_probe=m)


# ── 6. PySceneDetect: unavailable contract on this venv ───────────


@pytest.mark.fixture_only
def test_pyscenedetect_unavailable_contract():
    p = PySceneDetectProvider()
    ok, reason = p.is_available()
    if not ok:
        assert "scenedetect" in reason.lower()
        # no dependency => detect must refuse, never fabricate:
        with pytest.raises(ProviderUnavailable):
            p.detect("some.mp4")
    else:
        pytest.skip("scenedetect installed — behavior tested elsewhere")


# ── 7. TransNetV2: unavailable + A770 hardware-blocked marker ─────


@pytest.mark.fixture_only
def test_transnet_unavailable_contract():
    p = TransNetV2Provider(model_dir="/nonexistent")
    ok, _reason = p.is_available()
    if not ok:
        with pytest.raises(ProviderUnavailable):
            p.detect("some.mp4")
    # the A770 benchmark is a contract marker, never a fabricated number:
    assert p.a770_benchmark == "HARDWARE_BLOCKED"


@pytest.mark.fixture_only
def test_transnet_boundaries_extraction():
    import numpy as np
    # two scenes: frames 0-9 low, 10-19 high, 20-29 low
    pred = np.concatenate([np.zeros(10), np.ones(10), np.zeros(10)])
    b = _transnet_boundaries(pred, 0.5)
    assert b == [(0, 10), (10, 20), (20, 30)]
    # all-low -> one scene covering the whole range
    assert _transnet_boundaries(np.zeros(5), 0.5) == [(0, 5)]
    # all-high edge case must still return a covering pair, not empty
    assert _transnet_boundaries(np.ones(5), 0.5) in ([(0, 5)],)
    # empty prediction array -> no segments (review Minor #2 pin)
    assert _transnet_boundaries(np.zeros(0), 0.5) == []


# ── 8. URL input refused before any work ───────────────────────────


@pytest.mark.fixture_only
def test_url_source_refused(tmp_path):
    for prov in (FixedIntervalProvider(0.25), ContentDiffProvider(),
                 PySceneDetectProvider(), TransNetV2Provider()):
        with pytest.raises(InvalidInputError, match="network URL"):
            prov.detect("http://example.com/c.mp4")


# ── 9. corrupt source -> ProviderError, no segments, no writes ───


@pytest.mark.behavior_tested
def test_corrupt_source_raises(tmp_path):
    good, _ = _two_scenes(tmp_path, total_s=0.5)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(good.read_bytes()[:200])
    m_probe = probe(good)  # a probe of the GOOD clip, used for grid
    with pytest.raises(ProviderError):
        ContentDiffProvider().detect(bad, source_probe=m_probe)
    with pytest.raises(InvalidInputError):
        ContentDiffProvider().detect(tmp_path / "nope.mp4", source_probe=m_probe)
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(InvalidInputError, match="empty"):
        ContentDiffProvider().detect(empty, source_probe=m_probe)


# ── 10. fixed interval: non-integer-second boundaries stay valid ──


@pytest.mark.behavior_tested
def test_fixed_interval_no_duplicate_or_gap(tmp_path):
    src, _ = _two_scenes(tmp_path, total_s=1.0)
    m = probe(src)
    total = round(m.duration_s * float(m.fps))
    for sec in (0.25, 0.3, 0.4, 0.7, 1.5, 5.0):
        segs = FixedIntervalProvider(seconds=sec).detect(src, source_probe=m)
        assert segs and segs[0].start_frame == 0
        assert segs[-1].end_frame == total, f"{sec}s: last seg must reach {total}"
        for i in range(1, len(segs)):
            assert segs[i].start_frame == segs[i - 1].end_frame, f"{sec}s: gap"
            assert segs[i].index == i


# ── misc: kind separation, no verdict surface ─────────────────────


@pytest.mark.fixture_only
def test_three_modes_are_distinct_kinds():
    assert BoundaryKind.FIXED_INTERVAL.value == "fixed_interval"
    assert BoundaryKind.CONTENT_CUT.value == "content_cut"
    assert BoundaryKind.NEURAL_SBD.value == "neural_sbd"
    assert BoundaryKind.SEMANTIC.value == "semantic", "P13 slot reserved"


@pytest.mark.fixture_only
def test_no_safety_verdict_surface_in_scene_detect():
    import inspect

    import scene_detect
    src_txt = inspect.getsource(scene_detect)
    assert "verdict" not in src_txt.lower().replace(
        "archive safety verdict", ""
    ) or "safety_verdict" not in src_txt, \
        "scene detection must not expose or touch any archive safety verdict"
    for prov in (FixedIntervalProvider(1.0), ContentDiffProvider()):
        assert not hasattr(prov, "safety_verdict") and \
            not hasattr(prov, "archive_verdict")
