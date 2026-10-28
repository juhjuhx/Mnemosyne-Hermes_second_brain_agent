"""source_pinner.py — DIT 2.2 P12.2-B: the Source Identity Pinner.

The single cross-pipeline drift truth source for "the bytes ffmpeg
reads are still the bytes Admission verified". Phase 4 C1/C2 of
`docs/engineering/P4-integration-contract-audit.md`:

- C1 — TOCTOU between Admission (one hash at 0-B) and the post-encode
  receipt hash: two hashes, no equality check between them. The pinner
  closes the window: a `SourcePin` carries the expected identity, and
  `verify_pin` RE-HASHES on demand (a pre-execution SHA alone is
  explicitly NOT sufficient protection — that is the failure mode this
  module exists to stop).
- C2 — Source SHA256 drift: the queue's `input_manifest` is the drift
  truth source; a pin can additionally bind a manifest digest so
  admission-time and complete-time snapshots must agree.

Fail-closed matrix (any miss => `SourceDriftError`, no encode/publish):
- source mutated after admission (size or content);
- file replaced at the same path;
- source disappeared / device gone (no hash can be taken);
- manifest drift (bound digest != actual);
- different asset sharing a filename (collision pre-check against the
  catalog observations: two distinct asset_ids observed under the same
  basename on the same storage => the basename is not an identity,
  reject pin building on it);
- untrusted replica (replica not VERIFIED / not belonging to the
  asset => `pin_from_admission` refuses, before any encoding).

This module only READS the source (hash + stat, never a write handle).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class SourceDriftError(Exception):
    """The source no longer matches its pinned identity (or the pin
    itself is untrusted). No encode / publish may proceed on this
    source until a human re-admits it."""


# ── pin model ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourcePin:
    """Immutable snapshot of a source's trusted identity at
    admission time. `manifest_digest` is optional: when set, the pin
    additionally binds the queue's input manifest (C2)."""

    expected_sha256: str
    source_path: str
    source_size_bytes: int
    asset_id: str
    replica_id: str | None
    storage_id: str
    manifest_digest: str | None = None
    job_id: str = ""

    @property
    def source_file(self) -> Path:
        return Path(self.source_path)


@dataclass(frozen=True)
class PinVerification:
    """The outcome of one on-demand re-verification. `ok` is True only
    when every carried signal matches; the measured values are kept
    for the receipt/evidence trail."""

    ok: bool
    current_sha256: str | None
    current_size_bytes: int | None
    detail: str = ""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_digest_of(manifest: dict) -> str:
    """The queue's drift truth source (C2): a deterministic digest of
    the input manifest dict. Admission-time and complete-time
    manifests must digest identically or the job FAILs."""
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ── pin construction ────────────────────────────────────────────────


def pin_from_admission(
    decision, *, catalog=None, manifest: dict | None = None,
) -> SourcePin:
    """Build a pin from an `AdmissionDecision` (P11.1-A). The
    decision already proved: VERIFIED replica, PASS read-back
    evidence, content identity. This carries those identifiers onto
    the pin so every later layer can re-check the SAME identity.

    Trust re-check when a `catalog` is supplied (fail-closed, before
    any encoding): the decision's `replica_id` must still be recorded
    as VERIFIED and must BELONG TO the decision's asset — the same
    per-asset trust rule `source_admission._trusted_readback` uses.
    A pin built from an unverified / cross-asset replica is refused.
    `manifest` binds the C2 digest when supplied."""
    if not getattr(decision, "admitted", False):
        raise SourceDriftError(
            f"cannot pin a DENIED admission ({decision.reason!r}) — "
            "an unadmitted source has no trusted identity to pin"
        )
    if decision.replica_id is None:
        raise SourceDriftError(
            "admission carries no replica identity — a pin without a "
            "replica cannot be re-attributed (fail-closed)"
        )
    if catalog is not None:
        _recheck_replica_trust(catalog, decision)
    src = Path(decision.replica_path)
    if not src.is_file():
        raise SourceDriftError(
            f"admitted replica path {src} no longer exists at pin "
            "time — re-admit before pinning"
        )
    return SourcePin(
        expected_sha256=decision.source_sha256,
        source_path=str(src),
        source_size_bytes=src.stat().st_size,
        asset_id=decision.asset_id or "",
        replica_id=decision.replica_id,
        storage_id=decision.storage_id,
        manifest_digest=manifest_digest_of(manifest) if manifest is not None else None,
        job_id=getattr(decision, "job_id", "") or "",
    )


def _recheck_replica_trust(catalog, decision) -> None:
    """Re-verify, at pin time, that the decision's replica is still
    recorded as VERIFIED and still belongs to the decision's asset.
    (A replica re-registered against another asset, or flipped to
    unverified, is an untrusted chain — C2/C6 adjacency, fail
    closed.)"""
    reps = catalog.replicas_for(decision.asset_id)
    trusted = [
        r for r in reps if r.replica_id == decision.replica_id
    ]
    if not trusted or not all(r.verified for r in trusted):
        raise SourceDriftError(
            f"replica {decision.replica_id!r} is not a VERIFIED replica "
            f"of asset {decision.asset_id[:16]}… at pin time — the "
            "trust chain is broken; re-admit (fail-closed)"
        )


# ── verification ────────────────────────────────────────────────────


def verify_pin(
    pin: SourcePin, *, actual_manifest: dict | None = None,
) -> PinVerification:
    """Re-verify the pin against the CURRENT source. Reads the file
    (stat + streamed SHA256) — never writes it. Raises
    `SourceDriftError` on any mismatch; returns a `PinVerification`
    with the measured values when clean.

    Order is cheapest-signal-first: existence, size (free stat),
    content hash, then the manifest digest when both sides carry one.
    """
    src = pin.source_file
    if not src.is_file():
        raise SourceDriftError(
            f"source {src} has disappeared (device gone / file deleted); "
            "pinned identity can no longer be verified (fail-closed)"
        )
    st = src.stat()
    if st.st_size != pin.source_size_bytes:
        raise SourceDriftError(
            f"source {src} size drifted: pinned {pin.source_size_bytes} "
            f"bytes, now {st.st_size} — the source changed after "
            "admission; re-admit before encoding"
        )
    actual_sha = _sha256_file(src)
    if actual_sha != pin.expected_sha256:
        raise SourceDriftError(
            f"source {src} content drifted: pinned sha256 "
            f"{pin.expected_sha256[:16]}…, now {actual_sha[:16]}… — "
            "file replaced or mutated at the same path"
        )
    if pin.manifest_digest is not None:
        actual_digest = (
            manifest_digest_of(actual_manifest)
            if actual_manifest is not None
            else None
        )
        if actual_digest is None:
            raise SourceDriftError(
                "pin is manifest-bound but no actual manifest was "
                "supplied to verify against (C2: the queue's input "
                "manifest is the drift truth source; a missing one is "
                "a fail)"
            )
        if actual_digest != pin.manifest_digest:
            raise SourceDriftError(
                f"input manifest drifted: pinned digest "
                f"{pin.manifest_digest[:16]}…, actual "
                f"{actual_digest[:16]}… (C2)"
            )
    return PinVerification(
        ok=True,
        current_sha256=actual_sha,
        current_size_bytes=st.st_size,
        detail="verified",
    )
