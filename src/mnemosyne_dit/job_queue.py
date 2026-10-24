"""job_queue.py — DIT 2.2 P09 durable job control (F17).

Pure stdlib SQLite in the isolated `dit22` namespace (its own
`dit22_jobs.db` — a path the *caller* chooses; this module never opens
or writes the v4 `files.db`). Implements the P09 spec
(`docs/engineering/spec/P09-durable-job-queue.md`):

- **Idempotent enqueue**: same `idempotency_key` => same job row, no
  duplicate work (F17 `job_id` + `idempotency_key`).
- **Exclusive lease with expiry**: one unexpired lease per job; an
  expired lease is takeable (worker crash) and the takeover increments
  `attempt`. Re-owning your own unexpired lease is a no-op.
- **Checkpoint durability**: progress snapshots survive pause/resume
  so an interrupted worker continues where it stopped.
- **Input-manifest drift**: completion re-checks the input snapshot;
  drift => job FAILED, never "finished" on changed inputs.
- **Irreversibility rule**: a job marked `reversible=False` (inputs
  that cannot be re-run safely — destructive or quota-spending work)
  REFUSES automatic retry after FAILED, even when a human authorizes
  it: the only path is a fresh job under a new key. Reversible jobs
  may be re-queued.
- **Priority + FIFO**: claims are ordered by priority desc, then
  enqueue order within the same priority.

This module stores state; it does not run work. A consumer (worker
pool / orchestrator, P09+ follow-on) calls lease/update_checkpoint/
complete. No daemon is started here (ADR-DIT2-003 parallelism stays
PROPOSED, awaiting user approval).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dit22_job (
    job_id            TEXT PRIMARY KEY,
    idempotency_key   TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    input_manifest    TEXT NOT NULL DEFAULT '{}',
    priority          INTEGER NOT NULL DEFAULT 0,
    reversible        INTEGER NOT NULL DEFAULT 1,
    state             TEXT NOT NULL DEFAULT 'PENDING',
    attempt           INTEGER NOT NULL DEFAULT 0,
    lease_token       TEXT,
    lease_worker      TEXT,
    lease_expires_at  REAL,
    checkpoint        TEXT NOT NULL DEFAULT '{}',
    fail_reason       TEXT,
    seq               INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS dit22_job_claim_idx
    ON dit22_job(state, priority DESC, seq ASC);
"""


class LeaseHeldError(Exception):
    """Another worker holds an unexpired lease on this job."""


class IrreversibleRetryError(Exception):
    """The job is marked irreversible: it will never be re-run from
    this record. Start a fresh job (new idempotency key) instead."""


class InputManifestDriftError(Exception):
    """The input snapshot no longer matches what was enqueued — the job
    cannot safely continue or complete."""


def _now() -> float:
    return time.time()


