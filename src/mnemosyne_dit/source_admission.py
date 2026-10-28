"""source_admission.py — DIT 2.2 P11.1-A: the Source Admission Gate.

A formal Proxy Job may only read from a replica whose trust chain is
COMPLETE (P05/P07.1 evidence model, applied fail-closed here):

- the replica record exists and is VERIFIED;
- at least one PASS read-back evidence row points at a VERIFIED
  replica that BELONGS to this asset (dangling / cross-asset /
  unverified-replica evidence is a record, not a verification);
- the on-disk content's SHA256 matches the expected identity;
- when a device-identity provider is given, the replica's path
  resolves to a PHYSICAL device.

Any missing signal => DENIED. An admitted source authorizes proxy
ENCODING only: nothing in this module says a camera card is safe to
format (P05 `ReuseEligibility` contract; `unknown` failure domains
stay non-independent). The outcome + reason can be written to the
catalog's controlled, append-only evidence ledger
(`record_admission_evidence`).

Spec: docs/engineering/P11.1-safety-integration-review.md (gap G5).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from asset_schema import (
    Dit22Catalog,
    VerificationEvidence,
    asset_id_for_file,
)


class ProxySourceAdmissionError(Exception):
    """A formal proxy job's source failed the admission gate (or the
    gate's inputs were incomplete). No ffmpeg may run on a denied
    source."""


@dataclass(frozen=True)
class AdmissionDecision:
    """What the gate decided and why. `gates` is the full fail-closed
    matrix; `reason` is the first failing gate (or "admitted").

    Field surface is pinned: no authorization beyond `admitted` may be
    added here (no `safe_to_format` or the like — P05 S6)."""

    admitted: bool
    reason: str
    gates: dict = field(default_factory=dict)
    storage_id: str = ""
    replica_path: str = ""
    asset_id: str | None = None
    replica_id: str | None = None
    source_sha256: str | None = None
    fingerprint: str = ""


def _trusted_readback(
    catalog: Dit22Catalog, asset_id: str
) -> bool:
    """P07.1 trust-source rule (mirrors `reuse_eligibility`'s
    readback gate): a PASS evidence row is trusted ONLY when its
    `replica_id` references an existing VERIFIED replica that belongs
    to THIS asset."""
    reps = catalog.replicas_for(asset_id)
    verified_by_id = {r.replica_id: r for r in reps if r.verified}
    return any(
        e.verdict == "PASS"
        and e.replica_id is not None
        and e.replica_id in verified_by_id
        and verified_by_id[e.replica_id].asset_id == asset_id
        for e in catalog.evidence_for(asset_id)
    )


def _fingerprint(admitted: bool, reason: str, asset_id: str | None,
                 replica_id: str | None, storage_id: str,
                 replica_path: str) -> str:
    """Deterministic identity of this admission outcome; stored in the
    evidence ledger's `digest` so a re-recorded row is a no-op
    (P05.1 S5 append-only) while a changed outcome is a new row."""
    material = "|".join(
        ["admission-v1", "ADMITTED" if admitted else reason,
         asset_id or "-", replica_id or "-", storage_id, replica_path]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def admit_source(
    catalog: Dit22Catalog,
    storage_id: str,
    replica_path: str | Path,
    *,
    expected_sha256: str | None = None,
    device_provider=None,
) -> AdmissionDecision:
    """Fail-closed admission of `replica_path` (on `storage_id`) for
    formal proxy work. Returns the decision; the caller (proxy
    pipeline) raises `ProxySourceAdmissionError` on a denial — a
    denied source never reaches ffmpeg.

    Note on `expected_sha256`: the pipeline calls this gate without a
    caller-supplied hash, so the `sha_matches` gate is vacuously true
    there — content tamper is still caught transitively, because
    identity is content-derived (`asset_id_for_file`): any byte change
    moves the asset and breaks the replica-record link, denying the
    source. `expected_sha256` stays available for callers who carry a
    separately recorded hash (belt-and-braces pin).
    """
    replica_path_s = str(replica_path)
    p = Path(replica_path_s)

    gates: dict[str, bool | None] = {}

    if not p.is_file():
        gates["file_exists"] = False
        return AdmissionDecision(
            admitted=False, reason="file_exists", gates=gates,
            storage_id=storage_id, replica_path=replica_path_s,
            asset_id=None, replica_id=None, source_sha256=None,
            fingerprint=_fingerprint(False, "file_exists", None, None,
                                     storage_id, replica_path_s),
        )

    asset_id = asset_id_for_file(p)

    matching = [
        r for r in catalog.replicas_for(asset_id)
        if r.storage_id == storage_id and str(Path(r.path)) == str(p)
    ]
    gates["replica_recorded"] = bool(matching)
    gates["replica_verified"] = bool(matching) and all(r.verified for r in matching)

    if not matching:
        gates.update({"trusted_readback_evidence": None, "sha_matches": None,
                      "device_identity_trusted": None})
        return _deny(gates, "replica_recorded", asset_id, None,
                     storage_id, replica_path_s)
    if not all(r.verified for r in matching):
        gates.update({"trusted_readback_evidence": None, "sha_matches": None,
                      "device_identity_trusted": None})
        return _deny(gates, "replica_verified", asset_id,
                     matching[0].replica_id, storage_id, replica_path_s)

    gates["trusted_readback_evidence"] = _trusted_readback(catalog, asset_id)
    gates["sha_matches"] = (
        expected_sha256 is None or expected_sha256 == asset_id
    )
    if device_provider is not None:
        gates["device_identity_trusted"] = all(
            device_provider.identity_for(str(r.path)).is_physical for r in matching
        )
    else:
        gates["device_identity_trusted"] = None  # gate not in scope

    for name in (
        "replica_recorded",
        "replica_verified",
        "trusted_readback_evidence",
        "sha_matches",
        "device_identity_trusted",
    ):
        if gates.get(name) is False:
            return _deny(gates, name, asset_id, matching[0].replica_id,
                         storage_id, replica_path_s)

    return AdmissionDecision(
        admitted=True, reason="admitted", gates=gates,
        storage_id=storage_id, replica_path=replica_path_s,
        asset_id=asset_id, replica_id=matching[0].replica_id,
        source_sha256=asset_id,
        fingerprint=_fingerprint(True, "admitted", asset_id,
                                 matching[0].replica_id,
                                 storage_id, replica_path_s),
    )


def _deny(gates: dict, reason: str, asset_id: str | None,
          replica_id: str | None, storage_id: str,
          replica_path: str) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=False, reason=reason, gates=gates,
        storage_id=storage_id, replica_path=replica_path,
        asset_id=asset_id, replica_id=replica_id,
        source_sha256=asset_id,
        fingerprint=_fingerprint(False, reason, asset_id, replica_id,
                                 storage_id, replica_path),
    )


def record_admission_evidence(
    catalog: Dit22Catalog,
    decision: AdmissionDecision,
    *,
    job_id: str,
    evidence_id: str,
) -> None:
    """Write the gate outcome into the catalog's controlled, append-only
    evidence ledger (P04 S5 semantics). `file_name` namespaces the row
    under `admission/<job_id>`; the verdict is `ADMITTED` or
    `DENIED:<reason>` and the `digest` is the decision's fingerprint
    (an identical re-record is a no-op; a changed outcome is a new
    evidence_id, so the trail is never rewritten).

    A denial whose source file was missing has no asset identity to
    attribute the row to and is refused here (the job log carries it).
    """
    if decision.asset_id is None:
        raise ValueError(
            "no asset identity for this admission outcome — the source "
            "file was absent; record it in the job log, not the catalog"
        )
    verdict = "ADMITTED" if decision.admitted else f"DENIED:{decision.reason}"
    catalog.add_evidence(
        VerificationEvidence(
            evidence_id=evidence_id,
            asset_id=decision.asset_id,
            file_name=f"admission/{job_id}",
            algorithm="sha256-admission-gate",
            digest=decision.fingerprint,
            verdict=verdict,
        )
    )
