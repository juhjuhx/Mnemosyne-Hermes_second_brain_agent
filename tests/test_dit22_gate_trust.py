"""P07.1 trust-source hardening of the DIT 2.2 reuse gate.

The P05.1 `reuse_eligibility()` counted any stored row with the string
`verdict == "PASS"` and a non-null `replica_id` as "readback evidence".
That conflates two different things (user P07.1 item 2):

  * a **stored evidence record** — a row that exists in the DB with a
    PASS string, and
  * a **trustable actual verification** — evidence that is *bound to a
    real, verified, same-asset replica*.

A dangling / wrong / unverified `replica_id` must NOT be trusted. P07.1
tightens the gate so `readback_evidence` only counts PASS evidence whose
referenced replica (a) exists, (b) belongs to this asset, and (c) is
itself verified.

It also adds an **injectable device-identity provider** (item 4) so the
"same physical device reached by two mount paths" case is decided by a
real identity probe (fake-injected here; real hardware stays BLOCKED)
rather than by comparing two strings.

All synthetic; no camera card, no NAS, no A770, no cloud.
"""

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from asset_schema import (
    DeviceIdentity,
    Dit22Catalog,
    MediaAsset,
    Replica,
    StaticDeviceIdentityProvider,
    VerificationEvidence,
)


def _aid(seed: int) -> str:
    return (seed.to_bytes(32, "big")).hex()


def _cat(tmp_path: Path, seed: int) -> Dit22Catalog:
    db = tmp_path / f"p071_{seed:02x}"
    db.mkdir(parents=True, exist_ok=True)
    cat = Dit22Catalog(db / "gate.db")
    cat.upsert_asset(MediaAsset(source_sha256=_aid(seed)))
    return cat


# ── item 1 / item 2: trust-source negative cases ───────────────────


@pytest.mark.behavior_tested
def test_dangling_replica_evidence_is_not_trusted_readback(tmp_path):
    """A PASS evidence row pointing at a replica_id that does not exist
    must NOT count as readback (was the false-safe gap)."""
    aid = _aid(0x71)
    cat = _cat(tmp_path, 0x71)
    try:
        cat.add_replica(Replica("r1", aid, "s1", "fd-1", "/a", verified=True))
        # Evidence references a ghost replica that was never registered.
        cat.add_evidence(
            VerificationEvidence("e-ghost", aid, "ghost.mov", "sha256",
                                 "11" * 32, "dev1", "PASS", replica_id="ghost")
        )
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is False, "dangling replica must not be trusted"
        assert gate.gates["readback_evidence"] is False
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_zero_replicas_with_pass_evidence_blocked(tmp_path):
    """PASS evidence with no replicas at all is a stored record, not a
    verified chain — BLOCKED."""
    aid = _aid(0x72)
    cat = _cat(tmp_path, 0x72)
    try:
        cat.add_evidence(
            VerificationEvidence("e1", aid, "x.mov", "sha256", "ab" * 32,
                                 "dev", "PASS", replica_id="rX")
        )
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is False
        assert gate.gates["readback_evidence"] is False
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_evidence_bound_to_unverified_replica_not_trusted(tmp_path):
    """A PASS evidence bound to an UNverified replica is not readback of a
    verified copy."""
    aid = _aid(0x73)
    cat = _cat(tmp_path, 0x73)
    try:
        cat.add_replica(Replica("r-unverified", aid, "s1", "fd-1", "/a",
                                verified=False))
        cat.add_evidence(
            VerificationEvidence("e1", aid, "a.mov", "sha256", "11" * 32,
                                 "dev1", "PASS", replica_id="r-unverified")
        )
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is False, "unverified replica's PASS is not trusted"
        assert gate.gates["readback_evidence"] is False
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_evidence_pointing_to_wrong_asset_replica_not_trusted(tmp_path):
    """Evidence for asset A that references asset B's replica must not grant
    readback to A."""
    a, b = _aid(0x74), _aid(0x75)
    cat = _cat(tmp_path, 0x74)
    try:
        cat.upsert_asset(MediaAsset(source_sha256=b))
        cat.add_replica(Replica("r-b", b, "s2", "fd-2", "/b", verified=True))
        # Evidence recorded against asset A but bound to B's replica:
        cat.add_evidence(
            VerificationEvidence("e-cross", a, "b.mov", "sha256", "22" * 32,
                                 "dev2", "PASS", replica_id="r-b")
        )
        gate = cat.reuse_eligibility(a)
        assert gate.is_eligible is False, "cross-asset replica is not A's readback"
        assert gate.gates["readback_evidence"] is False
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_single_verified_replica_readback_eligible_but_not_independent(tmp_path):
    """A single verified replica with its own bound PASS readback clears the
    *reuse* gate, but must NOT be counted as a second independent backup.
    This pins the single-replica nuance without claiming redundancy."""
    aid = _aid(0x76)
    cat = _cat(tmp_path, 0x76)
    try:
        cat.add_replica(Replica("r1", aid, "s1", "fd-1", "/a", verified=True))
        cat.add_evidence(
            VerificationEvidence("e1", aid, "a.mov", "sha256", "11" * 32,
                                 "dev1", "PASS", replica_id="r1")
        )
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is True, "single verified replica + bound readback"
        # ... but it is not a double backup:
        assert cat.independent_replicas(aid) == 1
    finally:
        cat.close()


