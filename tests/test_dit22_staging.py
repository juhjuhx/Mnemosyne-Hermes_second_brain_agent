"""P08 staging atomic commit — contract tests for `staging.StagedArchive`.

Covers the P08 spec (docs/engineering/spec/P08-staging-atomic-commit.md):
mirror/RAID1 semantics (availability, NOT backup), staging→hash→commit
state machine, fail-closed crash recovery, idempotent re-entry, receipt
tamper detection, and independence reporting through an injected
device-identity provider (P07.1 machinery).

All synthetic. Real NAS/ZFS/SMB/power-loss stays @hw_blocked.
"""

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from asset_schema import (
    DeviceIdentity,
    StaticDeviceIdentityProvider,
)
from staging import (
    StagedArchive,
    StagingConflictError,
)


def _prov(mapping: dict[str, DeviceIdentity]) -> StaticDeviceIdentityProvider:
    return StaticDeviceIdentityProvider(mapping)


# ── happy path ──────────────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_stage_verify_commit_exposes_complete_archive(tmp_path):
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job1", st, tgt)
    arch.stage({"A001/A0010101.A": b"footage-1", "A002/A0020101.A": b"footage-2"})
    manifest = arch.verify_manifest()
    assert set(manifest) == {"A001/A0010101.A", "A002/A0020101.A"}
    assert arch.commit() is True
    # Target now holds byte-identical files + a receipt:
    assert (tgt / "A001/A0010101.A").read_bytes() == b"footage-1"
    assert (tgt / "receipt.json").exists()
    assert arch.recovery_state() == "COMMITTED"


@pytest.mark.behavior_tested
def test_partial_staging_never_exposed_in_target(tmp_path):
    """Crash-during-copy zero-tolerance: before commit, target must NOT
    contain the archive (no partial exposure to the processing queue)."""
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job-partial", st, tgt)
    arch.stage({"A001/A0010101.A": b"footage"})
    arch.verify_manifest()
    # Simulated crash: commit never ran.
    assert not tgt.exists() or not (tgt / "A001/A0010101.A").exists()
    assert arch.recovery_state() in ("INTERRUPTED", "BLOCKED", "CLEAN")


# ── crash recovery / resume ─────────────────────────────────────────


@pytest.mark.behavior_tested
def test_crash_resume_rehashes_and_commits(tmp_path):
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job-resume", st, tgt)
    arch.stage({"clip.mov": b"payload-123"})
    arch.verify_manifest()
    # "Process dies" — a NEW archive object re-enters the same paths:
    arch2 = StagedArchive("job-resume", st, tgt)
    assert arch2.recovery_state() == "INTERRUPTED"
    assert arch2.resume() is True
    assert (tgt / "clip.mov").read_bytes() == b"payload-123"
    assert arch2.recovery_state() == "COMMITTED"


@pytest.mark.behavior_tested
def test_resumed_staged_file_tampered_blocks_commit(tmp_path):
    """Any re-hash mismatch => BLOCKED; the archive is never exposed
    (fail-closed, zero-tolerance false-commit)."""
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job-tamper", st, tgt)
    arch.stage({"clip.mov": b"original"})
    arch.verify_manifest()
    (st / "clip.mov").write_bytes(b"TAMPERED")
    arch2 = StagedArchive("job-tamper", st, tgt)
    assert arch2.resume() is False
    assert arch2.recovery_state() == "BLOCKED"
    assert not (tgt / "clip.mov").exists()


@pytest.mark.behavior_tested
def test_receipt_tamper_blocks_reentry(tmp_path):
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job-rct", st, tgt)
    arch.stage({"a.bin": b"aa"})
    arch.verify_manifest()
    arch.commit()
    # Attacker flips the receipt manifest entry:
    import json

    receipt = json.loads((tgt / "receipt.json").read_text())
    receipt["manifest"]["a.bin"] = "0" * 64
    (tgt / "receipt.json").write_text(json.dumps(receipt))
    arch2 = StagedArchive("job-rct", st, tgt)
    with pytest.raises(StagingConflictError):
        arch2.reentry_check()
    assert arch2.recovery_state() == "BLOCKED"


