"""P11.1-D — Editor Proxy Validation: golden tests (source-to-proxy frame
mapping + audio/color/timecode preservation verdicts).

Method: fixtures are REAL synthetic media (ffmpeg `testsrc2`), proxies come
from the real `generate_proxy` pipeline (or a deliberately-legacy encode for
the audio-loss case), and every verdict is read back with REAL ffprobe
(golden). "Metadata field was copied" is NOT acceptance: a retimed / lost /
VFR timeline must surface as EDITOR_DEGRADED with an explicit reason, and
unverified camera families (BRAW/Sony/...) stay UNVERIFIED on this host.

Markers: `@behavior_tested` — synthetic media only; no real camera footage,
no v4, no cloud, no GPU.
"""

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest
from editor_validation import (
    STATUS_DEGRADED,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    validate_editor_proxy,
)
from media_probe import probe
from proxy_generator import generate_proxy

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _ff(*args) -> None:
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True, timeout=60, check=False,
    )
    assert p.returncode == 0, f"ffmpeg failed: {p.stderr[:500]!r}"


def _mk_source(tmp: Path, *, rate="24", dur="0.5", extra=(),
               itsoffset: str | None = None, audio_tracks: int = 0,
               name="src.mp4") -> Path:
    p = tmp / name
    v = f"testsrc2=d={dur}:r={rate}:s=192x108"
    # inputs first (lavfi video + optional lavfi sine tracks), then output
    # options — a `-pix_fmt` placed between inputs would be parsed as an
    # option of the NEXT input (ffmpeg rejects it on the sine source).
    args: list[str] = ["-f", "lavfi", "-i", v]
    for i in range(audio_tracks):
        args += ["-f", "lavfi", "-i", f"sine=f={440 + i * 200}:d={dur}"]
    args += ["-map", "0:v"]
    for i in range(audio_tracks):
        args += ["-map", f"{1 + i}:a"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_tracks:
        args += ["-c:a", "aac"]
    args += [*extra, str(p)]
    _ff(*args)
    return p


def _probe(path: Path, *, start_time_override: float | None = None,
           hdr_override: str | None = None):
    p = probe(path, full_fps=True)
    import dataclasses as _dc

    mv = p.video[0]
    if start_time_override is not None:
        # a TC-reel-style source whose start timebase is offset: probe the
        # fixture, then model the reel's 30-second start in the evidence
        # (deterministic — no dependence on muxer start-time behavior).
        mv = _dc.replace(mv, start_time=start_time_override)
    if hdr_override is not None:
        # this host's muxers do not round-trip HDR colr tags into a
        # small h264 fixture; model the source's HDR content on the P10
        # evidence (deterministic — the verdict under test is the
        # downgrade behavior, not tag persistence in mp4).
        mv = _dc.replace(mv, hdr=hdr_override)
    return _dc.replace(p, video=[mv])


def _make_proxy(src: Path, out: Path) -> Path:
    res = generate_proxy(src, "editor", out, test_mode=True)
    return Path(res.path)


@pytest.mark.behavior_tested
def test_d1_verified_cfr_baseline_carries_mapping_and_tc(tmp_path):
    src = _mk_source(tmp_path, rate="24")
    sp = _probe(src)
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(
        src, prx, source_probe=sp, asset_id="ASSET-1", reel="reel-001",
    )
    assert v.status == STATUS_VERIFIED, f"baseline must verify: {v.reasons}"
    m = v.frame_mapping
    assert m.fps_exact_match is True
    assert m.mapping_rule == "index-identity"
    assert m.confidence == "verified"
    assert m.source_frame_count == 12 and m.proxy_frame_count == 12
    assert v.audio.source_streams == 0 and v.audio.proxy_streams == 0
    # timecode: source is 24fps (non-drop by fps-family), proxy has no TC
    # track — mapping is PTS-anchored and the absence is REPORTED, not
    # guessed:
    assert v.timecode.source_timecode == "non-drop"
    assert v.timecode.proxy_timecode_present is False
    assert v.timecode.mapping_anchor == "pts"
    # attribution + evidence round-trip:
    assert v.asset_id == "ASSET-1" and v.reel == "reel-001"
    ev = json.loads(v.to_evidence_json())
    assert ev["status"] == "EDITOR_VERIFIED"
    assert ev["frame_mapping"]["mapping_rule"] == "index-identity"


@pytest.mark.behavior_tested
def test_d2_non_integer_2997_fps_is_exact_not_float(tmp_path):
    src = _mk_source(tmp_path, rate="30000/1001")
    sp = _probe(src)
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(src, prx, source_probe=sp)
    # 30000/1001 != 30 in float-land; the verdict must be rational-exact:
    assert v.status == STATUS_VERIFIED, f"29.97 CFR must verify: {v.reasons}"
    assert v.frame_mapping.fps_exact_match is True
    assert v.frame_mapping.mapping_rule == "index-identity"


@pytest.mark.behavior_tested
def test_d3_retimed_fps_is_degraded_not_verifying_metadata(tmp_path):
    src = _mk_source(tmp_path, rate="30")
    sp = _probe(src)
    # a proxy RE-TIMED to 24 (fps_cap) — both sides carry fps metadata,
    # but the timeline changed: metadata presence must NOT be acceptance.
    res = generate_proxy(src, "editor", tmp_path / "out",
                         test_mode=True, fps_cap=24)
    prx = Path(res.path)
    v = validate_editor_proxy(src, prx, source_probe=sp)
    assert v.status == STATUS_DEGRADED
    assert any("fps" in r for r in v.reasons)
    assert v.frame_mapping.fps_exact_match is False
    assert v.frame_mapping.mapping_rule != "index-identity"


@pytest.mark.behavior_tested
def test_d4_vfr_source_is_degraded_with_pts_mapping(tmp_path):
    # real VFR: two different rates concatenated (24 then 48)
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=d=0.25:r=24:s=192x108",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", str(a))
    _ff("-f", "lavfi", "-i", "testsrc2=d=0.25:r=48:s=192x108",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", str(b))
    src = tmp_path / "vfr.mp4"
    _ff("-i", str(a), "-i", str(b),
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
        "-fps_mode", "vfr", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(src))
    sp = _probe(src)
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(src, prx, source_probe=sp)
    assert sp.vfr_status == "vfr-likely", "fixture must be VFR for the test"
    assert v.status == STATUS_DEGRADED
    assert any("vfr" in r for r in v.reasons)
    assert v.frame_mapping.mapping_rule != "index-identity"


@pytest.mark.behavior_tested
def test_d5_start_pts_offset_is_absorbed_not_error(tmp_path):
    # a TC-reel-style source with a 30-second start time: the proxy
    # re-times to 0 — the offset must be RECORDED and absorbed, not a
    # blocker. (The reel start is modeled on the probe evidence — no
    # dependence on muxer -itsoffset behavior.)
    src = _mk_source(tmp_path, rate="24")
    sp = _probe(src, start_time_override=30.0)
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(src, prx, source_probe=sp)
    m = v.frame_mapping
    assert m.start_pts_offset_s is not None
    assert abs(m.start_pts_offset_s - 30.0) < 0.1, \
        "the source's 30s reel start must be recorded"
    assert v.status in (STATUS_VERIFIED, STATUS_DEGRADED)
    # a large recorded offset is a NOTE, and the verdict must SAY so:
    assert any("offset" in r for r in v.reasons) or \
        "offset" in v.timecode.note, \
        "a >half-second start offset must be surfaced to the editor"


@pytest.mark.behavior_tested
def test_d6_multi_audio_source_with_single_audio_proxy_degraded(tmp_path):
    # source has 2 audio tracks; the legacy-style proxy carries only 1:
    # the loss is BLOCKING, reported with both sides' stream facts.
    src = _mk_source(tmp_path, rate="24", dur="0.25", audio_tracks=2)
    sp = _probe(src)
    assert len(sp.audio) == 2
    prx = tmp_path / "legacy.mp4"
    _ff("-i", str(src), "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "libx264", "-c:a", "aac", str(prx))
    v = validate_editor_proxy(src, prx, source_probe=sp)
    assert v.audio.source_streams == 2 and v.audio.proxy_streams == 1
    assert v.audio.streams_lost is True
    assert v.status == STATUS_DEGRADED
    assert any("audio" in r for r in v.reasons)


@pytest.mark.behavior_tested
def test_d7_hdr_source_into_sdr_proxy_is_explicit_downgrade(tmp_path):
    # HDR *content* on the source (P10 evidence). The small h264 fixture's
    # mp4 muxer does not persist HDR colr tags on this host, so the HDR
    # source is modeled on the probe evidence (deterministic) — the D7
    # verdict under test is the downgrade behavior, not tag persistence.
    src = _mk_source(tmp_path, rate="24", dur="0.25")
    sp = _probe(src, hdr_override="hdr-sdr")
    assert sp.video[0].hdr == "hdr-sdr", "fixture must be HDR-tagged"
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(src, prx, source_probe=sp)
    assert v.color.source_hdr == "hdr-sdr"
    assert v.color.hdr_lost is True
    assert v.status == STATUS_DEGRADED
    assert any("hdr" in r for r in v.reasons)


@pytest.mark.behavior_tested
def test_d8_rotation_metadata_loss_is_degraded(tmp_path):
    src = _mk_source(tmp_path, rate="24", dur="0.25")
    sp = _probe(src)
    # source evidence says 90-degree rotation; the proxy carries none:
    sp90 = dataclasses.replace(
        sp,
        video=[dataclasses.replace(sp.video[0], rotation=90.0)],
    )
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(src, prx, source_probe=sp90)
    assert v.color.source_rotation == 90.0
    assert v.color.proxy_rotation is None
    assert v.color.rotation_lost is True
    assert v.status == STATUS_DEGRADED
    assert any("rotation" in r for r in v.reasons)
    # positive control: no rotation on the source side => no loss:
    v0 = validate_editor_proxy(src, prx, source_probe=sp)
    assert v0.color.rotation_lost is False
    assert "rotation" not in " ".join(v0.reasons)


@pytest.mark.behavior_tested
def test_d9_unverified_camera_family_is_unverified_even_when_mapping_holds(tmp_path):
    src = _mk_source(tmp_path, rate="24")
    sp = _probe(src)
    prx = _make_proxy(src, tmp_path / "out")
    # stand-in for a BRAW/Sony source (NO real sample exists on this host):
    brawish = dataclasses.replace(
        sp, camera_family="sony-braw", family_verified=False,
    )
    v = validate_editor_proxy(src, prx, source_probe=brawish)
    assert v.status == STATUS_UNVERIFIED, \
        "unverified camera families never become VERIFIED"
    assert any("sony-braw" in r or "unverified" in r for r in v.reasons)
    # the mapping evidence is STILL computed (a reviewer can audit it):
    assert v.frame_mapping.fps_exact_match is True
    assert v.frame_mapping.mapping_rule == "index-identity"


@pytest.mark.behavior_tested
def test_d10_bounded_frame_enumeration_truncation_is_degraded(tmp_path):
    src = _mk_source(tmp_path, rate="24")  # 12 frames
    sp = _probe(src)
    prx = _make_proxy(src, tmp_path / "out")
    v = validate_editor_proxy(src, prx, source_probe=sp, max_frames=3)
    assert v.status == STATUS_DEGRADED
    assert any("truncat" in r for r in v.reasons), \
        "capped enumeration must be surfaced, not silently trusted"


@pytest.mark.behavior_tested
def test_d11_undecodable_proxy_is_unverified_fail_closed(tmp_path):
    src = _mk_source(tmp_path, rate="24")
    sp = _probe(src)
    bad = tmp_path / "out"
    bad.mkdir()
    corrupt = bad / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x01not-a-media-file")
    v = validate_editor_proxy(src, corrupt, source_probe=sp)
    assert v.status == STATUS_UNVERIFIED
    assert any("undecodable" in r or "probe" in r for r in v.reasons)
