"""Contract tests for the DIT 2.2 canonical asset schema (P05).

Grounds P04 §2 (asset-schema) and P03 F03/F35. All tests are deterministic
and synthetic — no real media, no network, no v4 DB, no Qdrant.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from asset_schema import (
    AssetPathObservation,
    Dit22Catalog,
    MediaAsset,
    Replica,
    VerificationEvidence,
    asset_id_for_bytes,
    asset_id_for_file,
)

# ── Content identity (P03 F03) ───────────────────────────────────────


def test_asset_id_path_decoupled(tmp_path):
    """Same content at different paths → same asset_id; different content → different."""
    a = tmp_path / "DCIM" / "A001" / "A0010101.A"
    a.parent.mkdir(parents=True)
    a.write_bytes(b"same-content")
    b = tmp_path / "NAS" / "share" / "copy.mov"
    b.parent.mkdir(parents=True)
    b.write_bytes(b"same-content")
    c = tmp_path / "other" / "A0010101.A"
    c.parent.mkdir(parents=True)
    c.write_bytes(b"DIFFERENT-content")

    assert asset_id_for_file(a) == asset_id_for_file(b), "same bytes → same asset_id"
    assert asset_id_for_file(a) != asset_id_for_file(c), (
        "diff bytes → diff asset_id even with same basename"
    )


def test_asset_id_is_sha256_of_content():
    assert (
        asset_id_for_bytes(b"hello")
        == __import__("hashlib").sha256(b"hello").hexdigest()
    )


# ── New namespace isolation (invariant: v4 files.db / Qdrant untouched) ──


def test_catalog_is_isolated_new_db(tmp_path):
    """Catalog creates its own SQLite file; does not require or write files.db."""
    cat_db = tmp_path / "dit22.db"
    v4_db = tmp_path / "files.db"  # pretend v4 db exists alongside
    with Dit22Catalog(cat_db) as cat:
        asset = MediaAsset(source_sha256="ab" * 32, camera_family="ARRI", reel="A001")
        cat.upsert_asset(asset)
        # v4 db is never opened by our catalog
        assert not v4_db.exists(), "catalog must not create the v4 files.db"
        cat.add_observation(
            AssetPathObservation(asset.asset_id, "nas-a", "/mnt/nas/a/mov", 123)
        )
        obs = cat.observations_for(asset.asset_id)
        assert len(obs) == 1
        assert obs[0].storage_id == "nas-a"


# ── Multi-path observation, single asset (P03 F35) ──────────────────


def test_multi_path_observation_single_asset(tmp_path):
    with Dit22Catalog(tmp_path / "d.db") as cat:
        asset = MediaAsset(source_sha256="cd" * 32)
        cat.upsert_asset(asset)
        cat.add_observation(AssetPathObservation(asset.asset_id, "nas-a", "/a", 100))
        cat.add_observation(AssetPathObservation(asset.asset_id, "nas-b", "/b", 100))
        obs = cat.observations_for(asset.asset_id)
        assert len(obs) == 2, "two storages → two observations of the SAME asset"
        assert len({o.asset_id for o in obs}) == 1


# ── Independent replica / failure-domain counting (P03 F06/F13/F14) ──


def test_unknown_failure_domain_is_not_independent(tmp_path):
    """A replica on an 'unknown' failure domain is NOT an independent backup."""
    with Dit22Catalog(tmp_path / "d.db") as cat:
        asset = MediaAsset(source_sha256="ef" * 32)
        cat.upsert_asset(asset)
        cat.add_replica(
            Replica("r1", asset.asset_id, "nas-a", "domain-1", "/a", True, 0)
        )
        cat.add_replica(
            Replica("r2", asset.asset_id, "nas-b", "domain-2", "/b", True, 0)
        )
        cat.add_replica(
            Replica("r3", asset.asset_id, "nas-c", "unknown", "/c", True, 0)
        )
        cat.add_replica(
            Replica("r4", asset.asset_id, "nas-d", "domain-1", "/d", False, 0)
        )  # unverified, same domain-1
        assert cat.independent_replicas(asset.asset_id) == 2, (
            "domains {1,2}; unknown + unverified excluded"
        )


def test_no_verified_replica_means_zero(tmp_path):
    with Dit22Catalog(tmp_path / "d.db") as cat:
        asset = MediaAsset(source_sha256="01" * 32)
        cat.upsert_asset(asset)
        cat.add_replica(Replica("r1", asset.asset_id, "s", "d1", "/x", verified=False))
        assert cat.independent_replicas(asset.asset_id) == 0


# ── Evidence ledger (P03 F07, MHL stand-in) ─────────────────────────


def test_evidence_ledger_roundtrip(tmp_path):
    with Dit22Catalog(tmp_path / "d.db") as cat:
        asset = MediaAsset(source_sha256="22" * 32)
        cat.upsert_asset(asset)
        cat.add_evidence(
            VerificationEvidence(
                "e1", asset.asset_id, "A.mov", "sha256", "aa" * 32, "dev-1", "PASS"
            )
        )
        cur = cat.conn.execute(
            "SELECT verdict, algorithm FROM dit22_evidence WHERE evidence_id='e1'"
        )
        verdict, algo = cur.fetchone()
        assert (verdict, algo) == ("PASS", "sha256")


# ── Persistence / rebuildability (derived view, not source) ─────────


def test_catalog_persists_across_reopen(tmp_path):
    db = tmp_path / "d.db"
    with Dit22Catalog(db) as cat:
        asset = MediaAsset(source_sha256="33" * 32, reel="B001")
        cat.upsert_asset(asset)
        cat.add_replica(Replica("r1", asset.asset_id, "s1", "fd1", "/p", True, 5))
    # Reopen and read back — derived view rebuilds
    with Dit22Catalog(db) as cat2:
        reps = cat2.replicas_for(asset.asset_id)
        assert len(reps) == 1
        assert reps[0].verified and reps[0].verified_at == 5
        rows = cat2.conn.execute(
            "SELECT reel FROM dit22_asset WHERE asset_id=?", (asset.asset_id,)
        ).fetchall()
        assert rows == [("B001",)]
