"""P07 fault-injection scenario builders for DIT 2.2 (deterministic, synthetic).

Every scenario builds a fully synthetic tree in a caller-provided temp dir.
No real media, no camera cards, no network, no A770. Each scenario carries
a *classification* (see `CLASSIFICATIONS`) so the resulting test report can
separate:

1. ENGINE_NATIVE      — behavior the upstream engine already supports
                       (re-verified by calling the engine directly where
                       the engine is importable in the test venv, or by
                       citing its own test suite otherwise).
2. DIT_ADAPTER_GUARD  — extra protection the DIT Adapter itself must add
                       (P04 contracts + P05.1 hardening).
3. MOCK_SIMULATION    — pure mock / simulation test (monkeypatched I/O).
4. HW_BLOCKED        — real hardware not present on this host; marked
                       BLOCKED, no fabricated result.

`false SAFE_TO_FORMAT` is a zero-tolerance defect: any scenario whose
expected verdict is "source stays" must never observe a source mutation.
"""

from __future__ import annotations

import hashlib
import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CLASSIFICATIONS = (
    "ENGINE_NATIVE",
    "DIT_ADAPTER_GUARD",
    "MOCK_SIMULATION",
    "HW_BLOCKED",
)


@dataclass(frozen=True)
class FaultScenario:
    name: str
    classification: str
    expected: str  # one-line expectation for the P07 matrix doc
    build: Callable[[Path], dict]  # build(root) -> scenario state (paths, etc.)


def _deterministic_bytes(n: int, seed: int) -> bytes:
    return random.Random(seed).randbytes(n)


def _make_card(root: Path, extra: list[str] | None = None) -> Path:
    """Synthetic camera card: DCIM/... with deterministic content.

    File naming: reel ``A001`` -> ``A0010101.A`` (single leading reel char,
    matching the real-card convention used across the P07 test suite).
    """
    card = root / "card"
    for i, reel in enumerate(["A001", "A002"] + (extra or [])):
        rel = card / "DCIM" / f"CAM_{reel}" / f"{reel}0101.A"
        rel.parent.mkdir(parents=True, exist_ok=True)
        rel.write_bytes(_deterministic_bytes(4096, seed=100 + i))
    zero = card / "DCIM" / "CAM_A001" / "zero-byte.A"
    zero.parent.mkdir(parents=True, exist_ok=True)
    zero.write_bytes(b"")
    return card


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── S1 source immutability / self-dest / symlink traversal ─────────


def build_source_is_destination(root: Path) -> dict:
    card = _make_card(root)
    return {"source": card, "destination": card}


def build_destination_inside_source(root: Path) -> dict:
    card = _make_card(root)
    dest = card / "archive_inside"
    dest.mkdir()
    return {"source": card, "destination": dest}


def build_symlink_traversal(root: Path) -> dict:
    card = _make_card(root)
    outside = root / "outside_secret"
    outside.mkdir()
    (outside / "secret.mov").write_bytes(_deterministic_bytes(2048, 77))
    link = card / "DCIM" / "CAM_A001" / "escape-link.mov"
    os.symlink(outside / "secret.mov", str(link))
    return {
        "source": card,
        "destination": root / "dest",
        "symlink": link,
        "outside_secret": outside / "secret.mov",
    }


# ── S2 independent failure domain (device identity) ───────────────


def build_two_paths_one_device(root: Path) -> dict:
    """Same physical device reached by two different mount paths.

    On this host we cannot fabricate a second mount point of one real disk
    cheaply; the *scenario state* records what an adapter must check
    (device serial / volume identity) and the test asserts the contract,
    not a real device. Classification: the *contract* is DIT_ADAPTER_GUARD;
    exercising a real second mount is HW_BLOCKED.
    """
    card = _make_card(root)
    dest_a = root / "mount_a"
    dest_b = root / "mount_b"
    dest_a.mkdir()
    dest_b.mkdir()
    return {
        "source": card,
        "dest_a": dest_a,
        "dest_b": dest_b,
        "device_serial_same": "VOLSER-12345",  # what a real probe would report
    }


def build_two_nas_shares(root: Path) -> dict:
    """Two NAS shares on the same appliance = one failure domain."""
    card = _make_card(root)
    share1 = root / "nas" / "share1"
    share2 = root / "nas" / "share2"
    share1.mkdir(parents=True)
    share2.mkdir(parents=True)
    return {
        "source": card,
        "dest_a": share1,
        "dest_b": share2,
        "nas_appliance_same": "appliance-serial-X",
    }


