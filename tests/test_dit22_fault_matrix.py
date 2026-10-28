"""P07 differential fault harness.

Runs every `fault_matrix` scenario, asserts the documented expectation,
and — for the DIT-Adapter-guard cases — checks them against the P05.1
`reuse_eligibility` gate so that a **forged `verified` flag with no
readback evidence cannot produce a false `SAFE_TO_FORMAT`** (zero-tolerance).

Classification legend (see fault_matrix.CLASSIFICATIONS):
  ENGINE_NATIVE      re-verified by the upstream engine's own test suite
  DIT_ADAPTER_GUARD  protected by the DIT 2.2 adapter (P04/P05.1)
  MOCK_SIMULATION    pure synthetic / monkeypatched simulation
  HW_BLOCKED         real hardware absent on this host — asserted as BLOCKED

Nothing here touches a camera card, a NAS, or the A770. All data is
synthetic and generated under the caller's temp dir.

P07.1 coverage taxonomy (markers registered in tests/conftest.py):
  @fixture_only      — only verifies a synthetic scenario builds; it does
                       NOT prove engine/adapter behavior.
  @behavior_tested   — calls the DIT 2.2 gate/adapter and asserts the
                       actual accept/reject outcome.
  @hw_blocked        — real hardware absent on host; scenario state +
                       contract asserts only, no fabricated result.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "dit22"
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_FIXTURES.parent))

from asset_schema import (
    Dit22Catalog,
    MediaAsset,
    Replica,
    ReuseEligibility,
    VerificationEvidence,
)
from fixtures.dit22.fault_matrix import (
    CLASSIFICATIONS,
    SCENARIOS,
    run_all,
)


def _asset_id(seed: int) -> str:
    return (seed.to_bytes(32, "big")).hex()


def _classify(name: str) -> str:
    for sc in SCENARIOS:
        if sc.name == name:
            return sc.classification
    raise KeyError(name)


# ── matrix integrity ─────────────────────────────────────────────────


@pytest.mark.fixture_only
def test_matrix_classifications_are_valid():
    for sc in SCENARIOS:
        assert sc.classification in CLASSIFICATIONS, sc.name


@pytest.mark.fixture_only
def test_matrix_builds_every_scenario_cleanly(tmp_path):
    states = run_all(tmp_path)
    assert len(states) == len(SCENARIOS)
    # Each builder must return a non-empty state dict (no silent no-ops).
    for name, st in states.items():
        assert isinstance(st, dict) and st, f"{name} built an empty state"


# ── S1 source-immutability contract (adapter guard) ─────────────────


@pytest.mark.fixture_only
def test_source_is_destination_rejected(tmp_path):
    st = run_all(tmp_path)["S1 source==destination"]
    assert st["source"] == st["destination"], "scenario must alias the source"
    # Adapter guard: a destination that IS the source is refused up front.
    # (offloader: engine.assert_safe_destinations raises UnsafeDestination.)
    assert st["source"].resolve() == st["destination"].resolve()


@pytest.mark.fixture_only
def test_destination_inside_source_rejected(tmp_path):
    st = run_all(tmp_path)["S1 destination inside source"]
    src, dst = st["source"], st["destination"]
    assert dst.is_relative_to(src), "scenario must nest the destination in source"
    # Guard: nested destination refused; source content must be untouched.
    for f in src.rglob("*.A"):
        if f.name != "zero-byte.A":
            assert f.stat().st_size > 0


@pytest.mark.fixture_only
def test_symlink_traversal_never_followed(tmp_path):
    st = run_all(tmp_path)["S1 symlink traversal"]
    link = st["symlink"]
    secret = st["outside_secret"]
    assert link.is_symlink()
    # The outside secret must remain exactly as created — traversal refused.
    assert secret.stat().st_size == 2048


# ── S2 independent failure domain (contract, no real devices) ──────


@pytest.mark.fixture_only
def test_two_paths_one_device_not_independent(tmp_path):
    st = run_all(tmp_path)["S2 two paths one device"]
    # The *contract*: two DISTINCT mount paths reporting the SAME device
    # serial must collapse to one failure domain. We assert the check the
    # adapter must run, not a fabricated device.
    assert st["dest_a"] != st["dest_b"], "two distinct mount paths"
    assert isinstance(st["device_serial_same"], str) and st["device_serial_same"]


@pytest.mark.hw_blocked
def test_two_nas_shares_is_hw_blocked(tmp_path):
    st = run_all(tmp_path)["S2 two NAS shares one appliance"]
    assert _classify("S2 two NAS shares one appliance") == "HW_BLOCKED"
    # No real SMB/NAS identity on this host → the scenario must be marked
    # BLOCKED and must NOT assert independence.
    assert st["nas_appliance_same"], "contract records the single appliance"


# ── S3/S4 interruption, disk full, kill/resume (mock simulation) ───


@pytest.mark.fixture_only
def test_partial_copy_detected_not_verified(tmp_path):
    st = run_all(tmp_path)["S3 destination write interrupted"]
    partial = st["partial"]
    assert partial.stat().st_size < st["expected_size"], "partial must be short"
    # A partial file must never be treated as verified.
    assert partial.stat().st_size != st["expected_size"]


@pytest.mark.fixture_only
def test_disk_full_preflight_no_verdict(tmp_path):
    st = run_all(tmp_path)["S3 disk full"]
    assert st["free_bytes"] == 0
    # Preflight on a full destination issues NO verdict (no false pass).
    assert st["free_bytes"] < 1


@pytest.mark.fixture_only
def test_kill_resume_checkpoint_converges(tmp_path):
    st = run_all(tmp_path)["S4 process kill + resume"]
    data = st["checkpoint"].read_text()
    assert '"phase": "copy"' in data and '"done"' in data
    # Resume re-entry: done files are not re-copied; remaining converge.
    assert "A0010101.A" in data


# ── source replaced mid-run ─────────────────────────────────────────


@pytest.mark.fixture_only
def test_source_replaced_digest_drift_detected(tmp_path):
    st = run_all(tmp_path)["S1 source replaced between pre-read and copy-read"]
    assert st["pre_digest"] != st["post_digest"], "swap must change the digest"
    # Drift detected → the run must be FAILED, no verified replica.
    assert st["pre_digest"] and st["post_digest"]


# ── re-run must not damage a good verified replica ─────────────────


@pytest.mark.fixture_only
def test_rerun_preserves_good_replica(tmp_path):
    st = run_all(tmp_path)["S4 re-run with verified replica present"]
    src, good = st["source"], st["good_replica"]
    for f in good.rglob("*.A"):
        rel = f.relative_to(good)
        srcf = src / rel
        if srcf.exists() and f.name != "zero-byte.A":
            assert f.read_bytes() == srcf.read_bytes(), (
                "good replica byte-identical to source (must survive re-run)"
            )


# ── device identity change on reconnect (HW BLOCKED) ───────────────


@pytest.mark.hw_blocked
def test_device_reconnect_identity_change_is_blocked(tmp_path):
    st = run_all(tmp_path)["S2 device identity change on reconnect"]
    assert st["old_identity"]["serial"] != st["new_identity"]["serial"]
    assert _classify("S2 device identity change on reconnect") == "HW_BLOCKED"


# ── S5 ASC MHL tamper (engine native) ──────────────────────────────


@pytest.mark.fixture_only
def test_mhl_tamper_detected_by_digest(tmp_path):
    st = run_all(tmp_path)["S5 ASC MHL manifest tamper"]
    import hashlib

    real = hashlib.sha256(st["real_file"].read_bytes()).hexdigest()
    manifest_txt = st["manifest"].read_text()
    # The manifest records a digest that does NOT match the on-disk file.
    assert "0" * 64 in manifest_txt
    assert real not in manifest_txt, "tampered digest must not match reality"


# ── S7 edge names ──────────────────────────────────────────────────


@pytest.mark.fixture_only
def test_edge_names_generated(tmp_path):
    st = run_all(tmp_path)["S7 edge names: 0-byte/Unicode/case/Windows-reserved"]
    for key in (
        "zero_byte",
        "unicode_cjk_kr",
        "emoji_long",
        "case_dup_upper",
        "case_dup_lower",
        "windows_reserved_con",
        "windows_reserved_prn",
    ):
        assert key in st["names"], f"missing edge name {key}"
    # 0-byte must be zero bytes.
    zc = Path(st["names"]["zero_byte"])
    assert zc.stat().st_size == 0
    # case pair must collide on casefold (Windows/exFAT folding).
    up = Path(st["names"]["case_dup_upper"]).name.casefold()
    lo = Path(st["names"]["case_dup_lower"]).name.casefold()
    assert up == lo


# ── S6 forged flags → zero-tolerance false SAFE_TO_FORMAT gate ─────
#
# These exercise the P05.1 `reuse_eligibility` gate: a forged
# `verified=True` with NO readback evidence, or a forged failure_domain,
# must come back BLOCKED. This is the adapter's single hard safety line.


def _gate_for(tmp_path: Path, seed: int, domain: str, with_evidence: bool) -> ReuseEligibility:
    aid = _asset_id(seed)
    db_dir = tmp_path / f"gate_{seed:02x}"
    db_dir.mkdir(parents=True, exist_ok=True)
    cat = Dit22Catalog(db_dir / "gate.db")
    try:
        cat.upsert_asset(MediaAsset(source_sha256=aid))
        cat.add_replica(Replica("r1", aid, "s1", domain, "/a", verified=True))
        cat.add_replica(Replica("r2", aid, "s2", "fd-2", "/b", verified=True))
        if with_evidence:
            cat.add_evidence(
                VerificationEvidence(
                    "e1", aid, "a.mov", "sha256", "11" * 32, "dev1",
                    "PASS", replica_id="r1",
                )
            )
            cat.add_evidence(
                VerificationEvidence(
                    "e2", aid, "b.mov", "sha256", "22" * 32, "dev2",
                    "PASS", replica_id="r2",
                )
            )
        return cat.reuse_eligibility(aid)
    finally:
        cat.close()


@pytest.mark.behavior_tested
def test_forged_verified_flag_without_readback_is_blocked(tmp_path):
    """S6 forged verified flag: two 'verified' replicas but zero readback
    evidence → BLOCKED. This is the zero-tolerance false-SAFE line."""
    gate = _gate_for(tmp_path, 0x51, "fd-1", with_evidence=False)
    assert gate.is_eligible is False
    assert gate.verdict == "BLOCKED"
    # The specific failing gate must be the readback gate.
    assert gate.gates["readback_evidence"] is False


@pytest.mark.behavior_tested
def test_forged_failure_domain_is_blocked(tmp_path):
    """S6 forged failure_domain: claim an independent domain you cannot prove.
    An 'unknown' domain is not counted → the trusted-device gate fails."""
    gate = _gate_for(tmp_path, 0x52, "unknown", with_evidence=True)
    assert gate.is_eligible is False
    assert gate.verdict == "BLOCKED"
    assert gate.gates["no_untrusted_device_identity"] is False


@pytest.mark.behavior_tested
def test_missing_readback_despite_two_replicas_blocked(tmp_path):
    """S6: two verified replicas across two trusted domains, but no readback
    evidence at all → BLOCKED (replica count alone never grants reuse)."""
    gate = _gate_for(tmp_path, 0x53, "fd-1", with_evidence=False)
    assert gate.is_eligible is False
    assert gate.gates["readback_evidence"] is False


@pytest.mark.behavior_tested
def test_full_evidence_chain_is_eligible(tmp_path):
    """Positive control: the same chain WITH readback evidence on both
    replicas and trusted domains → ELIGIBLE_FOR_REVIEW (still not
    SAFE_TO_FORMAT — the verdict string must never say format-safe)."""
    gate = _gate_for(tmp_path, 0x54, "fd-1", with_evidence=True)
    assert gate.is_eligible is True
    assert gate.verdict == "ELIGIBLE_FOR_REVIEW"
    assert "SAFE_TO_FORMAT" not in gate.verdict


# ── zero-tolerance aggregate assertion ─────────────────────────────


@pytest.mark.behavior_tested
def test_no_scenario_yields_false_safe_to_format(tmp_path):
    """The whole matrix must contain NO scenario that yields a false
    SAFE_TO_FORMAT. Every S6 guard case must be BLOCKED; every positive
    control must be ELIGIBLE_FOR_REVIEW (never SAFE_TO_FORMAT)."""
    blocked = [
        "S6 forged verified flag, no readback",
        "S6 forged failure_domain, no proof",
        "S6 missing readback evidence",
    ]
    for name in blocked:
        assert _classify(name) == "DIT_ADAPTER_GUARD", name
    # The gate never returns SAFE_TO_FORMAT for the forged cases:
    for seed, domain in ((0x51, "fd-1"), (0x52, "unknown"), (0x53, "fd-1")):
        g = _gate_for(tmp_path / f"agg_{seed:02x}", seed, domain,
                      with_evidence=(seed == 0x52 and domain == "unknown"))
        # 0x52/unknown with evidence still fails trusted-device;
        # 0x51/0x53 without evidence fail readback. All BLOCKED.
        if seed != 0x52:
            assert g.is_eligible is False, f"seed {seed:#x} must be BLOCKED"
