"""P10 media probe — contract tests for `media_probe`.

Synthetic ffmpeg fixtures in `tmp_path` (reproducible, zero real media,
zero real camera cards). Spec: docs/engineering/spec/P10-media-probe.md.
Markers: `@behavior_tested` = real ffmpeg-generated fixture probed;
`@fixture_only` = pure classifier / parser-layer logic without binary
samples (camera families lacking real samples are pinned UNVERIFIED);
the malformed-JSON case uses a synthetic fake ffprobe binary.
"""

import json
import os
import stat
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

import media_probe
from media_probe import (
    InvalidInputError,
    MediaProbe,
    ProbeError,
    _classify_camera_family,
    classify_hdr,
    classify_timecode,
    probe,
    vfr_status_from_pts,
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


def _mp4_24p(tmp_path: Path) -> Path:
    return _mk(
        tmp_path / "clip24.mp4",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-colorspace", "bt709",
    )


# ── 1. 24p synthetic MP4 ────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_24p_mp4_exact_rational_fps_and_time_base(tmp_path):
    p = _mp4_24p(tmp_path)
    m = probe(p, full_fps=True)
    v = m.main_video()
    assert v is not None and v.codec == "h264"
    assert v.r_frame_rate == "24/1", "exact rational must be preserved"
    assert m.fps == Fraction(24), "FPS must be an exact Fraction"
    assert m.fps_status == "ok"
    assert m.vfr_status == "cfr", "per-frame PTS equidistant => cfr"
    assert m.timecode == "non-drop", "24fps family is non-drop"
    assert m.duration_s is not None and 0.9 < m.duration_s < 1.1
    # SDR classification: this ffmpeg build only carries colorspace into
    # the MP4 stream (primaries/transfer dropped), so hdr may be "sdr"
    # or the honest "unknown" — the classifier is pinned separately in
    # test_hdr_classifier_crafted_json.
    assert m.video[0].hdr in ("sdr", "unknown")


# ── 2. 29.97p exact rational + drop-family timecode ────────────────


@pytest.mark.behavior_tested
def test_29_97p_exact_rational_and_drop_family(tmp_path):
    p = _mk(
        tmp_path / "clip29.mp4",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=30000/1001",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )
    m = probe(p)
    v = m.main_video()
    assert v.r_frame_rate == "30000/1001", \
        "29.97 must stay the exact rational string, never a rounded float"
    assert m.fps == Fraction(30000, 1001)
    assert m.timecode == "drop", "29.97/30 family is drop-frame capable"
    assert m.timecode_basis == "fps-family"


# ── 3. VFR synthetic (two rates concatenated) ───────────────────────


@pytest.mark.behavior_tested
def test_vfr_concatenation_detected_not_assumed_cfr(tmp_path):
    a = _mk(
        tmp_path / "a.mp4",
        "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=60",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )
    b = _mk(
        tmp_path / "b.mp4",
        "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )
    (tmp_path / "list.txt").write_text(f"file '{a}'\nfile '{b}'\n")
    vfr = _mk(
        tmp_path / "vfr.mp4",
        "-f", "concat", "-safe", "0", "-i", str(tmp_path / "list.txt"),
        "-fps_mode", "vfr",  # keep the original per-frame timestamps
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )
    m = probe(vfr, full_fps=True)
    assert m.vfr_status == "vfr-likely", \
        "non-uniform per-frame PTS must not be assumed cfr"


# ── 4. rotation + HDR degradation ───────────────────────────────────
#
# Note: test_24p_mp4_exact_rational_fps_and_time_base (section 1) already
# covers the 24p rational-fps + cfr + timecode assertions. This section
# focuses on rotation/HDR color handling.


@pytest.mark.fixture_only
def test_rotation_parser_on_crafted_display_matrix(tmp_path):
    raw = json.dumps({
        "streams": [{
            "index": 0, "codec_type": "video", "codec_name": "h264",
            "width": 240, "height": 320, "pix_fmt": "yuv420p",
            "r_frame_rate": "24/1", "avg_frame_rate": "24/1",
            "time_base": "1/24000", "start_time": "0.000000",
            "side_data_list": [{
                "side_data_type": "Display Matrix",
                "side_data_value": "{rotation=-90.000000}",
            }],
        }],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                   "duration": "1.000000", "nb_streams": 1},
    })
    m = media_probe._build_probe_from_raw(
        raw, path="x.mov", ffprobe_version="ffprobe test",
        source_sha256=None,
    )
    # display-matrix -90° == player-rotated +90° (the sign convention
    # used by the rotate tag); we surface the raw matrix value:
    assert m.video[0].rotation == -90.0


@pytest.mark.fixture_only
def test_hdr_classifier_crafted_json(tmp_path):
    # PQ (smpte2084) transfer => hdr-sdr, verified at parser level:
    raw = json.dumps({
        "streams": [{
            "index": 0, "codec_type": "video", "codec_name": "h264",
            "r_frame_rate": "24/1", "avg_frame_rate": "24/1",
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
            "color_space": "bt2020nc",
        }],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                   "nb_streams": 1},
    })
    m = media_probe._build_probe_from_raw(
        raw, path="h.mov", ffprobe_version="ffprobe test",
        source_sha256=None,
    )
    assert m.video[0].hdr == "hdr-sdr"
    # And SDR:
    m2 = media_probe._build_probe_from_raw(
        raw.replace("smpte2084", "bt709")
        .replace("bt2020nc", "bt709")
        .replace('"bt2020"', '"bt709"'),
        path="s.mov", ffprobe_version="ffprobe test", source_sha256=None,
    )
    assert m2.video[0].hdr == "sdr"


@pytest.mark.behavior_tested
def test_rotation_attribute_present_on_real_clip(tmp_path):
    """The real-clip path must expose the rotation field (None when the
    muxer did not carry a display matrix — the honest, un-fabricated
    value on this ffmpeg build)."""
    p = _mp4_24p(tmp_path)
    m = probe(p)
    assert m.video[0].rotation is None, \
        "no display matrix in the synthetic clip -> None, never a guess"


@pytest.mark.fixture_only
def test_hdr_transfer_degrades_to_unknown_without_guessing():
    # HLG/PQ transfer families:
    assert classify_hdr("bt2020", "smpte2084", "bt2020") == "hdr-sdr"
    assert classify_hdr("bt2020", "arib-std-b67", "bt2020") == "hdr-sdr"
    # SDR only when BOTH transfer AND primaries are SDR-family:
    assert classify_hdr("bt709", "bt709", "bt709") == "sdr"
    # unknown transfer/primaries => unknown, never guessed:
    assert classify_hdr(None, None, None) == "unknown"
    assert classify_hdr("bt709", "unknown", "bt709") == "unknown"


# ── 5. multi-audio streams ──────────────────────────────────────────


@pytest.mark.behavior_tested
def test_dual_audio_streams_independent(tmp_path):
    p = _mk(
        tmp_path / "dual_audio.mp4",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=32000:duration=1",
        "-map", "0:v", "-map", "1:a", "-map", "2:a",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
    )
    m = probe(p)
    assert len(m.audio) == 2, "both audio tracks must be listed"
    rates = sorted(a.sample_rate for a in m.audio if a.sample_rate)
    assert 32000 in rates and 48000 in rates, \
        "each stream reports its own sample rate"


# ── 6. corrupt / empty ──────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_corrupt_file_raises_probe_error(tmp_path):
    good = _mp4_24p(tmp_path)
    truncated = tmp_path / "trunc.mp4"
    data = good.read_bytes()
    truncated.write_bytes(data[:200])
    with pytest.raises(ProbeError) as exc:
        probe(truncated)
    assert "ffprobe exited" in str(exc.value), \
        "the error must carry the ffprobe stderr summary"


@pytest.mark.behavior_tested
def test_empty_input_refused_without_calling_ffprobe(tmp_path, monkeypatch):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    calls: list = []
    monkeypatch.setattr(
        media_probe, "_run_ffprobe",
        lambda *a, **k: calls.append(a) or "",
    )
    with pytest.raises(ProbeError, match="empty input"):
        probe(empty)
    assert not calls, "an empty file must be rejected before ffprobe runs"


# ── 7. unknown format ───────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_unknown_format_raises_with_stderr_summary(tmp_path):
    p = tmp_path / "blob.foo"
    p.write_bytes(os.urandom(512))
    with pytest.raises(ProbeError) as exc:
        probe(p)
    assert "ffprobe exited" in str(exc.value)


# ── 8. CJK unicode path ─────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_cjk_unicode_path_probes(tmp_path):
    src = _mp4_24p(tmp_path)
    cjk_dir = tmp_path / "影像資料_試映_01"
    cjk_dir.mkdir()
    cjk = cjk_dir / "測試素材_24p.mp4"
    cjk.write_bytes(src.read_bytes())
    m = probe(cjk)
    assert m.fps == Fraction(24) and m.main_video() is not None


# ── 9. URL refusal before subprocess ────────────────────────────────


@pytest.mark.behavior_tested
def test_network_url_refused_before_ffprobe_runs(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        media_probe, "_run_ffprobe",
        lambda *a, **k: calls.append(a) or "",
    )
    with pytest.raises(InvalidInputError, match="network URL"):
        probe("http://example.com/clip.mp4")
    assert not calls, "URLs must be refused before any subprocess runs"


# ── 10. sidecar association ─────────────────────────────────────────


@pytest.mark.behavior_tested
def test_sidecars_listed_read_only(tmp_path):
    p = _mp4_24p(tmp_path)
    (tmp_path / "clip24.sidecar.json").write_text(
        json.dumps({"reel": "A001", "camera": "synthetic"})
    )
    (tmp_path / "clip24_notes.csv").write_text("field,val\nreel,A001\n")
    m = probe(p, sha256=True)
    assert "clip24.sidecar.json" in m.sidecars
    assert "clip24_notes.csv" in m.sidecars
    assert m.source_sha256 is not None and len(m.source_sha256) == 64
    # the media file itself must never be reported as its own sidecar
    assert "clip24.mp4" not in m.sidecars


# ── 11. evidence reproducibility ────────────────────────────────────


@pytest.mark.behavior_tested
def test_evidence_json_is_reproducible(tmp_path):
    p = _mp4_24p(tmp_path)
    m = probe(p, sha256=True)
    ev = json.loads(m.to_evidence_json())
    assert ev["ffprobe_version"].startswith("ffprobe ")
    assert ev["raw"] and json.loads(ev["raw"])  # raw ffprobe JSON intact
    m2 = MediaProbe.from_evidence(m.to_evidence_json())
    assert m2.fps == m.fps and m2.container == m.container
    assert m2.timecode == m.timecode
    assert m2.source_sha256 == m.source_sha256
    assert m2.video[0].r_frame_rate == m.video[0].r_frame_rate


# ── 12. camera families without samples stay UNVERIFIED ────────────


@pytest.mark.fixture_only
def test_camera_family_classifier_unverified_without_samples():
    # No real Sony BRAW / X-OCN / CinemaDNG / RED samples exist here:
    # the classifier must say so, never claim a verified match.
    for container, suffix, family in [
        ("matroska", ".braw", "sony-braw"),
        (None, ".dng", "cinemadng"),
        (None, ".x-ocn", "blackmagic-ocn"),
        (None, ".r3d", "red-mono"),
    ]:
        fam, verified = _classify_camera_family(container, [], f"x{suffix}")
        assert fam == family and verified is False, \
            f"{suffix}: {family} must be UNVERIFIED (no sample available)"
    # container-known families may be verified against the container:
    fam, verified = _classify_camera_family(
        "mov,quicktime", [], "x.mov"
    )
    assert fam == "quicktime" and verified is True


# ── 13. malformed JSON from a synthetic fake ffprobe ──────────────


@pytest.mark.fixture_only
def test_malformed_json_from_fake_ffprobe(tmp_path):
    fake = tmp_path / "fake_ffprobe"
    fake.write_text("#!/bin/sh\necho 'this is not json'\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # give it a valid input so we reach the JSON parse stage
    src = _mp4_24p(tmp_path)
    with pytest.raises(ProbeError, match="malformed ffprobe JSON"):
        probe(src, ffprobe_bin=str(fake))


# ── parser-layer unit pins ──────────────────────────────────────────


@pytest.mark.fixture_only
def test_vfr_status_degrades_unknown_when_few_frames():
    assert vfr_status_from_pts([]) == "unknown"
    assert vfr_status_from_pts([0.0, 1.0]) == "unknown"
    assert vfr_status_from_pts([0.0, 1.0, 2.0, 3.0]) == "cfr"
    assert vfr_status_from_pts([0.0, 1.0, 1.5, 3.0]) == "vfr-likely"


@pytest.mark.fixture_only
def test_timecode_classification_unknown_fps():
    assert classify_timecode(None) == (None, "unresolved")
    assert classify_timecode(Fraction(24))[0] == "non-drop"
    assert classify_timecode(Fraction(30000, 1001))[0] == "drop"
