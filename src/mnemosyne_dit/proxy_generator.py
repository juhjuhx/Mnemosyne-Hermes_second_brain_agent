"""proxy_generator.py — DIT 2.2 P11 proxy pipeline (CPU FFmpeg MVP).

Reads a source clip (never modifies it), encodes a small, playable
proxy with CPU ffmpeg, then verifies + atomically publishes it using
the P08 `StagedArchive` receipt shape (staging -> verify -> last-write
receipt -> atomic `os.replace`). External artifacts are fenced by their
destination receipt, not by the queue's DB CAS (P09.1 spec §4.3): a
stolen-lease writer's artifacts are detectable and discardable via the
`job_id` + `lease_token` recorded in the receipt.

Spec: docs/engineering/spec/P11-proxy-generator.md.

Safety contract:
- The source is opened READ-ONLY (ffmpeg `-i`); no write handle on it.
- No implicit network URL: a URL source is refused before ffmpeg runs.
- shell-free argv, timeout, non-zero exit -> ProxyEncodeError.
- Capability-decided editor target: DNxHR/ProRes when the build has
  the encoder, else an honest h264 fallback with `degraded=True`
  (never a fake ProRes claim).
- A proxy NEVER raises an archive safety verdict (P11 contract): this
  module has no verdict surface.
- No v4 imports (files.db / qdrant / indexer), zero cloud.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from media_probe import (
    ProbeError,
    _sha256_file,
    probe,
    run_ffprobe_json,
)

# ── limits ──────────────────────────────────────────────────────────

_MAX_STDERR_BYTES = 2048
_DEFAULT_TIMEOUT_S = 120.0
_BROWSER_MAX_HEIGHT = 720


class ProxyInputError(Exception):
    """The caller passed a source we refuse to encode (URL / empty)."""


class ProxyEncodeError(Exception):
    """ffmpeg could not encode the proxy (exit != 0 / timeout / missing)."""


class ProxyVerifyError(Exception):
    """The encoded proxy failed the verification gate (corrupt, wrong
    length, missing audio) and was NOT published."""


# ── result model ────────────────────────────────────────────────────


@dataclass
class ProxyResult:
    path: str
    profile: str
    codec: str
    container: str
    degraded: bool
    source: str
    source_fps: Fraction | None
    source_timecode: str | None
    source_reel: str | None
    audio_mapping: list[dict]
    source_sha256: str | None
    proxy_sha256: str
    receipt: dict
    size_bytes: int
    duration_s: float | None

    def to_evidence_json(self) -> str:
        return json.dumps(
            {
                "path": self.path,
                "profile": self.profile,
                "codec": self.codec,
                "container": self.container,
                "degraded": self.degraded,
                "source": self.source,
                "source_sha256": self.source_sha256,
                "proxy_sha256": self.proxy_sha256,
                "receipt": self.receipt,
            },
            ensure_ascii=False,
        )


# ── editor capability detection (honest) ──────────────────────────


def detect_editor_capabilities(ffmpeg_bin: str = "ffmpeg") -> set[str]:
    """Which editor-target encoders this build actually ships.
    Returns a subset of {"dnxhr", "prores"}; an empty set means the
    editor target will honestly degrade to h264. Best-effort: a
    failure to enumerate degrades to an empty set (safe direction)."""
    available: set[str] = set()
    try:
        p = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True, timeout=30, check=False,
        )
        text = (p.stdout or b"").decode("utf-8", "replace")
        if re.search(r"\bprores\b", text):
            available.add("prores")
        if re.search(r"\bdnxhr\b", text):
            available.add("dnxhr")
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return set()
    return available


# ── subprocess helpers ─────────────────────────────────────────────


def _run_ffmpeg(ffmpeg_bin: str, args: list[str], timeout_s: float) -> tuple[int, bytes, bytes]:
    """Run ffmpeg; return (returncode, stdout, stderr). Timeouts and
    missing-binary are reported here (encode stage) as a non-zero code
    with a diagnostic in stderr."""
    if shutil.which(ffmpeg_bin) is None:
        raise ProxyEncodeError(f"ffmpeg binary not found: {ffmpeg_bin!r}")
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", *args],
            capture_output=True, timeout=timeout_s, check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, b"", f"ffmpeg timed out after {timeout_s}s".encode()
    except FileNotFoundError:
        return 1, b"", f"ffmpeg binary not found: {ffmpeg_bin!r}".encode()


def _ffmpeg_version(ffmpeg_bin: str) -> str:
    try:
        p = subprocess.run([ffmpeg_bin, "-version"], capture_output=True,
                           timeout=15, check=False)
        first = (p.stdout or b"").decode("utf-8", "replace").splitlines()
        return first[0].strip() if first else "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


# ── external artifact fencing (P08 receipt shape + P09.1 token) ────


def find_stale_proxies(out_dir: Path, job_id: str, expected_token: str) -> list[str]:
    """Return the proxy filenames under `job_id` whose receipt records a
    lease_token that is NOT the current one (stolen-lease artifacts,
    detectable and discardable). Receipts of other jobs are never
    touched. A missing/undecodable receipt => the artifact is treated
    as stale (fail-closed: anything we cannot attribute is suspicious)."""
    out_dir = Path(out_dir)
    stale: list[str] = []
    if not out_dir.is_dir():
        return stale
    receipt_rx = re.compile(r"^(?P<base>.+)\.receipt\.json$")
    receipts = [f for f in out_dir.iterdir()
                if f.is_file() and f.name.endswith(".receipt.json")]
    for rfile in receipts:
        m = receipt_rx.match(rfile.name)
        if not m:
            continue
        try:
            rec = json.loads(rfile.read_text())
        except (OSError, json.JSONDecodeError):
            stale.append(m.group("base"))  # unattributable => stale
            continue
        if rec.get("job_id") != job_id:
            continue
        if rec.get("lease_token") != expected_token:
            stale.append(m.group("base"))
    return stale


def delete_proxies(out_dir: Path, job_id: str | None = None) -> int:
    """Delete proxy artifacts (and their receipts). With `job_id`, only
    that job's receipts are matched (other jobs' artifacts survive);
    without it, every `*.receipt.json`'s sibling + the receipt are
    removed. Returns the number of files removed. Sources are never
    touched — only files named by a receipt in `out_dir`."""
    out_dir = Path(out_dir)
    removed = 0
    if not out_dir.is_dir():
        return 0
    receipt_rx = re.compile(r"^(?P<base>.+)\.receipt\.json$")
    receipts = [f for f in out_dir.iterdir()
                if f.is_file() and f.name.endswith(".receipt.json")]
    for rfile in receipts:
        m = receipt_rx.match(rfile.name)
        if not m:
            continue
        base = m.group("base")
        if job_id is not None:
            try:
                rec = json.loads(rfile.read_text())
                if rec.get("job_id") != job_id:
                    continue
            except (OSError, json.JSONDecodeError):
                continue
        artifact = out_dir / base
        artifact_ok = False
        if artifact.exists():
            artifact.unlink()
            removed += 1
            artifact_ok = True
        rfile.unlink()
        removed += 1
        del artifact_ok
    return removed


# ── profiles ────────────────────────────────────────────────────────


def _pick_encoder(profile: str, caps: set[str]) -> tuple[list[str], str, str, bool]:
    """Build (video-encoder args, codec, container, degraded). The
    container is chosen from the codec's natural muxer, not the caller."""
    if profile == "browser":
        args = ["-c:v", "libx264", "-preset", "veryfast",
                "-profile:v", "main", "-pix_fmt", "yuv420p"]
        return args, "h264", "mp4", False
    # editor: pick the best available editor encoder, else degrade.
    if "dnxhr" in caps:
        return ["-c:v", "dnxhr_lb"], "dnxhr", "mxf", False
    if "prores" in caps:
        # ProRes Proxy floor: the bare prores encoder (Apple's official
        # 10-bit encoder; this build supports yuv422p10le and friends,
        # and ffmpeg auto-converts the 8-bit source into it). Not a fake
        # h264 posing as ProRes.
        return ["-c:v", "prores"], "prores", "mov", False
    # honest fallback: h264, flagged as degraded
    args = ["-c:v", "libx264", "-preset", "veryfast",
            "-profile:v", "main", "-pix_fmt", "yuv420p"]
    return args, "h264", "mov", True


