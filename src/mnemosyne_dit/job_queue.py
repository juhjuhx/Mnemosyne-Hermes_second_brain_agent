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
- **P09.1 lease fencing**: every lease-protected state update
  (`update_checkpoint` / `pause` / `fail` / `complete`) is a single
  conditional UPDATE that re-checks the full fence at write time —
  `job_id`, `state='LEASED'`, the caller's exact `lease_token`,
  `lease_worker`, and that the lease is still unexpired. `rowcount=0`
  is fail-closed: it raises `LeaseFencedError` and nothing is written.
  A worker that restarts under the same name, or a stale process whose
  lease was taken over, cannot overwrite the current holder's state.

P09.1 scope note (spec §4): the DB fence protects queue state only.
External artifacts written by a worker between lease and complete are
fenced by the *destination's* atomic contract (P08 `StagedArchive`
receipt shape; P11 proxies must reuse it and record `job_id` +
`lease_token` in their receipt), never by the queue's CAS alone.

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
    seq               INTEGER NOT NULL,
    max_attempts      INTEGER,
    retry_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS dit22_job_claim_idx
    ON dit22_job(state, priority DESC, seq ASC);
"""


class LeaseHeldError(Exception):
    """Another worker holds an unexpired lease on this job."""


class IrreversibleRetryError(Exception):
    """The job is marked irreversible: it will never be re-run from
    this record. Start a fresh job (new idempotency key) instead."""


class RetryBudgetExhaustedError(Exception):
    """P12.2-D (Phase 4 C3): the job's bounded retry budget is used
    up. A reversible job's automatic re-queues are capped at
    `max_attempts` total attempts (the enqueue value, None = legacy
    unbounded); beyond that the record is terminal and a fresh job
    under a new idempotency key is the only path. Resource saturation
    must not loop forever against a saturated backend (backoff via
    `backoff_seconds`)."""


__all__ = [
    "DurableJobQueue",
    "InputManifestDriftError",
    "IrreversibleRetryError",
    "LeaseFencedError",
    "LeaseHeldError",
    "RetryBudgetExhaustedError",
]


class InputManifestDriftError(Exception):
    """The input snapshot no longer matches what was enqueued — the job
    cannot safely continue or complete."""


class LeaseFencedError(Exception):
    """P09.1: a lease-protected state update was fenced out.

    The caller's (job_id, lease_token, lease_worker, unexpired) fence no
    longer matches the row at write time — the lease was taken over,
    expired, or the job moved to a terminal state. Fail-closed: nothing
    was written. The caller must re-lease (or accept the outcome) before
    acting again; a fenced call is never a silent no-op and never
    retried in place.
    """


def _now() -> float:
    return time.time()


class DurableJobQueue:
    """One durable job table in one SQLite file (the caller's path)."""

    #: P12.2-D (Phase 4 C3): deterministic exponential backoff for
    #: re-queued jobs. `backoff_seconds(job)` = BASE * 2 ** retry_count,
    #: capped at MAX. The consumer applies the interval; the queue only
    #: COMPUTES it (one schedule, no caller-invented math).
    BASE_BACKOFF_S = 30
    MAX_BACKOFF_S = 3600

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Two concurrent writers (separate worker processes on one DB file)
        # must wait on each other's write lock rather than raising
        # "database is locked" — the CAS lease arbitration (see lease())
        # relies on the loser re-evaluating its WHERE against the winner's
        # committed row.
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._migrate_retry_budget_columns()

    def _migrate_retry_budget_columns(self) -> None:
        """P12.2-D (Phase 4 C3): databases created by an older build
        lack the `max_attempts` / `retry_count` columns; add them
        in place (NULL = legacy unbounded, 0 = no re-queues yet).
        Existing rows keep the old behavior: a NULL budget never
        exhausts."""
        cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(dit22_job)")
        }
        if "max_attempts" not in cols:
            self.conn.execute(
                "ALTER TABLE dit22_job ADD COLUMN max_attempts INTEGER"
            )
        if "retry_count" not in cols:
            self.conn.execute(
                "ALTER TABLE dit22_job ADD COLUMN retry_count INTEGER"
                " NOT NULL DEFAULT 0"
            )
            self.conn.execute(
                "UPDATE dit22_job SET retry_count = attempt WHERE "
                "retry_count = 0 AND attempt > 0"
            )
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
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        """P12.2-D (Phase 4 C3): `max_attempts` caps the job's total
        attempts (None = legacy unbounded; a value must be >= 1).
        Idempotent re-enqueue of the same key returns the existing row
        (its original budget — the cap is set at creation)."""
        manifest = manifest or {}
        if max_attempts is not None and max_attempts < 1:
            raise ValueError(
                "max_attempts must be >= 1 (or None for legacy "
                f"unbounded); got {max_attempts}"
            )
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
            " priority, reversible, state, attempt, checkpoint, seq, max_attempts)"
            " VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?)",
            (
                job_id,
                idempotency_key,
                name,
                json.dumps(manifest),
                priority,
                int(reversible),
                "{}",
                seq,
                max_attempts,
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
        #
        # CAS arbitration: the UPDATE's WHERE re-checks takeability *at write
        # time*, so two racers on the same PENDING/expired job cannot both win
        # — the first to commit flips state to an unexpired LEASED, the second's
        # WHERE no longer matches and rowcount is 0 => it loses. (SQLite's
        # WAL write lock serializes the two UPDATEs, so the loser re-evaluates
        # against the winner's committed row.) Cross-process fairness beyond
        # this lock remains deferred to ADR-DIT2-003.
        token = str(uuid.uuid4())
        cur = self.conn.execute(
            "UPDATE dit22_job SET state='LEASED', lease_token=?, lease_worker=?,"
            " lease_expires_at=?, attempt=attempt+1 WHERE job_id=? AND ("
            "   state IN ('PENDING','PAUSED')"
            "   OR (state='LEASED' AND (lease_expires_at IS NULL"
            "       OR lease_expires_at <= ?))"
            " )",
            (token, worker, now + ttl_seconds, job_id, now),
        )
        if cur.rowcount == 0:
            # Lost the CAS: someone else already took it (or it moved to a
            # terminal state) between our read and this write.
            fresh = self._row(job_id)
            raise LeaseHeldError(
                f"job {job_id} lease race lost (state={fresh['state']}, "
                f"holder={fresh['lease_worker']!r})"
            )
        self.conn.commit()
        return token

    # ── checkpoint / lifecycle (P09.1: fenced conditional writes) ───

    # The shared fence: at write time the row must still be LEASED to
    # this exact (token, worker) pair and still unexpired. `now` is
    # bound as the last parameter so the expiry check happens in the
    # same statement as the write.
    _FENCE_WHERE = (
        "WHERE job_id=? AND state='LEASED'"
        " AND lease_token=? AND lease_worker=?"
        " AND lease_expires_at IS NOT NULL AND lease_expires_at > ?"
    )

    def _fenced_update(
        self,
        job_id: str,
        worker: str,
        token: str,
        set_clause: str,
        set_params: tuple,
    ) -> int:
        """One conditional UPDATE carrying the full fence in its WHERE.
        Returns the rowcount; raises `LeaseFencedError` when 0 rows
        matched (fail-closed — the caller's fence is stale and NOTHING
        was written)."""
        cur = self.conn.execute(
            f"UPDATE dit22_job SET {set_clause} {self._FENCE_WHERE}",
            set_params + (job_id, token, worker, _now()),
        )
        if cur.rowcount == 0:
            fresh = self._row(job_id)
            raise LeaseFencedError(
                f"job {job_id}: lease fence failed — expected holder "
                f"{worker!r} with an unexpired lease matching the caller's "
                f"token, but the row is now state={fresh['state']!r}, "
                f"holder={fresh['lease_worker']!r}. Nothing was written; "
                f"re-lease before acting again."
            )
        return cur.rowcount

    def update_checkpoint(
        self,
        job_id: str,
        worker: str,
        checkpoint: dict[str, Any],
        *,
        token: str,
    ) -> None:
        row = self._row(job_id)
        self._assert_leased_to(row, worker, token)
        self._fenced_update(
            job_id, worker, token,
            "checkpoint=?",
            (json.dumps(checkpoint),),
        )
        self.conn.commit()

    def pause(self, job_id: str, worker: str, *, token: str) -> None:
        row = self._row(job_id)
        self._assert_leased_to(row, worker, token)
        self._fenced_update(
            job_id, worker, token,
            "state='PAUSED', lease_token=NULL, lease_worker=NULL,"
            " lease_expires_at=NULL",
            (),
        )
        self.conn.commit()

    def fail(self, job_id: str, worker: str, reason: str, *, token: str) -> None:
        row = self._row(job_id)
        self._assert_leased_to(row, worker, token)
        self._fenced_update(
            job_id, worker, token,
            "state='FAILED', fail_reason=?,"
            " lease_token=NULL, lease_worker=NULL, lease_expires_at=NULL",
            (reason,),
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

    def complete(
        self,
        job_id: str,
        worker: str,
        actual_manifest: dict[str, str],
        *,
        token: str,
    ) -> bool:
        """Finish the job after re-checking the input snapshot.
        Both outcomes are fenced: only the current lease holder may
        record DONE — or record FAILED for drift. Drift => `False` +
        FAILED (never 'done' on changed inputs)."""
        row = self._row(job_id)
        self._assert_leased_to(row, worker, token)
        try:
            self.verify_manifest(job_id, actual_manifest)
        except InputManifestDriftError:
            self._fenced_update(
                job_id, worker, token,
                "state='FAILED', fail_reason='input manifest drift', "
                "lease_token=NULL, lease_worker=NULL, lease_expires_at=NULL",
                (),
            )
            self.conn.commit()
            return False
        self._fenced_update(
            job_id, worker, token,
            "state='DONE', lease_token=NULL, lease_worker=NULL,"
            " lease_expires_at=NULL",
            (),
        )
        self.conn.commit()
        return True

    def retry(self, job_id: str, authorize_manual: bool = False) -> bool:
        """Re-queue a FAILED job. Irreversible jobs refuse ALL retries
        (the flag authorizes a human START, not a rewrite of history —
        the manual path is a fresh job under a new key).

        P12.2-D (Phase 4 C3): a REVERSIBLE job with a `max_attempts`
        budget refuses re-queues once its total attempts (the original
        run + every re-queue) reach the cap — a saturated backend must
        not be hammered forever. The backoff before the NEXT attempt
        is `backoff_seconds`. Legacy jobs (budget NULL) keep the old
        unbounded behavior."""
        row = self._row(job_id)
        if row["state"] != "FAILED":
            return False
        if not row["reversible"]:
            raise IrreversibleRetryError(
                f"job {job_id} is irreversible; start a fresh job with a new "
                "idempotency key instead of retrying this record"
            )
        budget = row["max_attempts"]
        if budget is not None and row["attempt"] >= budget:
            raise RetryBudgetExhaustedError(
                f"job {job_id} used all {budget} allowed attempts "
                f"(attempt={row['attempt']}); the record is terminal — "
                "start a fresh job under a new idempotency key if the "
                "work is still required (C3: no unbounded retry loops)"
            )
        self.conn.execute(
            "UPDATE dit22_job SET state='PENDING', fail_reason=NULL, "
            "retry_count = COALESCE(retry_count, 0) + 1 WHERE job_id=?",
            (job_id,),
        )
        self.conn.commit()
        return True

    def backoff_seconds(self, job_id: str) -> int:
        """P12.2-D (Phase 4 C3): deterministic exponential backoff to
        wait BEFORE the next attempt after `job_id`'s current failure:
        `BASE_BACKOFF_S * 2 ** retry_count`, capped at
        `MAX_BACKOFF_S`. Saturated-resource jobs must back off, not
        loop. (A wall-clock wait is the consumer's job; this is the
        computed interval, kept in one place so no caller invents its
        own schedule.)"""
        row = self._row(job_id)
        k = max(0, row.get("retry_count") or 0)
        return min(self.BASE_BACKOFF_S * (2 ** k), self.MAX_BACKOFF_S)

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
            " lease_expires_at, checkpoint, fail_reason, seq,"
            " COALESCE(max_attempts, NULL), COALESCE(retry_count, 0)"
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
            "max_attempts": r[14],
            "retry_count": r[15],
        }

    def _assert_leased_to(self, row: dict[str, Any], worker: str, token: str) -> None:
        """Advisory pre-check of the full fence, raising `LeaseFencedError`
        on ANY miss (terminal state, holder change, expiry, or token
        mismatch) with an accurate diagnostic. The authoritative
        protection is the conditional UPDATE in `_fenced_update` — its
        WHERE re-checks the fence atomically at write time, so a state
        change between this read and the write is still fenced. A miss
        here is fail-closed: nothing is written and the caller must
        re-lease before acting again."""
        now = _now()
        unexpired = (
            row["lease_expires_at"] is not None and now < row["lease_expires_at"]
        )
        if row["state"] != "LEASED" or row["lease_worker"] != worker or not unexpired:
            raise LeaseFencedError(
                f"job {row['job_id']} is not leased to {worker!r} "
                f"(state={row['state']}, holder={row['lease_worker']!r}); "
                f"fence check failed, nothing will be written"
            )
        if row["lease_token"] != token:
            raise LeaseFencedError(
                f"job {row['job_id']}: caller token does not match the held "
                f"lease (holder={row['lease_worker']!r}); re-lease before "
                f"acting again"
            )