# ── S3/S4 write interruption, disk full, kill, resume ─────────────


def build_destination_write_interrupt(root: Path) -> dict:
    """Simulate a copy that dies mid-file: partial file left behind."""
    card = _make_card(root)
    dest = root / "dest"
    dest.mkdir()
    target = dest / "DCIM" / "CAM_A001" / "A0010101.A"
    target.parent.mkdir(parents=True, exist_ok=True)
    full = _deterministic_bytes(4096, 100)
    target.write_bytes(full[:1024])  # 1/4 written, rest missing
    return {
        "source": card,
        "destination": dest,
        "partial": target,
        "expected_size": len(full),
    }


def build_disk_full(root: Path) -> dict:
    """Mock: destination reports no free space before the first media byte."""
    card = _make_card(root)
    dest = root / "dest_full"
    dest.mkdir()
    return {
        "source": card,
        "destination": dest,
        "free_bytes": 0,  # what statvfs would report on a full disk
    }


def build_process_kill_resume(root: Path) -> dict:
    """A checkpoint DB the process left behind; resume must converge."""
    card = _make_card(root)
    dest = root / "dest"
    dest.mkdir()
    ckpt = root / "resume" / "checkpoint.json"
    ckpt.parent.mkdir()
    ckpt.write_text(
        '{"job": "j1", "phase": "copy", "done": ["DCIM/CAM_A001/A0010101.A"]}'
    )
    return {"source": card, "destination": dest, "checkpoint": ckpt}


# ── source replaced between pre-read and copy-read ────────────────


def build_source_replaced_midrun(root: Path) -> dict:
    card = _make_card(root)
    f = card / "DCIM" / "CAM_A001" / "A0010101.A"
    pre = _sha256(f)
    f.write_bytes(_deterministic_bytes(4096, 999))  # attacker swap
    post = _sha256(f)
    return {"source": card, "pre_digest": pre, "post_digest": post}


# ── re-run must not damage a good verified replica ───────────────


def build_rerun_with_verified_replica(root: Path) -> dict:
    card = _make_card(root)
    good = root / "verified_replica"
    for p in card.rglob("*.A"):
        rel = p.relative_to(card)
        if rel.name == "zero-byte.A":
            continue
        target = good / "DCIM" / rel.parent.name / rel.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    return {"source": card, "good_replica": good}


# ── device identity change on reconnect ───────────────────────────


def build_device_reconnect_identity_change(root: Path) -> dict:
    return {
        "old_identity": {"serial": "VOLSER-12345", "key": "win-volume:12345:VOLSER-12345"},
        "new_identity": {"serial": "VOLSER-98765", "key": "win-volume:98765:VOLSER-98765"},
        "note": "card ejected and a different card inserted in the same reader",
    }


# ── ASC MHL tamper ─────────────────────────────────────────────────


def build_mhl_tamper(root: Path) -> dict:
    """A manifest whose digest no longer matches the on-disk file."""
    card = _make_card(root)
    mhl = root / "ascmhl"
    mhl.mkdir()
    manifest = mhl / "mhl-gen1.xml"
    real = _deterministic_bytes(512, 5)
    (mhl / "file.bin").write_bytes(real)
    bad_digest = "0" * 64  # NOT the real digest → chain must fail
    manifest.write_text(
        f"<hashlist xmlns='urn:ASC:MHL:v2.0'><hashes>"
        f"<file name='file.bin' checksumAlgorithm='SHA256' value='{bad_digest}'/></hashes>"
        f"</hashlist>"
    )
    return {"source": card, "manifest": manifest, "real_file": mhl / "file.bin"}


# ── 0-byte / Unicode / case collision / Windows reserved names ───


def build_edge_names(root: Path) -> dict:
    card = _make_card(root, extra=["A003"])
    names = {
        "zero_byte": card / "DCIM" / "CAM_A001" / "zero-byte.A",
        "unicode_cjk_kr": card / "DCIM" / "CAM_A001" / "影像_영화_映像.A",
        "emoji_long": card / "DCIM" / "CAM_A001" / ("clip_" + "🎬" * 20 + ".A"),
        "case_dup_upper": card / "DCIM" / "CAM_A001" / "A0010101.B",
        "case_dup_lower": card / "DCIM" / "CAM_A001" / "a0010101.b",
        "windows_reserved_con": card / "DCIM" / "CAM_A001" / "CON",
        "windows_reserved_prn": card / "DCIM" / "CAM_A001" / "PRN.A",
    }
    for n, p in names.items():
        if n == "zero_byte":
            continue  # already exists as b""
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_deterministic_bytes(1024, seed=500 + len(n)))
    return {"card": card, "names": {k: str(v) for k, v in names.items()}}


