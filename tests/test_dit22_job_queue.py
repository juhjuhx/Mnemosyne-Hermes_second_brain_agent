"""P09 durable job control — contract tests for `job_queue.DurableJobQueue`.

Covers the P09 spec (docs/engineering/spec/P09-durable-job-queue.md):
idempotent enqueue, exclusive lease with expiry takeover, checkpoint
re-entry, input-manifest drift rejection, the irreversibility rule
(no automatic retry of irreversible jobs), and full isolation from the
v4 indexer database.

Pure stdlib SQLite. No daemon, no network, no real media. The queue is
worker-agnostic: it stores job state; a consumer (worker pool, P09+
orchestrator) drives lease/complete.
"""

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from job_queue import (
    DurableJobQueue,
    IrreversibleRetryError,
    LeaseHeldError,
)


def _q(tmp_path: Path, name: str = "q.db") -> DurableJobQueue:
    return DurableJobQueue(tmp_path / name)


# ── 1. idempotency ───────────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_same_idempotency_key_reuses_job_id(tmp_path):
    q = _q(tmp_path)
    j1 = q.enqueue("ingest", {"a.mov": "ab" * 32}, idempotency_key="k1")
    j2 = q.enqueue("ingest", {"a.mov": "ab" * 32}, idempotency_key="k1")
    assert j1["job_id"] == j2["job_id"]
    assert q.count_jobs() == 1, "idempotent re-enqueue must not add a row"


@pytest.mark.behavior_tested
def test_distinct_keys_distinct_jobs(tmp_path):
    q = _q(tmp_path)
    a = q.enqueue("x", idempotency_key="ka")
    b = q.enqueue("x", idempotency_key="kb")
    assert a["job_id"] != b["job_id"]
    assert q.count_jobs() == 2


# ── 2. lease exclusivity ────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_double_lease_by_unexpired_holds_raises(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k")
    token = q.lease(job["job_id"], worker="w1")
    assert token is not None
    with pytest.raises(LeaseHeldError):
        q.lease(job["job_id"], worker="w2")


