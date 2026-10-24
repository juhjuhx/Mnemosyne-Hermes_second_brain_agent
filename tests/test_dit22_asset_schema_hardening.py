"""P05.1 negative (contract-gap) tests for the dit22 asset schema.

Independent-review findings being turned into tests FIRST (Red), then the
minimal fix in `asset_schema.py` makes them Green:

1. `independent_replicas()` counts caller-provided `verified`/`failure_domain`
   fields only — it must NOT be usable as a `SAFE_TO_FORMAT` basis. A
   separate fail-closed `reuse_eligibility()` gate must require append-only
   readback evidence.
2. `add_evidence()` used INSERT OR REPLACE — silent verdict clobber conflicts
   with the append-only audit contract.
3. `upsert_asset()` clobbered known `card_id`/`reel` with NULL on conflict.
4. SQLite foreign keys were not enforced (PRAGMA default OFF) despite the
   schema declaring REFERENCES.
5. Re-entry: re-adding the same replica with different values was a silent
   REPLACE (tamper invisible).

All synthetic. No real media, no v4 DB, no network.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from asset_schema import (
    Dit22Catalog,
    EvidenceConflictError,
    MediaAsset,
    Replica,
    ReplicaConflictError,
    VerificationEvidence,
)


def _aid(seed: int) -> str:
    return (seed.to_bytes(32, "big")).hex()


# ── Finding 3: upsert must not clobber known card_id / reel ─────────


def test_upsert_does_not_clobber_known_card_and_reel(tmp_path):
    with Dit22Catalog(tmp_path / "d.db") as cat:
        asset = MediaAsset(source_sha256=_aid(1), card_id="CF-A001", reel="A001")
        cat.upsert_asset(asset)
        # Later upsert by another worker with unknown card/reel:
        cat.upsert_asset(MediaAsset(source_sha256=_aid(1)))
        row = cat.conn.execute(
            "SELECT card_id, reel FROM dit22_asset WHERE asset_id=?", (asset.asset_id,)
        ).fetchone()
        assert row == ("CF-A001", "A001"), "upsert must not overwrite known values with NULL"


def test_upsert_fills_missing_fields(tmp_path):
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=_aid(2)))  # card/reel NULL
        cat.upsert_asset(MediaAsset(source_sha256=_aid(2), card_id="SSD-B", reel="B002"))
        row = cat.conn.execute(
            "SELECT card_id, reel FROM dit22_asset WHERE asset_id=?", (cat.conn.execute("SELECT 1").fetchone()[0] and _aid(2),)
        ).fetchone()
        assert row == ("SSD-B", "B002"), "gap-fill must still work"


# ── Finding 2: evidence is append-only ──────────────────────────────


def test_evidence_conflict_raises_on_verdict_change(tmp_path):
    ev = VerificationEvidence("e1", _aid(3), "A.mov", "sha256", "ab" * 32, "dev1", "PASS")
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=_aid(3)))
        cat.add_evidence(ev)
        # Tampered re-run tries to rewrite the verdict:
        with pytest.raises(EvidenceConflictError):
            cat.add_evidence(
                VerificationEvidence("e1", _aid(3), "A.mov", "sha256", "ab" * 32, "dev1", "FAIL")
            )


def test_evidence_identical_reentry_is_idempotent(tmp_path):
    ev = VerificationEvidence("e1", _aid(4), "A.mov", "sha256", "cd" * 32, "dev1", "PASS")
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=_aid(4)))
        cat.add_evidence(ev)
        cat.add_evidence(ev)  # resume re-entry: identical row must not raise
        n = cat.conn.execute("SELECT COUNT(*) FROM dit22_evidence").fetchone()[0]
        assert n == 1, "identical re-entry must not duplicate rows"


# ── Finding 4: foreign keys actually enforced ───────────────────────


def test_foreign_keys_enforced_for_orphan_observation(tmp_path):
    cat = Dit22Catalog(tmp_path / "d.db")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            cat.conn.execute(
                "INSERT INTO dit22_observation (asset_id, storage_id, path, size_bytes) "
                "VALUES (?, ?, ?, ?)",
                ("deadbeef" * 8, "s1", "/x", 1),
            )
            cat.conn.commit()
    finally:
        cat.close()


def test_foreign_keys_pragma_on_at_open(tmp_path):
    with Dit22Catalog(tmp_path / "d.db") as cat:
        assert cat.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# ── Finding 5: replica re-entry must not silently rewrite ──────────


def test_replica_conflict_on_value_change(tmp_path):
    rid, aid = "r1", _aid(5)
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=aid))
        cat.add_replica(Replica(rid, aid, "s1", "fd-1", "/a", verified=True))
        with pytest.raises(ReplicaConflictError):
            # Tamper: same replica claimed on a different failure domain
            cat.add_replica(Replica(rid, aid, "s1", "fd-2", "/a", verified=True))
        cat.add_replica(Replica(rid, aid, "s1", "fd-1", "/a", verified=True))  # identical OK


# ── Finding 1: replica count must not become SAFE_TO_FORMAT ────────


def test_reuse_gate_fail_closed_without_evidence(tmp_path):
    """Two verified replicas in distinct domains are NOT enough — readback
    evidence is required. The count function stays advisory; only the gate
    can say anything, and it must say BLOCKED here."""
    aid = _aid(6)
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=aid))
        cat.add_replica(Replica("r1", aid, "s1", "fd-1", "/a", verified=True))
        cat.add_replica(Replica("r2", aid, "s2", "fd-2", "/b", verified=True))
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is False, "no readback evidence → BLOCKED"
        assert gate.verdict == "BLOCKED"
        assert gate.gates["readback_evidence"] is False


def test_reuse_gate_blocks_unknown_device_identity(tmp_path):
    aid = _aid(7)
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=aid))
        cat.add_replica(Replica("r1", aid, "s1", "fd-1", "/a", verified=True))
        cat.add_replica(Replica("r2", aid, "s2", "unknown", "/b", verified=True))
        cat.add_evidence(
            VerificationEvidence("e1", aid, "a.mov", "sha256", "11" * 32, "dev1", "PASS", replica_id="r1")
        )
        cat.add_evidence(
            VerificationEvidence("e2", aid, "b.mov", "sha256", "22" * 32, "dev2", "PASS", replica_id="r2")
        )
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is False, "unknown device identity → BLOCKED (fail-closed)"
        assert gate.gates["no_untrusted_device_identity"] is False


def test_reuse_gate_eligible_with_full_chain(tmp_path):
    aid = _aid(8)
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=aid))
        cat.add_replica(Replica("r1", aid, "s1", "fd-1", "/a", verified=True))
        cat.add_replica(Replica("r2", aid, "s2", "fd-2", "/b", verified=True))
        cat.add_evidence(
            VerificationEvidence("e1", aid, "a.mov", "sha256", "11" * 32, "dev1", "PASS", replica_id="r1")
        )
        cat.add_evidence(
            VerificationEvidence("e2", aid, "b.mov", "sha256", "22" * 32, "dev2", "PASS", replica_id="r2")
        )
        gate = cat.reuse_eligibility(aid)
        assert gate.is_eligible is True
        assert gate.verdict == "ELIGIBLE_FOR_REVIEW"
        # The verdict is advisory: it must never read SAFE_TO_FORMAT.
        assert "SAFE_TO_FORMAT" not in gate.verdict


def test_independent_replicas_is_advisory_documentation(tmp_path):
    """The count function itself must not grant anything: docstring pins it
    as advisory, and the module exposes no SAFE_TO_FORMAT surface."""
    import asset_schema as mod

    aid = _aid(9)
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=aid))
        cat.add_replica(Replica("r1", aid, "s1", "fd-1", "/a", verified=True))
        cat.add_replica(Replica("r2", aid, "s2", "fd-2", "/b", verified=True))
        assert cat.independent_replicas(aid) == 2  # still advisory count
    public = [n for n in dir(mod) if "safe_to_format" in n.lower()]
    assert public == [], "no SAFE_TO_FORMAT surface may exist in the module"


# ── Atomicity / transaction hygiene ─────────────────────────────────


def test_failed_evidence_conflict_leaves_no_partial_state(tmp_path):
    ev = VerificationEvidence("e1", _aid(10), "A.mov", "sha256", "ab" * 32, "dev1", "PASS")
    with Dit22Catalog(tmp_path / "d.db") as cat:
        cat.upsert_asset(MediaAsset(source_sha256=_aid(10)))
        cat.add_evidence(ev)
        before = cat.conn.execute("SELECT * FROM dit22_evidence").fetchall()
        with pytest.raises(EvidenceConflictError):
            cat.add_evidence(
                VerificationEvidence("e1", _aid(10), "A.mov", "sha256", "cc" * 32, "dev1", "FAIL")
            )
        after = cat.conn.execute("SELECT * FROM dit22_evidence").fetchall()
        assert before == after, "rejected tamper must not mutate committed evidence"
