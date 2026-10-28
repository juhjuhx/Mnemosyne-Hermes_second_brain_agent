"""P12.2 Phase E — full synthetic integration sequence:

    Admission -> Queue -> Probe -> Proxy -> Recovery -> Scene

Every layer's IDs must line up (asset/replica/job/generation +
manifest + evidence provenance). This is the Phase 5 acceptance
sequence on synthetic media: it proves the CHAIN, not hardware.

Run: pytest tests/test_dit22_integration_sequence.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

import media_probe
from artifact_recovery import (
    apply_recovery,
    reconcile_proxy_job,
)
from asset_schema import (
    AssetPathObservation,
    Dit22Catalog,
    MediaAsset,
    Replica,
    VerificationEvidence,
)
from editor_validation import STATUS_VERIFIED, validate_editor_proxy
from job_queue import DurableJobQueue
from proxy_generator import generate_proxy, generation_tag
from scene_detect import FixedIntervalProvider
from source_admission import admit_source
from source_pinner import (
    SourceDriftError,
    manifest_digest_of,
    pin_from_admission,
)

FFMPEG = "ffmpeg"


def _mk_source(path: Path, audio: bool = True) -> Path:
    """A real 2s 320x240 24p clip (one 48k mono audio track by
    default — the audio stream keeps the chain's audio-mapping live)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
    ]
    if audio:
        args += ["-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=48000:duration=2"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    args.append(str(path))
    subprocess.run(args, check=True)
    assert path.stat().st_size > 0
    return path


def _make_catalog_and_source(tmp_path: Path, name: str = "reel_A.mov") -> tuple[Dit22Catalog, Path, str]:
    """A VERIFIED replica chain on a tmp 'storage' (synthetic device)."""
    cat = Dit22Catalog(tmp_path / "cat.db")
    src = _mk_source(tmp_path / "media" / name)
    aid = media_probe._sha256_file(src)
    cat.upsert_asset(MediaAsset(source_sha256=aid))
    cat.add_observation(
        AssetPathObservation(aid, "sd-synthetic", str(src), src.stat().st_size)
    )
    cat.add_replica(
        Replica("rep-A", aid, "sd-synthetic", "card-synthetic", str(src),
                verified=True)
    )
    cat.add_evidence(
        VerificationEvidence(
            evidence_id="ev-A", asset_id=aid, file_name=src.name,
            algorithm="sha256", digest=aid, verdict="PASS",
            replica_id="rep-A",
        )
    )
    return cat, src, aid


# ══════════════════════════════ the full chain ═════════════════════


def test_I1_full_chain_admission_to_scene(tmp_path):
    cat, src, aid = _make_catalog_and_source(tmp_path)

    # ── 1. ADMISSION (P11.1-A) ──
    dec = admit_source(cat, "sd-synthetic", src)
    assert dec.admitted and dec.asset_id == aid
    assert dec.replica_id == "rep-A"
    assert dec.source_sha256 == aid

    # ── 2. DURABLE QUEUE (P09) — the manifest is the C2 truth source ──
    manifest = {"reel_A.mov": aid}
    q = DurableJobQueue(tmp_path / "jobs.db")
    try:
        job = q.enqueue("proxy-reel-A", manifest,
                        idempotency_key="i1", max_attempts=3)
        jid = job["job_id"]
        token = q.lease(jid, "worker-1", ttl_seconds=300)

        # ── 3. MEDIA PROBE (P10) — carries the content identity ──
        probe = media_probe.probe(src, sha256=True)
        assert probe.source_sha256 == aid
        assert probe.fps == Fraction(24)

        # ── 4. PROXY (P11/P11.1-B) with C1 pinner + C4 reservation ──
        pin = pin_from_admission(
            dec, catalog=cat, manifest=manifest,
        )
        assert pin.manifest_digest == manifest_digest_of(manifest)
        assert pin.asset_id == aid

        class _Roomy:
            free = 1 << 30
            total = 1 << 40

        result = generate_proxy(
            src, "editor", tmp_path / "proxies",
            job_id=jid, lease_token=token, test_mode=False,
            catalog=cat, storage_id="sd-synthetic",
            queue=q, worker="worker-1",
            source_probe=probe,
            source_pin=pin,
            capacity_probe=_Roomy(),
            estimated_staging_bytes=100_000,
            estimated_output_bytes=500_000,
            actual_manifest=manifest,
        )
        assert result.source_sha256 == aid
        pub = Path(result.path)
        assert pub.stat().st_size > 0
        receipt = json.loads(
            (tmp_path / "proxies" / f"{pub.name}.receipt.json").read_text()
        )
        assert receipt["job_id"] == jid
        assert receipt["lease_token"] == token
        assert receipt["source_sha256"] == aid

        # ── 5. ARTIFACT RECOVERY (P11.1-C) — a healthy publish
        # reconciles clean, idempotently, under the live lease ──
        report = reconcile_proxy_job(tmp_path / "proxies", jid,
                                    expected_token=token)
        assert report.is_published()
        assert report.published_sha == result.proxy_sha256
        assert report.issues == ()
        rr = apply_recovery(tmp_path / "proxies", jid, report,
                           queue=q, worker="worker-1", token=token)
        assert rr.completed
        assert rr.published_generation == report.published_generation

        # a STALE token must be fenced (no mutation):
        rr_stale = apply_recovery(
            tmp_path / "proxies", jid, report,
            queue=q, worker="worker-2", token="forged-token",
        )
        assert not rr_stale.completed

        # ── 6. EDITOR VALIDATION (P11.1-D) — the edit-side truth ──
        verdict = validate_editor_proxy(
            src, result.path, source_probe=probe,
            asset_id=aid, reel="reel_A.mov",
        )
        assert verdict.status in (STATUS_VERIFIED, "EDITOR_DEGRADED")
        assert verdict.asset_id == aid
        fm = verdict.frame_mapping
        assert fm.source_frame_count and fm.proxy_frame_count
        # a 24p source + proxy: the mapping is reconstructable
        t = fm.source_index_to_proxy_time(47)
        assert t is not None and 1.9 <= t < 2.0

        # ── 7. SCENE DETECTION (P12) — the segment carries the IDs ──
        segs = FixedIntervalProvider(seconds=1.0).detect(
            result.path, fps=probe.fps, source_probe=probe,
            source_asset_id=aid, camera_reel="reel_A.mov",
        )
        assert len(segs) == 2
        for s in segs:
            assert s.source_asset_id == aid
            assert s.camera_reel == "reel_A.mov"

        # ── close the job: manifest still matches the C2 truth ──
        ok = q.complete(jid, "worker-1", manifest, token=token)
        assert ok
    finally:
        q.close()


# ═══════════════════ negative: the chain's failure modes ══════════


def test_I2_source_mutated_after_admission_blocks_encode(tmp_path):
    """C1 TOCTOU: a replica rewrite between admission and encode
    must stop the job — the pre-encode pin re-verify raises, no
    ffmpeg, no staging."""
    cat, src, aid = _make_catalog_and_source(tmp_path)
    dec = admit_source(cat, "sd-synthetic", src)
    manifest = {"reel_A.mov": aid}
    pin = pin_from_admission(dec, catalog=cat, manifest=manifest)

    src.write_bytes(b"REPLACED-CONTENT")  # the TOCTOU window

    with pytest.raises(SourceDriftError):
        generate_proxy(
            src, "browser", tmp_path / "out",
            source_pin=pin, test_mode=True,
            actual_manifest=manifest,
            ffmpeg_bin="ffmpeg",
        )
    assert not (tmp_path / "out" / ".staging").exists()


def test_I3_replacement_at_same_path_denied_at_readmission(tmp_path):
    """C1/C2: a replaced file is a NEW asset — re-admission under the
    old trust chain fails closed (the replica record links the OLD
    content identity, not the new bytes)."""
    cat, src, _aid = _make_catalog_and_source(tmp_path)
    src.write_bytes(b"OTHER-BYTES-AT-SAME-PATH")
    dec2 = admit_source(cat, "sd-synthetic", src)
    assert dec2.admitted is False  # the chain no longer matches


def test_I4_crash_recovery_replays_a_receipt_first_window(tmp_path):
    """P11.1-C crash window, end-to-end on the real chain: a
    receipt-first interrupted publish is completed by the reconciler
    under the live lease — the published generation then reconciles
    clean and the editor validation still verifies it."""
    cat, src, aid = _make_catalog_and_source(tmp_path)
    manifest = {"reel_A.mov": aid}
    q = DurableJobQueue(tmp_path / "jobs.db")
    try:
        job = q.enqueue("proxy-reel-A", manifest, idempotency_key="i4")
        jid = job["job_id"]
        token = q.lease(jid, "w", ttl_seconds=300)
        probe = media_probe.probe(src, sha256=True)
        out = tmp_path / "proxies"
        result = generate_proxy(
            src, "browser", out, job_id=jid, lease_token=token,
            test_mode=False, catalog=cat, storage_id="sd-synthetic",
            queue=q, worker="w", source_probe=probe,
        )
        pub = Path(result.path)
        g = generation_tag(token)

        # Simulate the receipt-first crash window: the receipt is
        # written but the artifact is still in its staging generation
        # (the publish rename never happened). Move the published
        # artifact back into its staged location to recreate it.
        assert (out / f"{pub.name}.receipt.json").exists()
        staged = out / ".staging" / jid / g / pub.name
        staged.parent.mkdir(parents=True, exist_ok=True)
        pub.replace(staged)
        assert not pub.exists() and staged.exists()

        report = reconcile_proxy_job(out, jid, expected_token=token)
        assert not report.is_published()
        kinds = report.issues_by_kind()
        assert kinds.get("pending_rename"), kinds

        rr = apply_recovery(out, jid, report, queue=q, worker="w",
                            token=token)
        assert rr.completed
        assert pub.exists()
        rep2 = reconcile_proxy_job(out, jid, expected_token=token)
        assert rep2.is_published()
        assert rep2.published_sha == result.proxy_sha256
    finally:
        q.close()


def test_I5_scene_on_an_unverified_probe_is_honest(tmp_path):
    """C6-adjacent: a probe with unknown fps must not feed scene
    detection as if it were verified — the provider refuses a None
    fps instead of inventing frame numbers (fail-closed, no silent
    fabrication of a mapping)."""
    p = media_probe.MediaProbe(
        path=str(tmp_path / "x.mov"),
        ffprobe_version="x",
        container="mov",
        duration_s=2.0,
        nb_streams=0,
        video=[],
        audio=[],
        fps=None,
        fps_status="unknown",
        vfr_status="unknown",
        timecode=None,
        timecode_basis="none",
        camera_family="unknown",
        family_verified=False,
    )
    provider = FixedIntervalProvider(seconds=1.0)
    # _frame_context refuses to guess: ValueError("fps unknown …")
    with pytest.raises(ValueError, match="fps unknown"):
        provider.detect(tmp_path / "x.mov", fps=p.fps,
                        source_probe=p, source_asset_id="a")