@pytest.mark.behavior_tested
def test_expired_lease_can_be_taken_over(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k")
    q.lease(job["job_id"], worker="w1", ttl_seconds=0)  # expires immediately
    tok2 = q.lease(job["job_id"], worker="w2")
    assert tok2 is not None, "expired lease must be takeable by another worker"
    st = q.job_state(job["job_id"])
    assert st["state"] == "LEASED"
    assert st["attempt"] == 2, "takeover increments attempt"


@pytest.mark.behavior_tested
def test_re_lease_own_valid_lease_is_noop(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k")
    q.lease(job["job_id"], worker="w1", ttl_seconds=600)
    q.lease(job["job_id"], worker="w1")  # same worker, unexpired
    st = q.job_state(job["job_id"])
    assert st["attempt"] == 1, "re-owning an unexpired lease must not add attempts"


@pytest.mark.behavior_tested
def test_cas_second_stale_take_lease_cannot_win(tmp_path):
    """The P09 review flagged the read-then-update lease path: two
    processes that both believe a PENDING job is free could each commit
    a live lease. `lease()` now ends with a CAS UPDATE whose WHERE
    re-checks takeability *at write time*. Fire that exact UPDATE twice
    back-to-back: the FIRST must match (row is PENDING), the SECOND
    must not (row is now LEASED-unexpired) => only one live lease is
    ever set, and `attempt` increments once, not twice.

    Run on a single connection so the ordering is deterministic: the
    second UPDATE sees the first's committed-in-transaction state.
    """
    import time

    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k")
    now = time.time()
    # The exact take-lease UPDATE that lease() issues.
    sql = (
        "UPDATE dit22_job SET state='LEASED', lease_token=?, lease_worker=?,"
        " lease_expires_at=?, attempt=attempt+1 WHERE job_id=? AND ("
        "   state IN ('PENDING','PAUSED')"
        "   OR (state='LEASED' AND (lease_expires_at IS NULL"
        "       OR lease_expires_at <= ?))"
        " )"
    )
    first = q.conn.execute(sql, ("tok-A", "wA", now + 300, job["job_id"], now))
    second = q.conn.execute(sql, ("tok-B", "wB", now + 300, job["job_id"], now))
    q.conn.commit()
    assert first.rowcount == 1, "the PENDING take must match"
    assert second.rowcount == 0, "a stale second take must NOT match"
    st = q.job_state(job["job_id"])
    assert st["state"] == "LEASED"
    assert st["lease_worker"] == "wA", "the first writer is the sole holder"
    assert st["attempt"] == 1, "a lost race must not add a second attempt"


@pytest.mark.behavior_tested
def test_expired_takeover_via_second_connection_bumps_attempt_once(tmp_path):
    """A worker crash (expired lease) is takeable across connections,
    and the takeover increments `attempt` exactly once. A second
    DurableJobQueue on the same file proves state survives the first
    process going away."""
    db = tmp_path / "q.db"
    q1 = DurableJobQueue(db)
    job = q1.enqueue("x", idempotency_key="k")
    q1.lease(job["job_id"], worker="crashed", ttl_seconds=0)  # expires now
    q1.close()

    q2 = DurableJobQueue(db)  # a fresh process reconnecting
    tok = q2.lease(job["job_id"], worker="recoverer")
    assert tok is not None
    st = q2.job_state(job["job_id"])
    assert st["state"] == "LEASED"
    assert st["lease_worker"] == "recoverer"
    assert st["attempt"] == 2, "crash takeover = the second lease of this job"


# ── 3. checkpoint + pause/resume ───────────────────────────────────


@pytest.mark.behavior_tested
def test_checkpoint_survives_pause_resume(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k")
    tok = q.lease(job["job_id"], worker="w")
    q.update_checkpoint(job["job_id"], worker="w",
                        checkpoint={"done": ["a.mov"], "next": "b.mov"},
                        token=tok)
    q.pause(job["job_id"], worker="w", token=tok)
    st = q.job_state(job["job_id"])
    assert st["state"] == "PAUSED"
    q.lease(job["job_id"], worker="w2")
    st = q.job_state(job["job_id"])
    assert st["state"] == "LEASED"
    assert st["checkpoint"]["done"] == ["a.mov"], "resume must keep checkpoint"


# ── 4. input-manifest drift ─────────────────────────────────────────


@pytest.mark.behavior_tested
def test_complete_with_drifted_manifest_fails_job(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", {"a": "11" * 32}, idempotency_key="k")
    tok = q.lease(job["job_id"], worker="w")
    # The input snapshot on disk no longer matches what was enqueued:
    ok = q.complete(job["job_id"], worker="w",
                    actual_manifest={"a": "22" * 32}, token=tok)
    assert ok is False
    assert q.job_state(job["job_id"])["state"] == "FAILED"


@pytest.mark.behavior_tested
def test_complete_with_matching_manifest_done(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", {"a": "11" * 32}, idempotency_key="k")
    tok = q.lease(job["job_id"], worker="w")
    assert q.complete(job["job_id"], worker="w",
                     actual_manifest={"a": "11" * 32}, token=tok) is True
    assert q.job_state(job["job_id"])["state"] == "DONE"


# ── 5. irreversibility rule ─────────────────────────────────────────


@pytest.mark.behavior_tested
def test_irreversible_failed_job_refuses_retry(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k", reversible=False)
    tok = q.lease(job["job_id"], worker="w")
    q.fail(job["job_id"], worker="w", token=tok, reason="hardware loss")
    assert q.job_state(job["job_id"])["state"] == "FAILED"
    with pytest.raises(IrreversibleRetryError):
        q.retry(job["job_id"], authorize_manual=False)


@pytest.mark.behavior_tested
def test_irreversible_job_can_be_restarted_only_with_new_key(tmp_path):
    """The ONLY path after an irreversible failure: a human starts a
    fresh job (new idempotency key). Retry of the same job stays
    refused even 'authorized' — authorization applies to re-enqueue,
    not to rewriting history."""
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k", reversible=False)
    tok = q.lease(job["job_id"], worker="w")
    q.fail(job["job_id"], worker="w", token=tok, reason="x")
    with pytest.raises(IrreversibleRetryError):
        q.retry(job["job_id"], authorize_manual=True)
    # Fresh, distinct work:
    new_job = q.enqueue("x", idempotency_key="k-v2", reversible=False)
    assert new_job["job_id"] != job["job_id"]
    assert q.job_state(new_job["job_id"])["state"] == "PENDING"


@pytest.mark.behavior_tested
def test_reversible_failed_job_can_retry(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k")  # reversible default
    tok = q.lease(job["job_id"], worker="w")
    q.fail(job["job_id"], worker="w", token=tok, reason="transient")
    assert q.retry(job["job_id"]) is True
    assert q.job_state(job["job_id"])["state"] == "PENDING"


# ── 6. priority + FIFO within priority ─────────────────────────────


@pytest.mark.behavior_tested
def test_highest_priority_enqueued_first_fifo_within(tmp_path):
    q = _q(tmp_path)
    q.enqueue("low", idempotency_key="a", priority=1)
    q.enqueue("high", idempotency_key="b", priority=5)
    q.enqueue("mid", idempotency_key="c", priority=3)
    q.enqueue("mid2", idempotency_key="d", priority=3)
    order = [j["job_id"] for j in q.claim_next_batch(4)]
    keys = [q.job_state(jid)["idempotency_key"] for jid in order]
    assert keys == ["b", "c", "d", "a"], \
        "high(5) then FIFO of mid(3): c before d, low(1) last"


# ── 7. v4 isolation ─────────────────────────────────────────────────


@pytest.mark.behavior_tested
def test_queue_never_touches_v4_database(tmp_path, monkeypatch):
    """The v4 index db path must never be opened by the queue — even if
    it exists. Monkeypatch sqlite3.connect to detect any open on a path
    that is not the queue's own file."""
    import sqlite3

    real_connect = sqlite3.connect
    v4_path = tmp_path / "v4_files.db"
    v4_path.write_text("")  # exists on disk; queue must still ignore it
    opened: list[str] = []

    def spy_connect(path, *a, **k):
        opened.append(str(path))
        return real_connect(path, *a, **k)

    monkeypatch.setattr(sqlite3, "connect", spy_connect)
    q = DurableJobQueue(tmp_path / "dit22_jobs.db")
    job = q.enqueue("x", idempotency_key="k")
    q.lease(job["job_id"], worker="w")
    for p in opened:
        assert "v4_files.db" not in p, f"queue opened a v4 path: {p}"
