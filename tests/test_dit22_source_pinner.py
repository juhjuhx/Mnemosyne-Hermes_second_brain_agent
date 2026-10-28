"""P12.2-B (Phase 4 C1/C2): the Source Identity Pinner — RED negative tests.

The pinner is the single cross-pipeline drift truth source. It must
fail closed on every path by which the bytes ffmpeg reads could stop
being the bytes that Admission verified. A pre-execution SHA alone is
explicitly NOT sufficient: verification re-hashes on demand.

Run: pytest tests/test_dit22_source_pinner.py -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "mnemosyne_dit"))

from source_pinner import (
    SourceDriftError,
    SourcePin,
    pin_from_admission,
    verify_pin,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def pin_env(tmp_path: Path):
    """A verified source file + a pin against it, on a tmp volume."""
    src = tmp_path / "reel_001.mxf"
    src.write_bytes(b"\x00" * 4096)
    sha = _sha(b"\x00" * 4096)
    pin = SourcePin(
        expected_sha256=sha,
        source_path=str(src),
        source_size_bytes=4096,
        asset_id=sha,
        replica_id="rep-1",
        storage_id="sd-local",
        manifest_digest=None,
        job_id="job-x",
    )
    return src, pin


def test_s1_clean_pin_verifies(pin_env):
    _src, pin = pin_env
    outcome = verify_pin(pin)
    assert outcome.ok is True
    assert outcome.current_sha256 == pin.expected_sha256
    assert outcome.current_size_bytes == 4096


def test_s2_source_mutated_after_admission_fails_closed(pin_env):
    # C1 TOCTOU window: someone rewrites the replica after Admission.
    src, pin = pin_env
    src.write_bytes(b"\x01" * 4096)
    with pytest.raises(SourceDriftError):
        verify_pin(pin)


def test_s3_file_replaced_at_same_path_fails_closed(pin_env):
    # A different file, same path, different size + content:
    src, pin = pin_env
    src.unlink()
    src.write_bytes(b"swap-in material")
    with pytest.raises(SourceDriftError):
        verify_pin(pin)


def test_s4_source_disappeared_fails_closed(pin_env):
    # Device pulled / file gone: no hash can be taken.
    src, pin = pin_env
    src.unlink()
    with pytest.raises(SourceDriftError):
        verify_pin(pin)


def test_s5_size_only_drift_caught():
    # Same content prefix, different length: the cheap pre-filter must
    # catch it without even waiting for the hash mismatch.
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"A" * 1000)
        path = f.name
    pin = SourcePin(
        expected_sha256=_sha(b"A" * 1000),
        source_path=path,
        source_size_bytes=1000,
        asset_id=_sha(b"A" * 1000),
        replica_id="rep",
        storage_id="s",
        manifest_digest=None,
        job_id="j",
    )
    with open(path, "ab") as f:
        f.write(b"B")
    try:
        with pytest.raises(SourceDriftError):
            verify_pin(pin)
    finally:
        Path(path).unlink(missing_ok=True)


def test_s6_manifest_drift_fails_closed(pin_env):
    # C2: the queue's input_manifest digest is the drift truth source;
    # a pin built with a different manifest is a mismatch, even when
    # the file bytes are fine.
    src, pin = pin_env
    other_manifest = {"file": str(src), "sha256": _sha(b"\x00" * 4096)}
    digest = hashlib.sha256(
        json.dumps(other_manifest, sort_keys=True).encode()
    ).hexdigest()
    pin = SourcePin(
        expected_sha256=pin.expected_sha256,
        source_path=str(src),
        source_size_bytes=4096,
        asset_id=pin.asset_id,
        replica_id=pin.replica_id,
        storage_id=pin.storage_id,
        manifest_digest=digest,
        job_id="job-x",
    )
    with pytest.raises(SourceDriftError):
        verify_pin(pin, actual_manifest=other_manifest | {"sha256": "deadbeef"})


def test_s7_pin_built_from_admission_decision(tmp_path: Path):
    # pin_from_admission carries the trust-chain identifiers onto the
    # pin (asset/replica/storage + the admitted content identity), and
    # re-checks the replica's trust at pin time.
    from asset_schema import (
        AssetPathObservation,
        Dit22Catalog,
        MediaAsset,
        Replica,
        VerificationEvidence,
    )

    cat = Dit22Catalog(tmp_path / "cat.db")
    data = b"admitted-bytes"
    aid = _sha(data)
    cat.upsert_asset(MediaAsset(source_sha256=aid))
    p = tmp_path / "clip.mov"
    p.write_bytes(data)
    cat.add_observation(
        AssetPathObservation(aid, "sd1", str(p), p.stat().st_size)
    )
    cat.add_replica(Replica("rep-a", aid, "sd1", "card", str(p), verified=True))
    cat.add_evidence(
        VerificationEvidence(
            evidence_id="ev-1",
            asset_id=aid,
            file_name=p.name,
            algorithm="sha256",
            digest=aid,
            verdict="PASS",
            replica_id="rep-a",
        )
    )
    from source_admission import admit_source

    decision = admit_source(cat, "sd1", p)
    assert decision.admitted is True
    pin = pin_from_admission(decision, catalog=cat)
    assert pin.expected_sha256 == aid
    assert pin.asset_id == aid
    assert pin.replica_id == "rep-a"
    assert pin.storage_id == "sd1"
    assert pin.source_size_bytes == p.stat().st_size
    assert verify_pin(pin).ok


def test_s8_replica_mismatch_pin_rejected(tmp_path: Path):
    # A pin whose replica does not belong to the asset (re-registered
    # against another asset) is untrusted: the pinner refuses to build
    # it (fail-closed, before any encoding).
    from asset_schema import (
        AssetPathObservation,
        Dit22Catalog,
        MediaAsset,
        Replica,
        VerificationEvidence,
    )

    cat = Dit22Catalog(tmp_path / "cat.db")
    data = b"pin-rep"
    aid = _sha(data)
    cat.upsert_asset(MediaAsset(source_sha256=aid))
    p = tmp_path / "c.mov"
    p.write_bytes(data)
    cat.add_observation(AssetPathObservation(aid, "sd1", str(p), p.stat().st_size))
    cat.add_replica(
        Replica("rep-other", "other-asset-id", "sd1", "card", str(p),
                verified=True)
    )
    cat.add_evidence(
        VerificationEvidence(
            evidence_id="ev", asset_id=aid, file_name=p.name,
            algorithm="sha256", digest=aid, verdict="PASS",
            replica_id="rep-other",
        )
    )

    class _FakeDecision:
        admitted = True
        asset_id = aid
        replica_id = "rep-other"
        storage_id = "sd1"
        replica_path = str(p)
        source_sha256 = aid

    with pytest.raises(SourceDriftError):
        pin_from_admission(_FakeDecision(), catalog=cat)
