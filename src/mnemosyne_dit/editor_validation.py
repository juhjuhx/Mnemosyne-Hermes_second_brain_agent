"""editor_validation.py — DIT 2.2 P11.1-D: editor proxy validation.

The CPU Proxy MVP must give editors TRUSTWORTHY source-to-proxy
connection evidence. "The metadata field was copied" is NOT evidence
that "the timeline is actually consistent": this module re-probes the
PUBLISHED proxy with real ffprobe (golden readback — never an encoder
self-report) and re-derives a source-to-proxy FRAME MAPPING, then
verdicts it:

    verdict = validate_editor_proxy(source, proxy_path, *, source_probe=...)

Status model:
- `EDITOR_VERIFIED`   : fps exact, mapping resolvable, no content risk.
- `EDITOR_DEGRADED`   : content/timeline risk that an editor must know
    (VFR, retimed fps, lost audio streams, HDR content downgraded to
    SDR proxy, lost rotation, unresolvable mapping) — each with an
    EXPLICIT reason. An explicit downgrade is reported, never silent.
- `UNVERIFIED`        : the source camera family has no tested real
    media sample (BRAW / Sony / RED / OCN / unknown) — we cannot
    accept the timeline claim at all, no matter what the proxy readback
    shows — or the proxy itself is undecodable (fail-closed).

Decision rules (pinned by the golden tests):
- fps is compared as EXACT rationals (Fraction), so 30000/1001
  (29.97) is distinct from 30 — never float-rounded.
- A mapping is `index-identity` only when both sides are CFR, fps
  matches exactly, and frame counts are known and equal; otherwise it is
  `pts-anchored` (time-domain, start-PTS offset recorded); with an
  unknown source fps it is `unresolvable`.
- B-frames: mapping is always in DISPLAY (PTS) order; decode order is
  never used; their presence is noted, not penalized.
- Metadata-only notes (color tags absent on an SDR source) are
  reported, not blockers. Content/geometry risks are blockers.
- A start-PTS offset (non-zero TC reels) is recorded and absorbed by
  the mapping — it is not an error; a large one is surfaced in a note.
- The verdict carries `asset_id` + `reel` so the editor evidence is
  attributable; `to_evidence_json` round-trips the whole mapping.

Safety: read-only (ffprobe), refuses URLs (delegated to media_probe),
bounded frame enumeration (`max_frames` — truncation is surfaced, never
silently trusted), no v4 / cloud / GPU imports.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

from media_probe import (
    ProbeError,
    classify_hdr,
    run_ffprobe_json,
    vfr_status_from_pts,
)

STATUS_VERIFIED = "EDITOR_VERIFIED"
STATUS_DEGRADED = "EDITOR_DEGRADED"
STATUS_UNVERIFIED = "UNVERIFIED"

# a start-PTS offset beyond this is "large enough that an editor should
# be told" (still absorbed, still not an error).
_LARGE_OFFSET_S = 0.5


@dataclass(frozen=True)
class FrameMapping:
    source_fps: str | None      # Fraction rendering, or None
    proxy_fps: str | None
    fps_exact_match: bool
    source_frame_count: int | None
    proxy_frame_count: int | None
    source_first_pts: float | None
    source_last_pts: float | None
    proxy_first_pts: float | None
    proxy_last_pts: float | None
    vfr_source: str             # cfr | vfr-likely | unknown
    vfr_proxy: str
    mapping_rule: str          # index-identity | pts-anchored | unresolvable
    start_pts_offset_s: float | None
    source_start_time: float | None   # container-level start (reel timecode)
    b_frames_note: str
    confidence: str            # verified | degraded | unresolvable

    def source_index_to_proxy_time(self, i: int) -> float | None:
        """Reconstructable mapping: the PROXY display-time of the
        source's i-th frame (0-based display order). None when
        unresolvable. index-identity uses the proxy fps; pts-anchored
        uses the source fps (the proxy is a 1:1 time copy of content);
        the start offset is already proxy-domain, so it is absorbed, not
        re-added."""
        if self.mapping_rule == "unresolvable":
            return None
        fps_raw = (
            self.proxy_fps if self.mapping_rule == "index-identity"
            else self.source_fps
        )
        if not fps_raw:
            return None
        try:
            fps = Fraction(fps_raw)
        except (ValueError, ZeroDivisionError):
            return None
        base = self.proxy_first_pts if self.proxy_first_pts is not None else 0.0
        return base + i / fps


@dataclass(frozen=True)
class AudioReport:
    source_streams: int
    proxy_streams: int
    source_sample_rates: tuple[int | None, ...]
    proxy_sample_rates: tuple[int | None, ...]
    source_channel_layouts: tuple[str | None, ...]
    proxy_channel_layouts: tuple[str | None, ...]
    streams_lost: bool
    note: str = ""


@dataclass(frozen=True)
class ColorReport:
    source_hdr: str            # sdr | hdr-sdr | unknown
    proxy_hdr: str
    source_rotation: float | None
    proxy_rotation: float | None
    hdr_lost: bool            # HDR content into an SDR proxy (blocker)
    rotation_lost: bool       # orientation metadata not carried (blocker)
    note: str = ""


@dataclass(frozen=True)
class TimecodeReport:
    source_timecode: str | None       # drop | non-drop | None
    source_timecode_basis: str
    proxy_timecode_present: bool
    mapping_anchor: str               # pts | timecode
    note: str = ""


@dataclass(frozen=True)
class EditorVerdict:
    status: str
    reasons: tuple[str, ...]
    frame_mapping: FrameMapping
    audio: AudioReport
    color: ColorReport
    timecode: TimecodeReport
    camera_family: str
    family_verified: bool
    asset_id: str | None
    reel: str | None

    def to_evidence_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "reasons": list(self.reasons),
                "frame_mapping": asdict(self.frame_mapping),
                "audio": asdict(self.audio),
                "color": asdict(self.color),
                "timecode": asdict(self.timecode),
                "camera_family": self.camera_family,
                "family_verified": self.family_verified,
                "asset_id": self.asset_id,
                "reel": self.reel,
            },
            ensure_ascii=False,
            default=str,
        )


# ── internal readback helpers (real ffprobe, never encoder claims) ──


def _fps_fraction(raw: str | None) -> Fraction | None:
    if not raw:
        return None
    try:
        f = Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return None
    return f if f > 0 else None


def _first_video(streams: list[dict]) -> dict | None:
    for s in streams:
        if s.get("codec_type") == "video":
            return s
    return None


def _stream_fps(streams: list[dict]) -> Fraction | None:
    v = _first_video(streams)
    if not v:
        return None
    return _fps_fraction(v.get("avg_frame_rate") or v.get("r_frame_rate"))


def _stream_hdr(streams: list[dict]) -> str:
    v = _first_video(streams)
    if not v:
        return "unknown"
    return classify_hdr(
        v.get("color_primaries"), v.get("color_transfer"), v.get("color_space")
    )


def _stream_rotation(streams: list[dict]) -> float | None:
    """Orientation from the proxy video stream's Display-Matrix side data
    or rotation tags. None when ffprobe did not expose it (which is the
    normal case for our proxies — so a source rotation that the proxy
    lacks is a genuine loss)."""
    v = _first_video(streams)
    if not v:
        return None
    import re as _re

    for item in v.get("side_data_list") or []:
        kind = str(item.get("side_data_type", ""))
        if "Display" in kind or "rotation" in kind.lower():
            val = item.get("side_data_value")
            if isinstance(val, str):
                m = _re.search(r"rotation\s*=\s*([-0-9.]+)", val)
                if m:
                    try:
                        return float(m.group(1))
                    except ValueError:
                        pass
    tags = v.get("tags") or {}
    if isinstance(tags, dict):
        for k in ("rotation", "rotate", "Rotation"):
            if k in tags:
                try:
                    return float(str(tags[k]).replace("deg", ""))
                except ValueError:
                    return None
    return None


def _audio_of(streams: list[dict]) -> tuple[int, list[int | None], list[str | None]]:
    aud = [s for s in streams if s.get("codec_type") == "audio"]
    srs: list[int | None] = []
    for a in aud:
        try:
            srs.append(int(a.get("sample_rate")))
        except (TypeError, ValueError):
            srs.append(None)
    return len(aud), srs, [a.get("channel_layout") for a in aud]


def _frame_stats(
    path: Path, *, ffprobe_bin: str, timeout_s: float, max_frames: int
) -> tuple[int | None, float | None, float | None, str, bool]:
    """Bounded golden frame readback of `path` (the PROXY side of the
    verdict — never trusted from the encoder's word). Returns
    (frame_count, first_pts, last_pts, vfr_status, truncated).

    `frame_count` is authoritative ONLY when the enumeration was not
    capped; a capped run returns `None` + `truncated=True` and the
    caller must surface it, never trust a partial count. PTS order is
    DISPLAY order (ffprobe reports presentation order), which is exactly
    what a source-to-proxy mapping needs — B-frame decode order is
    irrelevant to it."""
    args = [
        ffprobe_bin, "-hide_banner", "-loglevel", "error",
        "-select_streams", "v:0", "-show_entries", "frame=pts_time",
        "-of", "json", str(path),
    ]
    try:
        proc = subprocess.run(
            args, input=None, capture_output=True, timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ProbeError(f"ffprobe timed out after {timeout_s}s") from e
    if proc.returncode != 0:
        err = (proc.stderr or b"")[:2048].decode("utf-8", "replace")
        raise ProbeError(f"ffprobe exited {proc.returncode}: {err.strip()[:300]}")
    try:
        payload = json.loads((proc.stdout or b"").decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise ProbeError(f"malformed ffprobe JSON: {e}") from e

    all_pts: list[float] = []
    for fr in payload.get("frames", []):
        try:
            all_pts.append(float(fr.get("pts_time")))
        except (TypeError, ValueError):
            continue
    truncated = len(all_pts) > max_frames
    pts = all_pts[:max_frames] if truncated else all_pts
    clean = sorted(p for p in pts if p is not None and p >= 0)
    return (
        (len(all_pts) if not truncated else None),
        clean[0] if clean else None,
        clean[-1] if clean else None,
        vfr_status_from_pts(clean),
        truncated,
    )


def _empty_mapping() -> FrameMapping:
    return FrameMapping(
        source_fps=None, proxy_fps=None, fps_exact_match=False,
        source_frame_count=None, proxy_frame_count=None,
        source_first_pts=None, source_last_pts=None,
        proxy_first_pts=None, proxy_last_pts=None,
        vfr_source="unknown", vfr_proxy="unknown",
        mapping_rule="unresolvable", start_pts_offset_s=None,
        source_start_time=None,
        b_frames_note="", confidence="unresolvable",
    )


def _empty_audio() -> AudioReport:
    return AudioReport(0, 0, (), (), (), (), False)


def _empty_color() -> ColorReport:
    return ColorReport("unknown", "unknown", None, None, False, False)


def _empty_timecode() -> TimecodeReport:
    return TimecodeReport(None, "unresolved", False, "pts")


# ── public API ──────────────────────────────────────────────────────


def validate_editor_proxy(
    source,
    proxy_path,
    *,
    source_probe=None,
    asset_id: str | None = None,
    reel: str | None = None,
    ffprobe_bin: str = "ffprobe",
    timeout_s: float = 60.0,
    max_frames: int = 5000,
) -> EditorVerdict:
    """Validate a published editor proxy against its source (golden
    ffprobe readback; read-only; no v4/cloud/GPU).

    The source side is `source_probe` (a P10 `MediaProbe` — the
    caller's authoritative evidence) or, when omitted, a fresh
    read-only probe of `source`. The PROXY side is always re-read with
    real ffprobe: stream facts + bounded per-frame PTS + audio +
    color/rotation — an encoder's self-report is never trusted."""
    src = Path(source)
    prx = Path(proxy_path)

    def _undecodable(reason: str) -> EditorVerdict:
        return EditorVerdict(
            status=STATUS_UNVERIFIED,
            reasons=(reason,),
            frame_mapping=_empty_mapping(),
            audio=_empty_audio(),
            color=_empty_color(),
            timecode=_empty_timecode(),
            camera_family=getattr(source_probe, "camera_family", "unknown"),
            family_verified=getattr(source_probe, "family_verified", False),
            asset_id=asset_id,
            reel=reel,
        )

    # golden readback of the PROXY (never an encoder claim):
    try:
        proxy_raw = run_ffprobe_json(
            prx, ffprobe_bin=ffprobe_bin, timeout_s=timeout_s
        )
    except ProbeError as e:
        return _undecodable(
            f"proxy undecodable by ffprobe (fail-closed): {e}"
        )
    proxy_streams = proxy_raw.get("streams", []) or []

    # source side: the caller's evidence, or a fresh read-only probe:
    if source_probe is None:
        from media_probe import probe as _probe

        try:
            source_probe = _probe(
                src, full_fps=True, ffprobe_bin=ffprobe_bin,
                timeout_s=timeout_s,
            )
        except ProbeError as e:
            return _undecodable(
                f"source undecodable by ffprobe (fail-closed): {e}"
            )
    s_fps = _fps_fraction(
        (source_probe.video[0].avg_frame_rate
         or source_probe.video[0].r_frame_rate)
        if source_probe.video else None
    )
    p_fps = _stream_fps(proxy_streams)
    s_vfr = getattr(source_probe, "vfr_status", "unknown") or "unknown"

    s_count = s_first = s_last = None
    p_count = p_first = p_last = None
    s_trunc = p_trunc = False
    try:
        s_count, s_first, s_last, s_vfr_read, s_trunc = _frame_stats(
            src, ffprobe_bin=ffprobe_bin, timeout_s=timeout_s,
            max_frames=max_frames,
        )
        if s_vfr_read != "unknown":
            s_vfr = s_vfr_read
    except ProbeError:
        s_vfr = "unknown"
    try:
        p_count, p_first, p_last, p_vfr, p_trunc = _frame_stats(
            prx, ffprobe_bin=ffprobe_bin, timeout_s=timeout_s,
            max_frames=max_frames,
        )
    except ProbeError:
        p_vfr = "unknown"

    truncated = s_trunc or p_trunc
    fps_exact = s_fps is not None and p_fps is not None and s_fps == p_fps
    # start-PTS offset in the CONTAINER sense (reel start / TC offset):
    # source start_time (from the P10 evidence) vs the proxy's start.
    # This is the number an editor must know when mapping a reel; the
    # first-frame pts delta stays informational in first/last pts fields.
    s_start: float | None = None
    _raw_s_start = (
        source_probe.video[0].start_time if source_probe.video else None
    )
    if _raw_s_start is not None:
        try:
            s_start = float(_raw_s_start)
        except (TypeError, ValueError):
            s_start = None
    p_start: float | None = None
    _pv = _first_video(proxy_streams)
    if _pv:
        try:
            p_start = float(_pv.get("start_time") or 0.0)
        except (TypeError, ValueError):
            p_start = 0.0
    if p_start is None:
        p_start = 0.0
    start_offset: float | None = (
        s_start - p_start if s_start is not None else None
    )

    if s_fps is None:
        rule, confidence = "unresolvable", "unresolvable"
    elif (
        fps_exact and s_vfr == "cfr" and p_vfr == "cfr"
        and s_count is not None and p_count is not None
        and s_count == p_count
    ):
        # Reaching this branch requires both frame counts to be non-None,
        # which a capped run can never satisfy (truncation nulls at least
        # one count, so it routes to the else branch below). The
        # truncation reason is added separately in the verdict; a
        # bounded run therefore never claims "verified" here.
        rule, confidence = "index-identity", "verified"
    else:
        rule, confidence = "pts-anchored", "degraded"

    b_note = (
        "mapping is display (PTS) order; B-frame decode order is not "
        "tracked (a note, never a penalty)"
        if rule != "unresolvable" else ""
    )
    mapping = FrameMapping(
        source_fps=str(s_fps) if s_fps is not None else None,
        proxy_fps=(
            f"{p_fps.numerator}/{p_fps.denominator}"
            if p_fps is not None
            else (_first_video(proxy_streams) or {}).get("avg_frame_rate")
        ),
        fps_exact_match=fps_exact,
        source_frame_count=s_count,
        proxy_frame_count=p_count,
        source_first_pts=s_first,
        source_last_pts=s_last,
        proxy_first_pts=p_first,
        proxy_last_pts=p_last,
        vfr_source=s_vfr,
        vfr_proxy=p_vfr,
        mapping_rule=rule,
        start_pts_offset_s=start_offset,
        source_start_time=s_start,
        b_frames_note=b_note,
        confidence=confidence,
    )

    # ── audio: stream counts + sr + layouts (loss is blocking) ─────
    s_audio = getattr(source_probe, "audio", []) or []
    s_sr: list[int | None] = []
    s_cl: list[str | None] = []
    for a in s_audio:
        s_sr.append(getattr(a, "sample_rate", None))
        s_cl.append(getattr(a, "channel_layout", None))
    p_n, p_sr, p_cl = _audio_of(proxy_streams)
    s_n = len(s_audio)
    audio_lost = p_n < s_n
    audio_note = (
        f"{s_n} source audio track(s) -> {p_n} proxy track(s): "
        "audio stream loss" if audio_lost else ""
    )
    audio = AudioReport(
        source_streams=s_n, proxy_streams=p_n,
        source_sample_rates=tuple(s_sr), proxy_sample_rates=tuple(p_sr),
        source_channel_layouts=tuple(s_cl),
        proxy_channel_layouts=tuple(p_cl),
        streams_lost=audio_lost, note=audio_note,
    )

    # ── color / rotation: content loss blocks, missing tags don't ──
    s_mv = source_probe.video[0] if source_probe.video else None
    s_hdr = getattr(s_mv, "hdr", "unknown") if s_mv else "unknown"
    s_rot = getattr(s_mv, "rotation", None) if s_mv else None
    p_hdr = _stream_hdr(proxy_streams)
    p_rot = _stream_rotation(proxy_streams)
    hdr_lost = s_hdr == "hdr-sdr" and p_hdr != "hdr-sdr"
    rotation_lost = (
        s_rot is not None and s_rot != 0 and (p_rot is None or p_rot == 0)
    )
    if hdr_lost:
        color_note = ("HDR content (source) downgraded to SDR proxy: "
                      "tone-mapping is irreversible in the proxy")
    elif not rotation_lost and s_hdr in ("sdr", "unknown") and p_hdr == "unknown":
        color_note = ("color metadata tags not carried into the proxy "
                      "(metadata-only: no content risk claimed)")
    else:
        color_note = ""
    color = ColorReport(
        source_hdr=s_hdr, proxy_hdr=p_hdr,
        source_rotation=s_rot, proxy_rotation=p_rot,
        hdr_lost=hdr_lost, rotation_lost=rotation_lost, note=color_note,
    )

    # ── timecode: the proxy never carries a TC track; the mapping is
    #    PTS-anchored and the absence is REPORTED, not guessed ──────
    s_tc = getattr(source_probe, "timecode", None)
    s_tc_basis = getattr(source_probe, "timecode_basis", "unresolved")
    proxy_tc_present = any(
        bool((v.get("tags") or {}).get("timecode"))
        for v in proxy_streams if v.get("codec_type") == "video"
    )
    tc_note = ""
    if start_offset is not None and abs(start_offset) > _LARGE_OFFSET_S:
        tc_note = (
            f"start-PTS offset {start_offset:.3f}s recorded "
            f"(reel-style start); absorbed into the pts mapping, "
            "reported not error"
        )
    elif s_tc == "drop" and not proxy_tc_present:
        tc_note = ("source is drop-frame-capable; the proxy carries no TC "
                   "track — mapping is PTS-anchored, drop-frame semantics "
                   "NOT preserved in metadata (report, never guess)")
    timecode = TimecodeReport(
        source_timecode=s_tc, source_timecode_basis=s_tc_basis,
        proxy_timecode_present=bool(proxy_tc_present),
        mapping_anchor="pts", note=tc_note,
    )

    # ── assemble the verdict ───────────────────────────────────────
    reasons: list[str] = []
    if s_vfr == "vfr-likely" or p_vfr == "vfr-likely":
        reasons.append(
            "vfr timeline detected (vfr-likely on source and/or proxy): "
            "mapping is time-domain (pts-anchored), not frame-index"
        )
    if s_fps is not None and p_fps is not None and not fps_exact:
        reasons.append(
            f"fps mismatch: source {s_fps} vs proxy {p_fps} (re-timed "
            "content; metadata presence is not acceptance)"
        )
    if s_count is not None and p_count is not None and s_count != p_count:
        reasons.append(
            f"frame count mismatch: source {s_count} vs proxy {p_count}"
        )
    if truncated:
        reasons.append(
            f"frame enumeration truncated at max_frames={max_frames}: "
            "frame counts unverified (bounded readback)"
        )
    if rule == "unresolvable":
        reasons.append(
            "fps not resolvable on at least one side: frame mapping "
            "unresolvable (time-domain only)"
        )
    if audio_lost:
        reasons.append(
            f"audio stream loss: {s_n} source track(s) -> {p_n} "
            "proxy track(s)"
        )
    if hdr_lost:
        reasons.append(
            "hdr content downgraded to SDR proxy (explicit downgrade, "
            "irreversible)"
        )
    if rotation_lost:
        reasons.append(
            f"rotation/orientation metadata lost: source "
            f"{s_rot}deg -> proxy none"
        )

    family = getattr(source_probe, "camera_family", "unknown")
    family_verified = bool(
        getattr(source_probe, "family_verified", False)
    )
    if not family_verified:
        status = STATUS_UNVERIFIED
        reasons.insert(
            0,
            f"camera family {family!r} unverified (UNVERIFIED): no "
            "tested real media for this family on this host; mapping "
            "evidence computed for audit only, not accepted",
        )
    elif reasons:
        status = STATUS_DEGRADED
    else:
        status = STATUS_VERIFIED

    return EditorVerdict(
        status=status, reasons=tuple(reasons), frame_mapping=mapping,
        audio=audio, color=color, timecode=timecode,
        camera_family=family, family_verified=family_verified,
        asset_id=asset_id, reel=reel,
    )


__all__ = [
    "STATUS_DEGRADED",
    "STATUS_UNVERIFIED",
    "STATUS_VERIFIED",
    "AudioReport",
    "ColorReport",
    "EditorVerdict",
    "FrameMapping",
    "TimecodeReport",
    "validate_editor_proxy",
]