# ── idempotent re-entry ─────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_commit_is_idempotent_noop(tmp_path):
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job-idem", st, tgt)
    arch.stage({"a.bin": b"1"})
    arch.verify_manifest()
    assert arch.commit() is True
    # Re-commit with the same receipt: no rewrite, no error, still COMMITTED.
    arch2 = StagedArchive("job-idem", st, tgt)
    arch2.reentry_check()  # must not raise
    assert arch2.recovery_state() == "COMMITTED"


@pytest.mark.behavior_tested
def test_discard_returns_to_clean(tmp_path):
    st = tmp_path / "staging"
    tgt = tmp_path / "target"
    arch = StagedArchive("job-disc", st, tgt)
    arch.stage({"a.bin": b"x"})
    arch.discard()
    assert not st.exists() or not any(st.rglob("*"))
    assert arch.recovery_state() == "CLEAN"


# ── mirror/RAID1: availability, NOT backup (F13) ───────────────────


@pytest.mark.behavior_tested
def test_two_mounts_one_device_fold_to_single_domain(tmp_path):
    arch = StagedArchive("job-mirror", tmp_path / "s", tmp_path / "t")
    arch.register_destination("/mnt/sdcard/a")
    arch.register_destination("/Volumes/MediaCard")
    prov = _prov({
        "/mnt/sdcard/a": DeviceIdentity("VOLSER-1", True, "removable"),
        "/Volumes/MediaCard": DeviceIdentity("VOLSER-1", True, "removable"),
    })
    rep = arch.independence_report(prov)
    assert rep["independent_backup_count"] == 1
    assert rep["domains"] == ["VOLSER-1"]
    assert rep["mirror_note"] == "availability, not backup"


@pytest.mark.behavior_tested
def test_two_distinct_physical_devices_count_as_two_backups(tmp_path):
    arch = StagedArchive("job-two", tmp_path / "s", tmp_path / "t")
    arch.register_destination("/dev/nvme1n1p1")
    arch.register_destination("/mnt/backup-card")
    prov = _prov({
        "/dev/nvme1n1p1": DeviceIdentity("SER-A", True, "ssd"),
        "/mnt/backup-card": DeviceIdentity("SER-B", True, "removable"),
    })
    rep = arch.independence_report(prov)
    assert rep["independent_backup_count"] == 2
    assert set(rep["domains"]) == {"SER-A", "SER-B"}


@pytest.mark.behavior_tested
def test_network_share_and_unlisted_paths_never_count(tmp_path):
    arch = StagedArchive("job-net", tmp_path / "s", tmp_path / "t")
    arch.register_destination("//nas/share")
    arch.register_destination("/mnt/unknown-thing")
    arch.register_destination("/dev/backup-disk")
    prov = _prov({
        "//nas/share": DeviceIdentity("NAS-1", False, "network"),
        "/dev/backup-disk": DeviceIdentity("SER-B", True, "ssd"),
        # /mnt/unknown-thing intentionally absent -> fail-closed unknown
    })
    rep = arch.independence_report(prov)
    assert rep["independent_backup_count"] == 1
    assert rep["domains"] == ["SER-B"]


# ── hardware-blocked scenario (contract asserts only) ──────────────


@pytest.mark.hw_blocked
def test_real_zfs_snapshot_restore_drill_is_contract_only(tmp_path):
    """ZFS snapshot/replication/restore drill requires a real appliance.
    We record the drill CONTRACT (inputs/expected outputs) but assert no
    real result — the scenario state is inspectable, nothing is fabricated."""
    contract = {
        "inputs": ["zfs snapshot @pre-offload", "replication stream", "restore target"],
        "expected": ["restored tree hash == pre-offload manifest", "RPO=0 for committed archive"],
        "status": "HARDWARE_BLOCKED",
        "result": None,
    }
    state = tmp_path / "zfs_drill_contract.json"
    state.write_text(json.dumps(contract))
    loaded = json.loads(state.read_text())
    assert loaded["status"] == "HARDWARE_BLOCKED"
    assert loaded["result"] is None, "no fabricated restore result"
