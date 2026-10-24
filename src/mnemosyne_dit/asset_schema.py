"""
asset_schema.py — DIT 2.2 canonical asset identity + path observations.

Pure stdlib. Implements the P05 clean-room data-model sketch from
`docs/engineering/spec/P04-clean-room-contracts.md §2`:

- `asset_id` is a **content identity** (`sha256(source bytes)`), decoupled
  from any filesystem path. The same content reached by different NAS paths
  is the *same* asset; a different content with the same basename is a
  *different* asset.
- A single `Dit22Catalog` lives in its **own SQLite file** (a new `dit22`
  namespace). It NEVER opens or writes the v4 `files.db` and never touches
  the Qdrant `text_vec(768)`/`image_vec(512)` named vectors.
- Path observations and replicas are **records** about where an asset is
  observed; nothing here moves, deletes, or rewrites a source file.

Safety invariants (P04 §2 / §1 S1, S6):
- Derived views only: this catalog is rebuildable from the source.
- No auto-move: observations are append records; callers move nothing.
- `unknown` storage failure_domain is stored verbatim and treated as
  non-independent by consumers (fail-closed); the catalog does not guess.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

CHUNK = 1 << 20  # 1 MiB streaming reads


class EvidenceConflictError(Exception):
    """A re-submitted evidence row with the same `evidence_id` but different
    values would silently rewrite the append-only audit trail (P05.1 S5).
    Refused: the existing verdict is authoritative."""


class ReplicaConflictError(Exception):
    """A re-submitted replica with the same `replica_id` but different
    values (e.g. a changed failure_domain) would silently re-tamper the
    safety ledger (P05.1 S2/S5). Refused: identical re-entry is a
    no-op, anything else is a conflict."""


def asset_id_for_bytes(data: bytes) -> str:
    """Content identity for an in-memory byte string."""
    return hashlib.sha256(data).hexdigest()


def asset_id_for_file(path: str | Path) -> str:
    """Content identity for a file, streamed (never loads the whole file).

    Identity is by **bytes**, not by basename or path.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class MediaAsset:
    """Canonical asset: content-addressed, path-independent."""

    source_sha256: str
    camera_family: str = "unknown"
    card_id: str | None = None
    reel: str | None = None

    @property
    def asset_id(self) -> str:
        # Content identity == the source sha256. Stable across paths.
        return self.source_sha256

    @classmethod
    def from_file(cls, path: str | Path, **kw) -> MediaAsset:
        return cls(source_sha256=asset_id_for_file(path), **kw)


@dataclass
class AssetPathObservation:
    """Where an asset is observed (append-only; does not move the source)."""

    asset_id: str
    storage_id: str
    path: str
    size_bytes: int
    mtime: int | None = None
    observed_at: int | None = None

    def to_row(self) -> tuple:
        return (
            self.asset_id,
            self.storage_id,
            self.path,
            self.size_bytes,
            self.mtime,
            self.observed_at,
        )


@dataclass
class Replica:
    """A verified copy of an asset on a storage device / failure domain."""

    replica_id: str
    asset_id: str
    storage_id: str
    failure_domain: str  # unknown => consumers treat as non-independent
    path: str
    verified: bool = False
    verified_at: int | None = None