# ── forged safety flags / missing readback evidence ───────────────


def build_forged_verified_flag(root: Path) -> dict:
    """A replica row claiming verified=True with NO readback evidence."""
    return {"asset_sha": "ab" * 32, "forged_verified": True, "readback_evidence": None}


def build_forged_failure_domain(root: Path) -> dict:
    """A replica claiming an independent domain it cannot prove."""
    return {"asset_sha": "cd" * 32, "forged_domain": "fd-claims-independent", "proof": None}


def build_missing_readback(root: Path) -> dict:
    return {"asset_sha": "ef" * 32, "replicas": 2, "readback_evidence": None}


SCENARIOS: list[FaultScenario] = [
    FaultScenario("S1 source==destination", "DIT_ADAPTER_GUARD",
                  "rejected before any write; source untouched",
                  build_source_is_destination),
    FaultScenario("S1 destination inside source", "DIT_ADAPTER_GUARD",
                  "rejected (UnsafeDestination); source untouched",
                  build_destination_inside_source),
    FaultScenario("S1 symlink traversal", "MOCK_SIMULATION",
                  "symlink skipped/never followed; outside file intact",
                  build_symlink_traversal),
    FaultScenario("S2 two paths one device", "DIT_ADAPTER_GUARD",
                  "same device serial → NOT counted independent (contract)",
                  build_two_paths_one_device),
    FaultScenario("S2 two NAS shares one appliance", "HW_BLOCKED",
                  "real SMB/NAS share identity unavailable on host; contract-only",
                  build_two_nas_shares),
    FaultScenario("S3 destination write interrupted", "MOCK_SIMULATION",
                  "partial file detected; resume or discard; no false verified",
                  build_destination_write_interrupt),
    FaultScenario("S3 disk full", "MOCK_SIMULATION",
                  "fail before first media byte (preflight); no verdict issued",
                  build_disk_full),
    FaultScenario("S4 process kill + resume", "MOCK_SIMULATION",
                  "checkpoint re-entry converges to same verified replica",
                  build_process_kill_resume),
    FaultScenario("S1 source replaced between pre-read and copy-read", "MOCK_SIMULATION",
                  "digest drift detected → FAILED, no verified replica",
                  build_source_replaced_midrun),
    FaultScenario("S4 re-run with verified replica present", "ENGINE_NATIVE",
                  "previous good copy untouched on failure (offloader regression test)",
                  build_rerun_with_verified_replica),
    FaultScenario("S2 device identity change on reconnect", "HW_BLOCKED",
                  "different serial on same reader → not the same card; untestable here",
                  build_device_reconnect_identity_change),
    FaultScenario("S5 ASC MHL manifest tamper", "ENGINE_NATIVE",
                  "digest mismatch → chain verification fails (offloader ascmhl)",
                  build_mhl_tamper),
    FaultScenario("S7 edge names: 0-byte/Unicode/case/Windows-reserved", "MOCK_SIMULATION",
                  "0-byte flagged; Unicode roundtrip; case collision deduped; "
                  "Windows reserved name is a documented gap (offloader MISSING)",
                  build_edge_names),
    FaultScenario("S6 forged verified flag, no readback", "DIT_ADAPTER_GUARD",
                  "reuse gate BLOCKED: readback_evidence gate fails",
                  build_forged_verified_flag),
    FaultScenario("S6 forged failure_domain, no proof", "DIT_ADAPTER_GUARD",
                  "untrusted domain → BLOCKED",
                  build_forged_failure_domain),
    FaultScenario("S6 missing readback evidence", "DIT_ADAPTER_GUARD",
                  "BLOCKED despite two replicas",
                  build_missing_readback),
]


def run_all(root: Path) -> dict[str, dict]:
    """Build every scenario under `root`; returns {name: state}."""
    out: dict[str, dict] = {}
    for i, sc in enumerate(SCENARIOS):
        out[sc.name] = sc.build(root / f"case{i:02d}")
    return out
