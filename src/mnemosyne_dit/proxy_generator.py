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

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from capacity_gate import CapacityShortError, check_capacity
from media_probe import (
    ProbeError,
    _sha256_file,
    probe,
    run_ffprobe_json,
)
from path_isolation import HARDWARE_BLOCKED, PathIsolationError, check_path_isolation
from source_admission import (
    AdmissionDecision,
    ProxySourceAdmissionError,
    admit_source,
    record_admission_evidence,
)
from source_pinner import SourceDriftError, SourcePin, verify_pin

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


class ProxyFencedError(Exception):
    """P11.1-B publication fencing: the lease obligation failed (a
    formal job carrying a lease_token without a live-check, or a lease
    that died before / mid-encode), or the target slot is not ours to
    clobber (receipt-less healthy artifact, another job's receipt, an
    undecodable receipt). A fenced publish discards the staged
    artifact; nothing published is ever overwritten by a stale
    worker."""


def generation_tag(lease_token: str | None) -> str:
    """A short, path-safe staging-generation tag derived from the lease
    token (tok- prefix + first 12 hex of its sha256). Two lease
    generations of the same job therefore never share a staging
    target, so a zombie worker's partial write cannot land in the
    current holder's slot. `None` (ad-hoc / test path) is a fixed
    `unleased` tag."""
    if lease_token is None:
        return "unleased"
    digest = hashlib.sha256(str(lease_token).encode("utf-8")).hexdigest()
    return "tok-" + digest[:12]


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
    admission: AdmissionDecision | None = None  # None only in test_mode

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
        if artifact.exists():
            artifact.unlink()
            removed += 1
        rfile.unlink()
        removed += 1
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
    test_mode: bool = False,
    catalog=None,
    storage_id: str | None = None,
    device_provider=None,
    queue=None,
    worker: str | None = None,
    source_pin: SourcePin | None = None,
    protected_source: bool = False,
    capacity_probe=None,
    estimated_staging_bytes: int = 0,
    estimated_output_bytes: int = 0,
    capacity_safety_factor: float = 1.0,
    actual_manifest: dict | None = None,
) -> ProxyResult:
    """Encode a playable proxy of `source` into `out_dir` and atomically
    publish it (staging -> verify -> receipt -> rename). The source is
    never modified. A proxy never raises an archive safety verdict.

    P11.1-A admission: a formal job (`job_id` set, not `test_mode`)
    MUST pass a `catalog` + `storage_id`; the source is admitted by the
    `source_admission` gate (fail-closed) and a DENIED source raises
    `ProxySourceAdmissionError` before any ffmpeg. An admitted outcome
    is recorded in the catalog's evidence ledger. `test_mode` is the
    isolated synthetic path (never with a catalog): it skips the gate
    and records nothing.

    P11.1-B publication fencing: a formal job carrying a `lease_token`
    MUST also pass the live-lease truth source — `queue` (a P09
    `DurableJobQueue`) + `worker`. The lease is verified against the
    queue row (state LEASED, holder, exact token, unexpired — P09.1
    `_assert_leased_to` semantics) at START and re-verified at the
    PUBLISH moment (a lease can die mid-encode). A dead lease raises
    `ProxyFencedError` and the staged artifact is discarded. Staging
    is versioned by the token (`generation_tag`), so two lease
    generations of one job never share a target; a successful live
    publish sweeps the job's stale staging generations. A published
    slot that is not ours to own (receipt-less healthy artifact,
    another job's receipt, an undecodable receipt) is fenced, never
    clobbered. Writing the token into the receipt alone (P09.1
    detection-based fencing) is NOT a publication fence — it only
    detects an already-happened clobber.

    P12.2 Phase-4 gates (all optional => default behavior unchanged):
    - `source_pin` (C1/C2): when given, the pinner RE-VERIFIES the
      source's identity before ffmpeg AND after encode completes (the
      C1 TOCTOU close — a pre-execution SHA alone is not sufficient:
      drift can land mid-encode). A pre-encode mismatch raises
      `SourceDriftError`; a post-encode mismatch discards the staged
      artifact (nothing is published on a drifted source).
    - `protected_source` (C5): a camera-card / NAS volume that must
      stay pristine — the path-isolation gate then also refuses
      staging INSIDE the source's own directory.
    - `capacity_probe` (C4): when given, a pre-encode storage
      reservation (estimated staging + output bytes, factor-applied)
      runs BEFORE ffmpeg; a short volume raises `CapacityShortError`.
    - out_dir UNC paths return the pinner's `HARDWARE_BLOCKED`
      verdict (C6: never a fabricated pass).
    - `actual_manifest` (C2): the queue's input manifest, re-checked
      against a manifest-bound pin at both pre-encode and post-encode
      moments; a missing manifest on a manifest-bound pin is a fail.
    """
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
    if profile not in ("browser", "editor"):
        raise ProxyInputError(f"unknown profile {profile!r}")

    out = Path(out_dir)
    # ── P12.2 Phase-4 pre-encode gates (fail-closed, before any I/O) ──
    # C5+C6 in one call: UNC / unverified-FS paths => the HARDWARE_BLOCKED
    # sentinel (never a fabricated pass); same/contains/protected-inside
    # containment => PathIsolationError.
    # C5: containment (same / contains / protected-inside) => wrap the
    # gate's PathIsolationError as the caller's input-level rejection.
    try:
        iso = check_path_isolation(
            str(src), str(out), protected_source=protected_source
        )
    except PathIsolationError as e:
        raise ProxyInputError(f"source/output path isolation failed: {e}")
    if iso == HARDWARE_BLOCKED:
        raise ProxyInputError(
            f"out_dir {out_dir!r} is a UNC/unverified-filesystem path — "
            "cross-volume rename + persistence are HARDWARE_BLOCKED on "
            "this build (C6); a pass verdict is not fabricated"
        )
    # C4: pre-encode storage reservation (estimated staging + output).
    if capacity_probe is not None:
        try:
            check_capacity(
                capacity_probe,
                estimated_staging_bytes=estimated_staging_bytes,
                estimated_output_bytes=estimated_output_bytes,
                safety_factor=capacity_safety_factor,
            )
        except CapacityShortError as e:
            raise ProxyInputError(
                f"destination cannot reserve the estimated staging + "
                f"output bytes (C4 storage reservation): {e}"
            )
    # C1/C2: the pinner re-verifies the source's identity BEFORE ffmpeg
    # (content + the C2 manifest digest, when the pin is manifest-bound).
    if source_pin is not None:
        verify_pin(source_pin, actual_manifest=actual_manifest)
    out.mkdir(parents=True, exist_ok=True)

    # ── P11.1-A source admission gate (fail-closed, BEFORE any encode) ──
    if test_mode and catalog is not None:
        raise ProxyInputError(
            "test_mode is the isolated synthetic path: pass test_mode WITHOUT "
            "a catalog. A fixture must not be admitted through, or recorded "
            "into, a formal catalog (it could not masquerade as a verified "
            "source)."
        )
    admission: AdmissionDecision | None = None
    if job_id is not None and not test_mode:
        # formal job: the gate is authoritative and runs FIRST — a missing
        # replica surfaces as the gate's `file_exists` denial, not a bare
        # input error.
        if catalog is None or storage_id is None:
            missing = "catalog" if catalog is None else "storage_id"
            raise ProxySourceAdmissionError(
                f"a formal proxy job ({job_id!r}) must pass a `catalog` and "
                f"`storage_id` to run the source admission gate; "
                f"missing {missing!r}"
            )
        decision = admit_source(
            catalog, storage_id, src, device_provider=device_provider
        )
        if not decision.admitted:
            # record the denial in the controlled ledger (when the file is
            # absent there is no asset identity to attribute the row to —
            # the job log carries it), then stop: a denied source never
            # reaches staging or ffmpeg.
            if decision.asset_id is not None:
                record_admission_evidence(
                    catalog, decision,
                    job_id=job_id,
                    evidence_id=f"adm-{job_id}-{decision.fingerprint[:12]}",
                )
            raise ProxySourceAdmissionError(
                f"source admission DENIED ({decision.reason}) for "
                f"{src!r} on {storage_id!r}: a denied source must not "
                f"enter the proxy pipeline"
            )
        # A 0-B source is refused even on a complete trust chain — and this
        # check runs BEFORE the ADMITTED outcome is written to the
        # controlled ledger, so an "ADMITTED" row can never point at a
        # source from which no encode actually ran (review Minor #2).
        if src.stat().st_size == 0:
            raise ProxyInputError(f"empty source: {src}")
        # the admission outcome is part of the job's controlled evidence:
        record_admission_evidence(
            catalog, decision,
            job_id=job_id,
            evidence_id=f"adm-{job_id}-ok-{decision.fingerprint[:12]}",
        )
        admission = decision
    else:
        # isolated (test_mode) or ad-hoc (no job_id) path: base checks,
        # no gate, nothing recorded.
        if not src.exists():
            raise ProxyInputError(f"no such source file: {src}")
        if src.stat().st_size == 0:
            raise ProxyInputError(f"empty source: {src}")

    # ── P11.1-B lease obligation: a formal lease-bound run must prove
    # the lease is still LIVE before we spend an encode on it. The live
    # truth is the P09 queue row (P09.1 `_assert_leased_to` semantics):
    # state LEASED, holder == worker, EXACT token, unexpired. ────────
    def _lease_live() -> bool:
        if queue is None or worker is None:
            return False
        try:
            row = queue.job_state(job_id)
        except KeyError:
            return False
        unexpired = (
            row["lease_expires_at"] is None
            or time.time() < row["lease_expires_at"]
        )
        return (
            row["state"] == "LEASED"
            and row["lease_worker"] == worker
            and row["lease_token"] == lease_token
            and unexpired
        )

    if job_id is not None and not test_mode and lease_token is not None:
        if queue is None or worker is None:
            missing = "queue" if queue is None else "worker"
            raise ProxyFencedError(
                f"a formal proxy job ({job_id!r}) carrying lease token "
                f"{lease_token!r} must pass a live-lease source "
                f"(a `queue` + `worker` {missing!r} is missing) — the "
                "publication fence is fail-closed, not skipped"
            )
        if not _lease_live():
            raise ProxyFencedError(
                f"lease fence failed at start: {job_id!r} token "
                f"{lease_token!r} is no longer {worker!r}'s live lease; "
                "re-lease before encoding"
            )

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
    # P11.1-B: staging is VERSIONED by the lease generation, so two lease
    # tokens of the same job never share a staging target (a zombie's
    # partial write cannot land in the live holder's slot).
    job_tag = job_id or "ad-hoc"
    stem = f"{job_tag}__{src.stem}__{profile}"
    gen = generation_tag(lease_token)

    staging_root = out / ".staging" / job_tag / gen
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

    # C1 (P12.2): "source changing WHILE FFmpeg runs" — a pre-execution
    # SHA is explicitly NOT sufficient. Re-verify the pin AFTER the
    # encode but BEFORE the receipt/publish; a drift that landed during
    # the encode means the staged bytes were cut from a DIFFERENT
    # source than the pinned identity, so nothing is published.
    if source_pin is not None:
        try:
            verify_pin(source_pin, actual_manifest=actual_manifest)
        except SourceDriftError as e:
            _discard(staging_root, staged)
            raise SourceDriftError(
                f"source drifted while FFmpeg was running ({e}); the "
                "staged proxy was cut from a different source than the "
                "pinned identity — it was discarded, nothing published"
            ) from e

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

    # ── P11.1-B publish-time fence + conditional publish ─────────────
    # A lease can die while we were encoding. The PUBLISH moment is where
    # ownership is decided: re-verify against the live-lease truth (queue
    # row) so a zombie cannot rename over the live holder's slot. (P09.1's
    # receipt-only fence is *detection* — it reads the token after the
    # clobber. This is the *stop*.)
    #
    # RESIDUAL TOCTOU WINDOW (reviewed, quantified — Minor #1): between
    # the `_lease_live()` re-check above and the receipt write +
    # `os.replace` below, the lease can still expire and be taken over —
    # a clobber by a just-staled writer is NOT impossible, only rarer.
    # This is deliberately NOT closed here: closing it needs a P11.1-C
    # generation-owned commit primitive (receipt+rename as one fenced
    # transaction) that does not exist yet. Mitigations in place:
    # (a) the window is sub-millisecond on local volumes; (b) P09.1's
    # detection backstop still fires post-hoc — `find_stale_proxies`
    # reports the clobbered slot stale under the NEW token, so nothing
    # is lost silently; (c) crash material inside the window is P08's
    # crash-discardable staging, not published truth. Documented as
    # P11.1-C territory (HARDWARE_BLOCKED on Windows/UNC, where
    # `os.replace` is not atomic cross-volume).
    if (
        job_id is not None
        and lease_token is not None
        and not test_mode
        and not _lease_live()
    ):
        _discard(staging_root, staged)
        raise ProxyFencedError(
            f"lease fence failed at publish: {job_id!r} token "
            f"{lease_token!r} is no longer live; the staged artifact "
            f"was discarded, nothing published"
        )

    # conditional publish: if the target slot already exists, decide
    # ownership from its receipt BEFORE writing anything. Fail-closed on
    # every unattributable signal:
    #   - healthy artifact + no/undecodable receipt => UNOWNABLE, never
    #     clobbered (an operator investigates; P11.1-C quarantines);
    #   - an undecodable receipt under our slot is ALWAYS a fence, even
    #     when the artifact is gone (it may be the only trace of a
    #     crash in the receipt-first window — we must not overwrite it);
    #   - a decodable receipt is replaceable ONLY when it attributes the
    #     slot to exactly THIS run's job (P09.1's detection semantics,
    #     made into a stop): a foreign job's receipt, an ad-hoc (None)
    #     receipt under a formal slot, or a dict with no `job_id` key at
    #     all (hand-crafted — no writer in this codebase emits that) is
    #     unattributable and fenced;
    #   - our own job's receipt (rotation / re-entry) => an atomic
    #     replace is allowed.
    published = out / f"{stem}{ext}"
    receipt_path = out / f"{stem}{ext}.receipt.json"
    if published.exists() or receipt_path.exists():
        existing_receipt = "undecodable"
        if receipt_path.exists():
            try:
                existing_receipt = json.loads(receipt_path.read_text())
            except (OSError, json.JSONDecodeError):
                existing_receipt = "undecodable"
        else:
            existing_receipt = None
        if (
            isinstance(existing_receipt, dict)
            and "job_id" in existing_receipt
            and existing_receipt["job_id"] != job_id
        ):
            _discard(staging_root, staged)
            raise ProxyFencedError(
                f"target {published.name!r} carries a receipt that does "
                f"not attribute it to this run's job "
                f"({existing_receipt.get('job_id', '<absent>')!r} != "
                f"{job_id!r}); refusing to clobber unattributable material"
            )
        if isinstance(existing_receipt, dict) and "job_id" not in existing_receipt:
            _discard(staging_root, staged)
            raise ProxyFencedError(
                f"target {published.name!r} carries a hand-crafted receipt "
                f"with no `job_id` key; unattributable — refusing to clobber"
            )
        if existing_receipt == "undecodable":
            _discard(staging_root, staged)
            raise ProxyFencedError(
                f"target {published.name!r} has an undecodable receipt; "
                f"refusing to overwrite unattributable evidence "
                f"(fail-closed)"
            )
        if published.exists() and existing_receipt is None:
            _discard(staging_root, staged)
            raise ProxyFencedError(
                f"target {published.name!r} is a healthy artifact without a "
                f"receipt; refusing to clobber it (fail-closed)"
            )

    # ── atomic publish: receipt FIRST, then rename ─────────────────
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    os.replace(staged, published)
    # P11.1-B live-success sweep: a successful publish by the LIVE holder
    # may discard this job's OTHER (stale/zombie) staging generations —
    # a stale worker never triggers it (no live lease => no sweep). The
    # operator's published artifacts + receipts are untouched.
    if job_id is not None and lease_token is not None and not test_mode:
        _sweep_stale_staging(out / ".staging" / job_tag, current_gen=gen)
    # clean up now-empty staging dirs (best effort)
    try:
        staging_root.rmdir()
        job_staging = out / ".staging" / job_tag
        try:
            job_staging.rmdir()
        except OSError:
            pass
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
        admission=admission,
    )


def _discard(staging_root: Path, staged: Path) -> None:
    """Best-effort cleanup of a failed staging artifact (never the source)."""
    try:
        if staged.exists():
            staged.unlink()
    except OSError:
        pass


def _sweep_stale_staging(job_staging_dir: Path, *, current_gen: str) -> int:
    """Discard the OTHER (stale/zombie) staging generations under a job's
    staging dir — P08 crash-discardable material (never a published
    artifact, never another job's dir, never the caller's own generation).
    Called only after a SUCCESSFUL publish by the live holder (the caller
    re-verified the lease), so a stale worker can never trigger it.
    Returns the number of foreign generation dirs removed."""
    removed = 0
    job_staging_dir = Path(job_staging_dir)
    if not job_staging_dir.is_dir():
        return 0
    for gen_dir in sorted(job_staging_dir.iterdir()):
        if not gen_dir.is_dir() or gen_dir.name == current_gen:
            continue
        shutil.rmtree(gen_dir, ignore_errors=True)
        if not gen_dir.exists():
            removed += 1
    return removed
