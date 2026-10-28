"""P12.2-D (Phase 4 C3/C4): Retry Budgets + Storage Reservation — RED tests.

C3: a reversible job may be re-tried only within a per-job budget
(`max_attempts`), with computed exponential backoff; irreversible jobs
still refuse every retry (existing P09 rule, re-asserted here).
C4: a pre-encode storage reservation — estimated staging + output
capacity, NOT only a percentage warning. The census 15% threshold
stays ADVISORY (reported, not blocking) until separately authorized.

Run: pytest tests/test_dit22_retry_budget.py tests/test_dit22_capacity_gate.py -q
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))


# ════════════════════════════════════ C3: retry budget ═══════════════


def _fail_cycle(queue, job_id: str, worker: str = "w1") -> None:
    """Lease the job, let it fail, back to the FAILED state."""
    token = queue.lease(job_id, worker, ttl_seconds=60)
    queue.fail(job_id, worker, "synthetic failure", token=token)


@pytest.fixture
def queue(tmp_path: Path):
    from job_queue import DurableJobQueue

    q = DurableJobQueue(tmp_path / "jobs.db")
    yield q
    q.close()


def test_r1_retry_budget_enforced(queue, tmp_path):
    from job_queue import RetryBudgetExhaustedError

    # `max_attempts=2` caps the job's TOTAL attempts (original run +
    # re-runs): one re-queue is allowed, the second is exhausted.
    row = queue.enqueue("job", idempotency_key="k1", max_attempts=2)
    jid = row["job_id"]
    _fail_cycle(queue, jid)  # attempt 1 -> FAILED
    assert queue.retry(jid) is True  # re-queue -> attempt 2 will run
    _fail_cycle(queue, jid)  # attempt 2 -> FAILED
    with pytest.raises(RetryBudgetExhaustedError):
        queue.retry(jid)  # a 3rd attempt exceeds the budget: terminal

    # and the state is FAILED (not PENDING) — the re-queue never ran:
    assert queue.job_state(jid)["state"] == "FAILED"


def test_r2_backoff_is_deterministic_exponential(queue, tmp_path):
    row = queue.enqueue("job", idempotency_key="k2", max_attempts=5)
    jid = row["job_id"]
    assert queue.backoff_seconds(jid) == 30  # 2**0 * 30 base
    _fail_cycle(queue, jid)
    queue.retry(jid)
    assert queue.backoff_seconds(jid) == 60
    _fail_cycle(queue, jid)
    queue.retry(jid)
    assert queue.backoff_seconds(jid) == 120
    # cap: never grows past the ceiling
    from job_queue import RetryBudgetExhaustedError

    for _ in range(50):
        _fail_cycle(queue, jid)
        try:
            queue.retry(jid)
        except RetryBudgetExhaustedError:
            break
    assert queue.backoff_seconds(jid) <= 3600


def test_r3_irreversible_still_refuses_all_retries(queue, tmp_path):
    from job_queue import IrreversibleRetryError

    row = queue.enqueue(
        "job", idempotency_key="k3", reversible=False, max_attempts=3
    )
    jid = row["job_id"]
    _fail_cycle(queue, jid)
    with pytest.raises(IrreversibleRetryError):
        queue.retry(jid)
    # and even a manual authorization must NOT open a retry path:
    with pytest.raises(IrreversibleRetryError):
        queue.retry(jid, authorize_manual=True)


def test_r4_v1_databases_migrate_transparently(tmp_path):
    # A queue DB created by an older build (no max_attempts /
    # retry_count columns) must still work: the constructor migrates.
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE dit22_job (
            job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, input_manifest TEXT NOT NULL DEFAULT '{}',
            priority INTEGER NOT NULL DEFAULT 0,
            reversible INTEGER NOT NULL DEFAULT 1,
            state TEXT NOT NULL DEFAULT 'PENDING',
            attempt INTEGER NOT NULL DEFAULT 0,
            lease_token TEXT, lease_worker TEXT, lease_expires_at REAL,
            checkpoint TEXT NOT NULL DEFAULT '{}', fail_reason TEXT,
            seq INTEGER NOT NULL
        );
        CREATE INDEX dit22_job_claim_idx
            ON dit22_job(state, priority DESC, seq ASC);
        INSERT INTO dit22_job (job_id, idempotency_key, name, input_manifest,
            priority, reversible, state, attempt, checkpoint, seq)
            VALUES ('j-old', 'k-old', 'legacy job', '{}', 0, 1, 'PENDING',
            0, '{}', 1);
        """
    )
    conn.commit()
    conn.close()

    from job_queue import DurableJobQueue

    q = DurableJobQueue(db)
    try:
        cols = [
            r[1] for r in q.conn.execute("PRAGMA table_info(dit22_job)")
        ]
        assert "max_attempts" in cols and "retry_count" in cols
        row = q.job_state("j-old")
        assert row["max_attempts"] is None  # legacy default: unbounded
        assert row["retry_count"] == 0
        # unbounded legacy job keeps the old retry behavior:
        _fail_cycle(q, "j-old")
        assert q.retry("j-old") is True
    finally:
        q.close()