class DurableJobQueue:
    """One durable job table in one SQLite file (the caller's path)."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ── enqueue (idempotent) ─────────────────────────────────────────

    def enqueue(
        self,
        name: str,
        manifest: dict[str, str] | None = None,
        *,
        idempotency_key: str,
        priority: int = 0,
        reversible: bool = True,
    ) -> dict[str, Any]:
        manifest = manifest or {}
        existing = self.conn.execute(
            "SELECT job_id FROM dit22_job WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            row = self._row(existing[0])
            return row
        job_id = str(uuid.uuid4())
        seq = (
            self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM dit22_job")
            .fetchone()[0]
        )
        self.conn.execute(
            "INSERT INTO dit22_job (job_id, idempotency_key, name, input_manifest,"
            " priority, reversible, state, attempt, checkpoint, seq) "
            "VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)",
            (
                job_id,
                idempotency_key,
                name,
                json.dumps(manifest),
                priority,
                int(reversible),
                "{}",
                seq,
            ),
        )
        self.conn.commit()
        return self._row(job_id)

    # ── lease ────────────────────────────────────────────────────────

    def lease(self, job_id: str, worker: str, ttl_seconds: float = 300.0) -> str:
        """Take (or keep) the lease. Returns the lease token.

        - PENDING/PAUSED: fresh lease, `attempt` +1.
        - LEASED by the SAME worker, unexpired: no-op (same token, no
          extra attempt).
        - LEASED by ANOTHER worker, unexpired: `LeaseHeldError`.
        - LEASED but EXPIRED: takeover, `attempt` +1.
        - DONE/FAILED: no leasing (retries go through `retry()`).
        """
        row = self._row(job_id)
        state = row["state"]
        now = _now()
        if state in ("DONE", "FAILED"):
            return row.get("lease_token") or ""
        unexpired = (
            row["lease_expires_at"] is not None and now < row["lease_expires_at"]
        )
        if state == "LEASED" and unexpired:
            if row["lease_worker"] == worker:
                return row["lease_token"]  # idempotent no-op
            raise LeaseHeldError(
                f"job {job_id} leased by {row['lease_worker']!r} until "
                f"{row['lease_expires_at']}"
            )
        # PENDING, PAUSED, or an expired lease: take it.
        token = str(uuid.uuid4())
        self.conn.execute(
            "UPDATE dit22_job SET state='LEASED', lease_token=?, lease_worker=?,"
            " lease_expires_at=?, attempt=attempt+1 WHERE job_id=?",
            (token, worker, now + ttl_seconds, job_id),
        )
        self.conn.commit()
        return token

    # ── checkpoint / lifecycle ───────────────────────────────────────

    def update_checkpoint(
        self, job_id: str, worker: str, checkpoint: dict[str, Any]
    ) -> None:
        row = self._row(job_id)
        self._assert_leased_to(row, worker)
        self.conn.execute(
            "UPDATE dit22_job SET checkpoint=? WHERE job_id=?",
            (json.dumps(checkpoint), job_id),
        )
        self.conn.commit()

    def pause(self, job_id: str, worker: str) -> None:
        row = self._row(job_id)
        self._assert_leased_to(row, worker)
        self.conn.execute(
            "UPDATE dit22_job SET state='PAUSED', lease_token=NULL,"
            " lease_worker=NULL, lease_expires_at=NULL WHERE job_id=?",
            (job_id,),
        )
        self.conn.commit()

    def fail(self, job_id: str, worker: str, reason: str) -> None:
        row = self._row(job_id)
        self._assert_leased_to(row, worker)
        self.conn.execute(
            "UPDATE dit22_job SET state='FAILED', fail_reason=?,"
            " lease_token=NULL, lease_worker=NULL, lease_expires_at=NULL"
            " WHERE job_id=?",
            (reason, job_id),
        )
        self.conn.commit()

    def verify_manifest(self, job_id: str, actual: dict[str, str]) -> None:
        """Drift check: raises `InputManifestDriftError` on mismatch."""
        row = self._row(job_id)
        expected = row["input_manifest"]  # _row() already JSON-decodes it
        if expected != actual:
            raise InputManifestDriftError(
                f"job {job_id}: input manifest drifted "
                f"(enqueued {expected} != actual {actual})"
            )

    def complete(self, job_id: str, worker: str, actual_manifest: dict[str, str]) -> bool:
        """Finish the job after re-checking the input snapshot.
        Drift => FAILED + False (never 'done' on changed inputs)."""
        row = self._row(job_id)
        self._assert_leased_to(row, worker)
        try:
            self.verify_manifest(job_id, actual_manifest)
        except InputManifestDriftError:
            self.conn.execute(
                "UPDATE dit22_job SET state='FAILED',"
                " fail_reason='input manifest drift',"
                " lease_token=NULL, lease_worker=NULL, lease_expires_at=NULL"
                " WHERE job_id=?",
                (job_id,),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            "UPDATE dit22_job SET state='DONE', lease_token=NULL,"
            " lease_worker=NULL, lease_expires_at=NULL WHERE job_id=?",
            (job_id,),
        )
        self.conn.commit()
        return True

    def retry(self, job_id: str, authorize_manual: bool = False) -> bool:
        """Re-queue a FAILED job. Irreversible jobs refuse ALL retries
        (the flag authorizes a human START, not a rewrite of history —
        the manual path is a fresh job under a new key)."""
        row = self._row(job_id)
        if row["state"] != "FAILED":
            return False
        if not row["reversible"]:
            raise IrreversibleRetryError(
                f"job {job_id} is irreversible; start a fresh job with a new "
                f"idempotency key instead of retrying this record"
            )
        self.conn.execute(
            "UPDATE dit22_job SET state='PENDING', fail_reason=NULL WHERE job_id=?",
            (job_id,),
        )
        self.conn.commit()
        return True

    # ── claiming (priority + FIFO) ───────────────────────────────────

    def claim_next_batch(self, limit: int = 1) -> list[dict[str, Any]]:
        """Return up to `limit` PENDING jobs ordered by priority desc,
        then enqueue order (FIFO within a priority). Claiming does not
        lease — the consumer leases each job explicitly (one worker,
        one lease, exclusive)."""
        cur = self.conn.execute(
            "SELECT job_id FROM dit22_job WHERE state='PENDING' "
            "ORDER BY priority DESC, seq ASC LIMIT ?",
            (limit,),
        )
        return [self._row(job_id) for job_id in [r[0] for r in cur.fetchall()]]

    # ── introspection ────────────────────────────────────────────────

    def job_state(self, job_id: str) -> dict[str, Any]:
        return self._row(job_id)

    def count_jobs(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM dit22_job").fetchone()[0]

    # ── lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── internals ────────────────────────────────────────────────────

    def _row(self, job_id: str) -> dict[str, Any]:
        r = self.conn.execute(
            "SELECT job_id, idempotency_key, name, input_manifest, priority,"
            " reversible, state, attempt, lease_token, lease_worker,"
            " lease_expires_at, checkpoint, fail_reason, seq"
            " FROM dit22_job WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if r is None:
            raise KeyError(job_id)
        return {
            "job_id": r[0],
            "idempotency_key": r[1],
            "name": r[2],
            "input_manifest": json.loads(r[3]),
            "priority": r[4],
            "reversible": bool(r[5]),
            "state": r[6],
            "attempt": r[7],
            "lease_token": r[8],
            "lease_worker": r[9],
            "lease_expires_at": r[10],
            "checkpoint": json.loads(r[11]),
            "fail_reason": r[12],
            "seq": r[13],
        }

    def _assert_leased_to(self, row: dict[str, Any], worker: str) -> None:
        now = _now()
        unexpired = (
            row["lease_expires_at"] is not None and now < row["lease_expires_at"]
        )
        if row["state"] != "LEASED" or not unexpired or row["lease_worker"] != worker:
            raise LeaseHeldError(
                f"job {row['job_id']} is not leased to {worker!r} "
                f"(state={row['state']}, holder={row['lease_worker']!r})"
            )
