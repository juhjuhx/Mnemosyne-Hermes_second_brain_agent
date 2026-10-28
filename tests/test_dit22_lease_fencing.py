"""P09.1 — lease fencing contract tests.

The P09.1 spec addendum
(`docs/engineering/spec/P09-durable-job-queue.md`, P09.1 section)
requires every lease-protected state update (`update_checkpoint` /
`pause` / `fail` / `complete`) to be a single conditional UPDATE that
re-checks the full fence (job_id + lease_token + lease_worker +
state + lease_expires_at) at write time; `rowcount = 0` must
fail-closed with `LeaseFencedError`.

These tests first RED against the P09 implementation (which still
compares only the worker *name*): they reproduce a stale token
overwriting the new holder's state, and a same-name restart race.
"""

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from job_queue import (
    DurableJobQueue,
    LeaseFencedError,
)


def _q(tmp_path: Path, name: str = "q.db") -> DurableJobQueue:
    return DurableJobQueue(tmp_path / name)


def _expired_lease(q: DurableJobQueue, key: str) -> tuple[str, str, str]:
    """Create + lease a job with a zero TTL so its lease is already
    expired by the time any later assertion runs. Returns
    (job_id, worker, token)."""
    job = q.enqueue("x", idempotency_key=key)
    token = q.lease(job["job_id"], worker="w1", ttl_seconds=0)
    return job["job_id"], "w1", token


# ── scenario 1: stale token after cross-worker takeover ─────────────


@pytest.mark.behavior_tested
def test_stale_token_checkpoint_after_takeover_is_fenced(tmp_path):
    q = _q(tmp_path)
    job_id, worker, stale = _expired_lease(q, "k1")
    # w2 takes over the expired lease (crash recovery path).
    q.lease(job_id, worker="w2")
    # w1's old token must no longer be able to write a checkpoint.
    with pytest.raises(LeaseFencedError):
        q.update_checkpoint(job_id, worker, {"phase": "stale"}, token=stale)
    st = q.job_state(job_id)
    assert st["state"] == "LEASED" and st["lease_worker"] == "w2"
    assert st["checkpoint"] == {}, "stale checkpoint must not have landed"


@pytest.mark.behavior_tested
def test_stale_token_pause_and_fail_after_takeover_are_fenced(tmp_path):
    q = _q(tmp_path)
    job_id, worker, stale = _expired_lease(q, "k2")
    q.lease(job_id, worker="w2")
    with pytest.raises(LeaseFencedError):
        q.pause(job_id, worker, token=stale)
    with pytest.raises(LeaseFencedError):
        q.fail(job_id, worker, token=stale, reason="stale")
    st = q.job_state(job_id)
    assert st["state"] == "LEASED" and st["lease_worker"] == "w2", \
        "stale pause/fail must not disturb the new holder"


# ── scenario 2: same worker NAME restart ─────────────────────────────


@pytest.mark.behavior_tested
def test_same_worker_name_restart_invalidates_old_incarnation(tmp_path):
    """A worker that restarts re-leases under the SAME name. The old
    process's token must be dead even though its name matches —
    name is not a fencing token, the (new) lease_token is."""
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k3")
    old_token = q.lease(job["job_id"], worker="w", ttl_seconds=0)
    # restart: same name, new lease.
    new_token = q.lease(job["job_id"], worker="w")
    assert new_token != old_token
    st = q.job_state(job["job_id"])
    assert st["attempt"] == 2
    # old incarnation's writes are fenced; new one's are accepted.
    with pytest.raises(LeaseFencedError):
        q.update_checkpoint(job["job_id"], "w", {"old": 1}, token=old_token)
    q.update_checkpoint(job["job_id"], "w", {"new": 2}, token=new_token)
    assert q.job_state(job["job_id"])["checkpoint"] == {"new": 2}


# ── scenario 3: two handles on one file ──────────────────────────────