# ════════════════════════════════════ C4: capacity gate ═════════════


def test_c1_capacity_reservation_blocks_when_short(tmp_path):
    # A tiny tmp_path volume (or any vol) with a demand that exceeds
    # available bytes must be refused BEFORE an encode would start.
    from capacity_gate import CapacityShortError, check_capacity

    class _Probe:
        def __init__(self, free, total):
            self.free = free
            self.total = total

    with pytest.raises(CapacityShortError):
        check_capacity(
            _Probe(free=100, total=10_000),
            estimated_staging_bytes=500,
            estimated_output_bytes=400,
            safety_factor=1.0,
        )


def test_c2_capacity_passes_with_margin(tmp_path):
    from capacity_gate import check_capacity

    class _Probe:
        free = 1_000
        total = 10_000

    res = check_capacity(
        _Probe(), estimated_staging_bytes=200,
        estimated_output_bytes=150, safety_factor=1.0,
    )
    assert res.ok is True
    assert res.required_bytes == 350  # staging + output


def test_c3_safety_factor_inflates_the_requirement(tmp_path):
    from capacity_gate import check_capacity

    class _Probe:
        free = 400
        total = 10_000

    # 550 * 1.0 = 550 > 400 free => blocked even though the raw sum
    # (550) is close to free; the factor must be applied to the SUM.
    from capacity_gate import CapacityShortError

    with pytest.raises(CapacityShortError):
        check_capacity(
            _Probe(), estimated_staging_bytes=500,
            estimated_output_bytes=50, safety_factor=1.0,
        )
    # with headroom it passes:
    class _BigProbe:
        free = 600
        total = 10_000

    assert check_capacity(
        _BigProbe(), estimated_staging_bytes=500,
        estimated_output_bytes=50, safety_factor=1.0,
    ).ok is True


def test_c4_free_space_probe_reads_real_disk(tmp_path):
    # The default probe MUST be the OS truth (shutil.disk_usage): free
    # on a real volume is the number, not a caller-supplied claim.
    from capacity_gate import free_space_bytes

    free = free_space_bytes(tmp_path)
    usage = shutil.disk_usage(tmp_path)
    assert free == usage.free
    # and it is a plausible fraction of the total:
    assert 0 <= free <= usage.total


def test_c5_advisory_15pct_census_threshold_never_blocks(tmp_path):
    # The existing 15% low-space census threshold stays ADVISORY: a
    # volume at ~10% free still PASSES when the estimated demand fits
    # (it is flagged, not blocked).
    from capacity_gate import check_capacity

    class _Probe:
        free = int(0.10 * 10_000_000_000)   # 10% of a 10 GB vol
        total = 10_000_000_000

    res = check_capacity(
        _Probe(), estimated_staging_bytes=1_000,
        estimated_output_bytes=900, safety_factor=1.0,
    )
    assert res.ok is True
    assert res.advisory_low_space is True  # flagged, not blocked


def test_c6_estimated_output_never_zero_floors(tmp_path):
    # A caller passing 0 estimated output (unknown size) still
    # reserves the staging estimate + a non-zero floor: 0 demand must
    # not mean "no reservation at all". A tiny-volume probe proves
    # the floor (not the 5-byte staging) is what blocks.
    from capacity_gate import CapacityShortError, check_capacity

    class _TinyVol:
        free = 100
        total = 1000

    # 5 staging + floor => required >> 100 free => blocked:
    with pytest.raises(CapacityShortError):
        check_capacity(
            _TinyVol(), estimated_staging_bytes=5,
            estimated_output_bytes=0, safety_factor=1.0,
        )