# ── public API ──────────────────────────────────────────────────────


def generate_proxy(
    source: str | Path,
    profile: str,
    out_dir: str | Path,
    *,
    source_probe=None,
    job_id: str | None = None,
    lease_token: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    fps_cap: int | None = None,
) -> ProxyResult:
    """Encode a playable proxy of `source` into `out_dir` and atomically
    publish it (staging -> verify -> receipt -> rename). The source is
    never modified. A proxy never raises an archive safety verdict."""
    src = Path(source)
    # URL refusal on the ORIGINAL string: Path() collapses "http://x" to
    # "http:/x" and would hide the scheme from _reject_url.
    if "://" in str(source) or str(source).lower().startswith(
        ("http:", "ftp:", "data:", "srt:", "udp:")
    ):
        raise ProxyInputError(
            f"refusing to encode a network URL ({source!r}); pass a local "
            f"file path"
        )
    if not src.exists():
        raise ProxyInputError(f"no such source file: {src}")
    if src.stat().st_size == 0:
        raise ProxyInputError(f"empty source: {src}")
    if profile not in ("browser", "editor"):
        raise ProxyInputError(f"unknown profile {profile!r}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    caps = detect_editor_capabilities(ffmpeg_bin)
    v_args, codec, container, degraded = _pick_encoder(profile, caps)

    # source correspondence (copied from the probe, not recomputed)
    if source_probe is not None:
        s_fps = source_probe.fps
        s_tc = source_probe.timecode
        s_reel = None
        for sc in getattr(source_probe, "sidecars", []) or []:
            if sc.lower().endswith(".sidecar.json"):
                s_reel = sc
        audio_mapping = [
            {"index": a.index, "codec": a.codec,
             "sample_rate": a.sample_rate,
             "channel_layout": a.channel_layout}
            for a in source_probe.audio
        ]
        source_sha = source_probe.source_sha256
        ref_duration = source_probe.duration_s
    else:
        try:
            s_probe = probe(src, sha256=True)
            s_fps, s_tc = s_probe.fps, s_probe.timecode
            s_reel = None
            audio_mapping = [
                {"index": a.index, "codec": a.codec,
                 "sample_rate": a.sample_rate,
                 "channel_layout": a.channel_layout}
                for a in s_probe.audio
            ]
            source_sha = s_probe.source_sha256
            ref_duration = s_probe.duration_s
        except ProbeError:
            # The source is too corrupt to probe: degrade to "no
            # correspondence" and let ffmpeg surface the real encode
            # error (a corrupt input must not be silently accepted).
            s_fps, s_tc, s_reel = None, None, None
            audio_mapping = []
            source_sha = None
            ref_duration = None

    ext = {"mp4": ".mp4", "mxf": ".mxf", "mov": ".mov"}[container]
    # Namespace artifacts by job_tag (job_id or "ad-hoc"): two DIFFERENT
    # jobs sharing a source + profile + out dir never collide — each
    # publishes `{job_tag}__{stem}__{profile}{ext}` with its own receipt.
    # Re-entry with the SAME job is an idempotent atomic replace.
    job_tag = job_id or "ad-hoc"
    stem = f"{job_tag}__{src.stem}__{profile}"

    staging_root = out / ".staging" / job_tag
    staging_root.mkdir(parents=True, exist_ok=True)
    staged = staging_root / f"{stem}{ext}"

    ff_args: list[str] = ["-y", "-loglevel", "error", "-i", str(src)]
    ff_args += v_args
    if fps_cap:
        ff_args += ["-r", str(fps_cap)]
    if profile == "browser":
        # cap height for a browser-friendly proxy (never upscale)
        ff_args += ["-vf", f"scale='min(iw,{_BROWSER_MAX_HEIGHT * 2})':'min(ih,{_BROWSER_MAX_HEIGHT})'"]
    # carry source audio 1:1 (a264/aac floor); if none, don't add
    if audio_mapping:
        ff_args += ["-c:a", "aac", "-b:a", "192k"]
    ff_args += [str(staged)]

    rc, _out, err = _run_ffmpeg(ffmpeg_bin, ff_args, timeout_s)
    if rc != 0:
        summary = (err[:_MAX_STDERR_BYTES].decode("utf-8", "replace")).strip()
        raise ProxyEncodeError(f"ffmpeg exited {rc}: {summary[:500]}")

    # ── verify gate: read the STAGED artifact back with ffprobe ────
    try:
        back = run_ffprobe_json(staged, ffprobe_bin="ffprobe")
    except ProbeError as e:
        _discard(staging_root, staged)
        raise ProxyVerifyError(
            f"staged proxy failed verification (not decodable): {e}"
        ) from e

    fmt = back.get("format", {})
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    if ref_duration and duration is not None and abs(duration - ref_duration) > 0.5:
        _discard(staging_root, staged)
        raise ProxyVerifyError(
            f"staged proxy duration {duration}s deviates from source "
            f"{ref_duration}s beyond tolerance"
        )
    # audio stream count must match the mapping (or be absent)
    n_audio_back = sum(
        1 for s in back.get("streams", []) if s.get("codec_type") == "audio"
    )
    if audio_mapping and n_audio_back != len(audio_mapping):
        _discard(staging_root, staged)
        raise ProxyVerifyError(
            f"staged proxy has {n_audio_back} audio streams; expected "
            f"{len(audio_mapping)} per the source mapping"
        )

    proxy_sha = _sha256_file(staged)
    receipt = {
        "job_id": job_id,
        "lease_token": lease_token,
        "source_sha256": source_sha,
        "proxy_sha256": proxy_sha,
        "ffmpeg_version": _ffmpeg_version(ffmpeg_bin),
        "argv": [ffmpeg_bin, "-hide_banner", *ff_args],
        "codec": codec,
        "container": container,
        "profile": profile,
        "degraded": degraded,
        "status": "published",
    }

    # ── atomic publish: receipt FIRST, then rename ─────────────────
    receipt_path = out / f"{stem}{ext}.receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    published = out / f"{stem}{ext}"
    os.replace(staged, published)
    # clean up now-empty staging dir (best effort)
    try:
        staging_root.rmdir()
        (out / ".staging").rmdir()
    except OSError:
        pass

    return ProxyResult(
        path=str(published),
        profile=profile,
        codec=codec,
        container=container,
        degraded=degraded,
        source=str(src),
        source_fps=s_fps,
        source_timecode=s_tc,
        source_reel=s_reel,
        audio_mapping=audio_mapping,
        source_sha256=source_sha,
        proxy_sha256=proxy_sha,
        receipt=receipt,
        size_bytes=published.stat().st_size,
        duration_s=duration,
    )


def _discard(staging_root: Path, staged: Path) -> None:
    """Best-effort cleanup of a failed staging artifact (never the source)."""
    try:
        if staged.exists():
            staged.unlink()
    except OSError:
        pass