@pytest.mark.behavior_tested
def test_stale_token_across_two_connections_is_fenced(tmp_path):
    db = tmp_path / "q.db"
    q1 = DurableJobQueue(db)
    job = q1.enqueue("x", idempotency_key="k4")
    stale = q1.lease(job["job_id"], worker="w1", ttl_seconds=0)
    q1.close()

    q2 = DurableJobQueue(db)  # a second process's handle
    q2.lease(job["job_id"], worker="w2")
    q1b = DurableJobQueue(db)  # the 'old' process reconnects with stale state
    with pytest.raises(LeaseFencedError):
        q1b.complete(job["job_id"], "w1", {}, token=stale)
    st = q2.job_state(job["job_id"])
    assert st["state"] == "LEASED" and st["lease_worker"] == "w2", \
        "a stale complete must not flip state or clear the new holder"
    q1b.close()
    q2.close()


# ── scenario 4: complete after expiry by the old holder ────────────


@pytest.mark.behavior_tested
def test_complete_after_expiry_by_old_holder_is_fenced(tmp_path):
    q = _q(tmp_path)
    job_id, worker, stale = _expired_lease(q, "k5")
    q.lease(job_id, worker="w2")
    with pytest.raises(LeaseFencedError):
        q.complete(job_id, worker, {}, token=stale)
    st = q.job_state(job_id)
    assert st["state"] == "LEASED" and st["lease_worker"] == "w2"
    assert st["fail_reason"] is None, \
        "a stale writer must not be able to FAIL the job either"


# ── scenario 5: regression — drift with a VALID token still works ──


@pytest.mark.behavior_tested
def test_complete_drift_with_valid_token_still_fails_job(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", {"a": "11" * 32}, idempotency_key="k6")
    tok = q.lease(job["job_id"], worker="w")
    ok = q.complete(job["job_id"], "w", {"a": "22" * 32}, token=tok)
    assert ok is False
    st = q.job_state(job["job_id"])
    assert st["state"] == "FAILED" and st["fail_reason"] == "input manifest drift"


@pytest.mark.behavior_tested
def test_complete_match_with_valid_token_done(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", {"a": "11" * 32}, idempotency_key="k7")
    tok = q.lease(job["job_id"], worker="w")
    assert q.complete(job["job_id"], "w", {"a": "11" * 32}, token=tok) is True
    assert q.job_state(job["job_id"])["state"] == "DONE"


# ── scenario 6: regression — happy paths with a valid token ─────────


@pytest.mark.behavior_tested
def test_valid_token_checkpoint_pause_fail_paths_unchanged(tmp_path):
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k8")
    tok = q.lease(job["job_id"], worker="w")
    q.update_checkpoint(job["job_id"], "w", {"p": 1}, token=tok)
    q.pause(job["job_id"], "w", token=tok)
    assert q.job_state(job["job_id"])["state"] == "PAUSED"
    # resume: re-lease (same or new name), valid token of the NEW lease.
    tok2 = q.lease(job["job_id"], worker="w")
    q.fail(job["job_id"], "w", "boom", token=tok2)
    st = q.job_state(job["job_id"])
    assert st["state"] == "FAILED" and st["fail_reason"] == "boom"


@pytest.mark.behavior_tested
def test_fenced_callers_cannot_silently_succeed(tmp_path):
    """rowcount=0 must NEVER be swallowed: every fenced path raises.
    A stale token on a DONE/FAILED/unknown-state job still raises
    (fail-closed), it is not treated as a benign no-op."""
    q = _q(tmp_path)
    job = q.enqueue("x", idempotency_key="k9")
    tok = q.lease(job["job_id"], worker="w")
    q.fail(job["job_id"], "w", "x", token=tok)
    # job is now FAILED; even the token that was valid before must be
    # fenced on any state update — only retry() may move it forward.
    with pytest.raises(LeaseFencedError):
        q.update_checkpoint(job["job_id"], "w", {}, token=tok)