# ── item 4: injectable fake device-identity provider ───────────────


def _provider(paths_to_same_device: dict[str, DeviceIdentity]) -> StaticDeviceIdentityProvider:
    return StaticDeviceIdentityProvider(paths_to_same_device)


@pytest.mark.behavior_tested
def test_same_device_two_paths_collapse_via_provider(tmp_path):
    """Two mount paths that the (fake) device-identity provider reports as
    ONE physical device must collapse to a single domain — this is a
    behavior test through the provider, not a string/path comparison."""
    aid = _aid(0x77)
    cat = _cat(tmp_path, 0x77)
    prov = _provider({
        "/mnt/sdcard/a": DeviceIdentity("VOLSER-1", True, "removable"),
        "/Volumes/MediaCard": DeviceIdentity("VOLSER-1", True, "removable"),
    })
    try:
        cat.add_replica(Replica("r-a", aid, "s-a", "VOLSER-1", "/mnt/sdcard/a", verified=True))
        cat.add_replica(Replica("r-b", aid, "s-b", "VOLSER-1", "/Volumes/MediaCard", verified=True))
        assert cat.independent_domains(aid, prov) == 1, "same device => one domain"
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_two_distinct_devices_counted_independent_via_provider(tmp_path):
    aid = _aid(0x78)
    cat = _cat(tmp_path, 0x78)
    prov = _provider({
        "/dev/nvme1n1p1": DeviceIdentity("SER-AAA", True, "ssd"),
        "/mnt/nas/share": DeviceIdentity("SER-BBB", True, "disk"),
    })
    try:
        cat.add_replica(Replica("r1", aid, "s1", "SER-AAA", "/dev/nvme1n1p1", verified=True))
        cat.add_replica(Replica("r2", aid, "s2", "SER-BBB", "/mnt/nas/share", verified=True))
        assert cat.independent_domains(aid, prov) == 2
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_network_share_not_physical_collapses_to_zero(tmp_path):
    """A destination the provider marks non-physical (SMB/NAS share) must NOT
    contribute to the independent-physical-domain count."""
    aid = _aid(0x79)
    cat = _cat(tmp_path, 0x79)
    prov = _provider({
        "//nas/share1": DeviceIdentity("NAS-X", False, "network"),
    })
    try:
        cat.add_replica(Replica("r1", aid, "s1", "NAS-X", "//nas/share1", verified=True))
        assert cat.independent_domains(aid, prov) == 0, "network share is non-physical"
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_untrusted_device_blocks_reuse_when_provider_given(tmp_path):
    """With a provider, a verified replica on a non-physical (network) device
    fails the device-identity gate → BLOCKED even with valid readback."""
    aid = _aid(0x7A)
    cat = _cat(tmp_path, 0x7A)
    prov = _provider({
        "//nas/share": DeviceIdentity("NAS-X", False, "network"),
    })
    try:
        cat.add_replica(Replica("r1", aid, "s1", "NAS-X", "//nas/share", verified=True))
        cat.add_evidence(
            VerificationEvidence("e1", aid, "a.mov", "sha256", "11" * 32,
                                 "dev", "PASS", replica_id="r1")
        )
        gate = cat.reuse_eligibility(aid, provider=prov)
        assert gate.is_eligible is False
        assert gate.gates.get("device_identity_trusted") is False
    finally:
        cat.close()