@dataclass
class VerificationEvidence:
    """Append-only hash evidence for a replica (MHL ledger stand-in)."""

    evidence_id: str
    asset_id: str
    file_name: str
    algorithm: str
    digest: str
    device_id: str | None = None
    verdict: str = "PENDING"
    replica_id: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS dit22_asset (
    asset_id      TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    camera_family TEXT NOT NULL DEFAULT 'unknown',
    card_id       TEXT,
    reel          TEXT
);
CREATE TABLE IF NOT EXISTS dit22_observation (
    asset_id      TEXT NOT NULL REFERENCES dit22_asset(asset_id),
    storage_id    TEXT NOT NULL,
    path          TEXT NOT NULL,
    size_bytes    INTEGER,
    mtime         INTEGER,
    observed_at   INTEGER,
    PRIMARY KEY (asset_id, storage_id, path)
);
CREATE TABLE IF NOT EXISTS dit22_replica (
    replica_id     TEXT PRIMARY KEY,
    asset_id       TEXT NOT NULL REFERENCES dit22_asset(asset_id),
    storage_id     TEXT NOT NULL,
    failure_domain TEXT NOT NULL,
    path           TEXT NOT NULL,
    verified       INTEGER NOT NULL DEFAULT 0,
    verified_at    INTEGER
);
CREATE TABLE IF NOT EXISTS dit22_evidence (
    evidence_id TEXT PRIMARY KEY,
    asset_id    TEXT NOT NULL REFERENCES dit22_asset(asset_id),
    file_name   TEXT NOT NULL,
    algorithm   TEXT NOT NULL,
    digest      TEXT NOT NULL,
    device_id   TEXT,
    verdict     TEXT NOT NULL DEFAULT 'PENDING',
    replica_id  TEXT
);
"""


@dataclass
class ReuseEligibility:
    """Fail-closed advisory verdict for whether an asset's replicas may be
    re-used (e.g. as edit source material).

    This gate is the ONLY surface that may express a reuse verdict. It never
    says `SAFE_TO_FORMAT` — no catalog-level count or flag in this module may
    ever authorize reformatting or deleting a source (P04 §1 S6, S1).
    """

    verdict: str  # "BLOCKED" | "ELIGIBLE_FOR_REVIEW"
    is_eligible: bool
    gates: dict = field(default_factory=dict)


class Dit22Catalog:
    """New-namespace SQLite catalog. Isolated from v4 `files.db`/Qdrant."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ── assets ────────────────────────────────────────────────────────
    def upsert_asset(self, asset: MediaAsset) -> str:
        # Conflict path is COALESCE-based: a new value only fills a field
        # that is currently NULL. A known card_id/reel is NEVER overwritten
        # by a later NULL-carrying upsert (P05.1: no silent clobber).
        self.conn.execute(
            """
            INSERT INTO dit22_asset (asset_id, source_sha256, camera_family, card_id, reel)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                camera_family=excluded.camera_family,
                card_id=COALESCE(excluded.card_id, dit22_asset.card_id),
                reel=COALESCE(excluded.reel, dit22_asset.reel)
            """,
            (
                asset.asset_id,
                asset.source_sha256,
                asset.camera_family,
                asset.card_id,
                asset.reel,
            ),
        )
        self.conn.commit()
        return asset.asset_id

    # ── observations / replicas / evidence ────────────────────────────
    def _seed_asset(self, asset_id: str) -> None:
        """Ensure the asset row exists; do NOT clobber an existing richer row.

        `INSERT OR IGNORE` seeds a minimal record only when absent, so a
        later `add_replica`/`add_observation` cannot overwrite card_id/reel
        that an explicit `upsert_asset` already set.
        """
        self.conn.execute(
            "INSERT OR IGNORE INTO dit22_asset (asset_id, source_sha256) VALUES (?, ?)",
            (asset_id, asset_id),
        )
        self.conn.commit()

    def add_observation(self, obs: AssetPathObservation) -> None:
        self._seed_asset(obs.asset_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO dit22_observation "
            "(asset_id, storage_id, path, size_bytes, mtime, observed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            obs.to_row(),
        )
        self.conn.commit()

    def observations_for(self, asset_id: str) -> list[AssetPathObservation]:
        cur = self.conn.execute(
            "SELECT asset_id, storage_id, path, size_bytes, mtime, observed_at "
            "FROM dit22_observation WHERE asset_id=? ORDER BY storage_id, path",
            (asset_id,),
        )
        return [
            AssetPathObservation(r[0], r[1], r[2], r[3], r[4], r[5])
            for r in cur.fetchall()
        ]

    def add_replica(self, rep: Replica) -> None:
        """Register a replica. Identical re-entry is a no-op (resume-safe);
        any value change under the same replica_id raises
        `ReplicaConflictError` — silent rewrites of the safety ledger are
        the S5 tamper path this refuses."""
        self._seed_asset(rep.asset_id)
        existing = self.conn.execute(
            "SELECT asset_id, storage_id, failure_domain, path, verified, verified_at "
            "FROM dit22_replica WHERE replica_id=?",
            (rep.replica_id,),
        ).fetchone()
        new_row = (
            rep.asset_id,
            rep.storage_id,
            rep.failure_domain,
            rep.path,
            int(rep.verified),
            rep.verified_at,
        )
        if existing is not None:
            if tuple(existing) != new_row:
                raise ReplicaConflictError(
                    f"replica {rep.replica_id!r} already recorded with different "
                    f"values; existing={existing}, new={new_row}"
                )
            return  # identical resume: nothing to do
        self.conn.execute(
            "INSERT INTO dit22_replica "
            "(replica_id, asset_id, storage_id, failure_domain, path, verified, verified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rep.replica_id, *new_row),
        )
        self.conn.commit()

    def replicas_for(self, asset_id: str) -> list[Replica]:
        cur = self.conn.execute(
            "SELECT replica_id, asset_id, storage_id, failure_domain, path, verified, verified_at "
            "FROM dit22_replica WHERE asset_id=? ORDER BY replica_id",
            (asset_id,),
        )
        return [
            Replica(r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6])
            for r in cur.fetchall()
        ]

    def independent_replicas(self, asset_id: str) -> int:
        """Count replicas across *distinct, known* failure domains.

        A replica whose `failure_domain == 'unknown'` is NOT counted as an
        independent backup (fail-closed; mirrors ADR-DIT2-004 / F13).
        """
        reps = self.replicas_for(asset_id)
        domains = {
            r.failure_domain
            for r in reps
            if r.verified and r.failure_domain != "unknown"
        }
        return len(domains)

    def add_evidence(self, ev: VerificationEvidence) -> None:
        """Append-only audit trail (P04 S5). An identical re-entry is a
        no-op (resume-safe); a row with the same `evidence_id` but any other
        value (e.g. a verdict flipped PASS→FAIL) raises
        `EvidenceConflictError` — the first recorded verdict is
        authoritative and cannot be rewritten."""
        self._seed_asset(ev.asset_id)
        row = (
            ev.asset_id,
            ev.file_name,
            ev.algorithm,
            ev.digest,
            ev.device_id,
            ev.verdict,
            ev.replica_id,
        )
        existing = self.conn.execute(
            "SELECT asset_id, file_name, algorithm, digest, device_id, verdict, replica_id "
            "FROM dit22_evidence WHERE evidence_id=?",
            (ev.evidence_id,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != row:
                raise EvidenceConflictError(
                    f"evidence {ev.evidence_id!r} already recorded with different "
                    f"values; existing={existing}, new={row}"
                )
            return  # identical resume
        self.conn.execute(
            "INSERT INTO dit22_evidence "
            "(evidence_id, asset_id, file_name, algorithm, digest, device_id, verdict, replica_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ev.evidence_id, *row),
        )
        self.conn.commit()

    def evidence_for(self, asset_id: str) -> list[VerificationEvidence]:
        cur = self.conn.execute(
            "SELECT evidence_id, asset_id, file_name, algorithm, digest, device_id, verdict, replica_id "
            "FROM dit22_evidence WHERE asset_id=? ORDER BY evidence_id",
            (asset_id,),
        )
        return [
            VerificationEvidence(
                r[0], r[1], r[2], r[3], r[4], r[5], r[6], replica_id=r[7]
            )
            for r in cur.fetchall()
        ]

    # ── fail-closed reuse gate (S6) ──────────────────────────────────
    def reuse_eligibility(self, asset_id: str) -> ReuseEligibility:
        """Fail-closed gate: may this asset's replicas be re-used as working
        material? ALL gates must pass; any failure (or missing evidence)
        yields `BLOCKED`. This gate never says `SAFE_TO_FORMAT`.

        Gates:
        - readback_evidence: at least one PASS readback evidence row bound to
          a replica of this asset.
        - no_untrusted_device_identity: every verified replica must carry a
          known (non-`unknown`) failure_domain. An `unknown` domain is
          treated as non-independent (fail-closed).
        """
        reps = self.replicas_for(asset_id)
        evs = self.evidence_for(asset_id)

        readback = any(
            e.verdict == "PASS" and e.replica_id is not None for e in evs
        )
        verified = [r for r in reps if r.verified]
        untrusted = any(r.failure_domain == "unknown" for r in verified)

        gates = {
            "readback_evidence": readback,
            "no_untrusted_device_identity": not untrusted,
        }
        ok = all(gates.values())
        return ReuseEligibility(
            verdict="ELIGIBLE_FOR_REVIEW" if ok else "BLOCKED",
            is_eligible=ok,
            gates=gates,
        )

    # ── lifecycle ─────────────────────────────────────────────────────
    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
