"""P11.1-C — Crash/Recovery of proxy publication: 11 behavior-level RED tests.

These tests do NOT import anything that does not exist yet; they run against
the real on-disk layout that proxy_generator writes, and they assert *behavior*
(report contents + post-recovery on-disk state), not just "module exists".
Against the current stub they all FAIL on a real assertion (red evidence).

Layout under test (from proxy_generator, formal job, source stem "m",
browser profile):
  published : out/{job}__m__browser.mp4
  receipt   : out/{job}__m__browser.mp4.receipt.json   (single commit record)
  staged    : out/.staging/{job}/{generation_tag(token)}/{job}__m__browser.mp4

Recovery contract under test (P11.1-C spec):
  - reconcile is READ-ONLY; it re-derives every path from root+job+token
    (never from receipt argv), and classifies the slot.
  - apply mutates ONLY under a live lease (P09.1) and NEVER clobbers a
    verified-healthy published artifact or another job's files.
  - A receipt is not proof; a complete generation (hash-matching artifact +
    matching receipt + valid commit) is.
  - Cross-FS/queue transactions are NOT atomic here; recovery is replayable.

Markers: `@behavior_tested` — synthetic bytes only; no real media, no v4,
no cloud. Windows/UNC/SMB persistence stays HARDWARE_BLOCKED (asserted, not
pretended).
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

import job_queue
from artifact_recovery import (
    ISSUE_CORRUPT_RECEIPT,
    ISSUE_FOREIGN_RECEIPT,
    ISSUE_HASH_MISMATCH,
    ISSUE_PENDING_RENAME,
    ISSUE_SHA_DRIFT,
    ISSUE_UNATTRIBUTABLE,
    ISSUE_UNSAFE_PATH,
    ISSUE_ZOMBIE_STAGING,
    apply_recovery,
    reconcile_proxy_job,
)
from proxy_generator import generation_tag

_PROF = "browser"
_EXT = ".mp4"
_STEM = "m"


def _artname(job: str) -> str:
    return f"{job}__{_STEM}__{_PROF}{_EXT}"


def _published(out: Path, job: str) -> Path:
    return out / _artname(job)


def _receipt(out: Path, job: str) -> Path:
    return out / f"{_artname(job)}.receipt.json"


def _staged(out: Path, job: str, token: str) -> Path:
    return out / ".staging" / job / generation_tag(token) / _artname(job)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _lease(tmp_path: Path, key: str = "j") -> tuple:
    q = job_queue.DurableJobQueue(tmp_path / "jobs.db")
    row = q.enqueue("proxy", idempotency_key=key)
    job = row["job_id"]
    tok = q.lease(job, "w1")
    return q, job, tok


def _write_receipt(out: Path, job: str, token: str, proxy_sha: str,
                   *, argv_last: str | None = None, corrupt: bool = False) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = _receipt(out, job)
    if corrupt:
        p.write_text("\x00\x01garbage-not-json")
        return p
    rec = {
        "job_id": job,
        "lease_token": token,
        "source_sha256": "s",
        "proxy_sha256": proxy_sha,
        "profile": _PROF,
        "container": "mp4",
        "codec": "h264",
        "degraded": False,
        "ffmpeg_version": "t",
        "status": "published",
        "argv": ["ffmpeg", "-hide_banner", "-i",
                 argv_last if argv_last is not None else str(_staged(out, job, token))],
    }
    p.write_text(json.dumps(rec, ensure_ascii=False))
    return p


def _expire(q, job: str) -> None:
    q.conn.execute("UPDATE dit22_job SET lease_expires_at=? WHERE job_id=?",
                   (time.time() - 5, job))
    q.conn.commit()


# ── N1: receipt-first crash window ─────────────────────────────────


@pytest.mark.behavior_tested
def test_n1_receipt_written_artifact_not_exposed(tmp_path):
    q, job, tok = _lease(tmp_path)
    out = tmp_path / "out"
    data = b"gen-artifact-bytes"
    st = _staged(out, job, tok)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_bytes(data)
    _write_receipt(out, job, tok, _sha(data))
    assert not _published(out, job).exists()  # crash between receipt write + rename

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert not rep.is_published()
    assert ISSUE_PENDING_RENAME in rep.issues_by_kind()

    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    assert res.completed is True
    assert _published(out, job).exists()
    assert _sha(_published(out, job).read_bytes()) == _sha(data)
    rep2 = reconcile_proxy_job(out, job, expected_token=tok)
    assert rep2.is_published() and rep2.published_sha == _sha(data)


# ── N2: proxy/receipt hash mismatch ────────────────────────────────


@pytest.mark.behavior_tested
def test_n2_exposed_artifact_hash_mismatch(tmp_path):
    q, job, tok = _lease(tmp_path)
    out = tmp_path / "out"
    _write_receipt(out, job, tok, _sha(b"promised-hash"))
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(b"actual-differs")

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert not rep.is_published()
    assert ISSUE_HASH_MISMATCH in rep.issues_by_kind()

    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    # a mismatched artifact must NOT be accepted as published, and it must
    # not be silently deleted: it is quarantined (moved, evidence kept).
    assert res.completed is False
    assert len(res.quarantined) > 0
    assert not _published(out, job).exists()


# ── N3: old healthy generation survives a new interrupted one ─────


@pytest.mark.behavior_tested
def test_n3_healthy_published_not_clobbered_by_failed_retry(tmp_path):
    q, job, _ = _lease(tmp_path, key="j3")
    out = tmp_path / "out"
    # a fully-healthy published gen A (receipt + exposed + matching hash):
    healthy = b"healthy-old-gen"
    tok_a = "tok-A"
    _write_receipt(out, job, tok_a, _sha(healthy))
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(healthy)
    # a failed retry B left only staging residue (its encode died before
    # any receipt); B's gen is a zombie, not a commit:
    zombie = b"zombie-b-partial"
    zk = _staged(out, job, "tok-B")
    zk.parent.mkdir(parents=True, exist_ok=True)
    zk.write_bytes(zombie)

    rep = reconcile_proxy_job(out, job, expected_token=tok_a)
    assert rep.is_published() and rep.published_sha == _sha(healthy)
    assert ISSUE_ZOMBIE_STAGING in rep.issues_by_kind()

    # recovery under the LIVE gen A's owner must preserve A, discard B:
    _expire(q, job)
    live = q.lease(job, "wA", ttl_seconds=60)
    res = apply_recovery(out, job, rep, queue=q, worker="wA", token=live)
    assert _sha(_published(out, job).read_bytes()) == _sha(healthy), \
        "the healthy published version must survive a failed retry"
    assert not zk.exists(), "zombie staging must be discarded"
    assert zk.parent in [Path(p) for p in res.discarded], \
        "the zombie generation dir must be in the discarded set"


# ── N4: corrupt receipt / unattributable orphan proxy ────────────


@pytest.mark.behavior_tested
def test_n4a_published_artifact_with_no_receipt(tmp_path):
    q, job, tok = _lease(tmp_path, key="j4a")
    out = tmp_path / "out"
    orphan = b"orphan-proxy"
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(orphan)
    # no receipt at all

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert not rep.is_published()
    assert ISSUE_UNATTRIBUTABLE in rep.issues_by_kind()

    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    # an unattributable proxy is quarantined (evidence kept), never deleted:
    assert res.completed is False
    assert len(res.quarantined) > 0
    assert not _published(out, job).exists()
    qdir = out / ".quarantine"
    assert qdir.is_dir(), "quarantined evidence must be preserved on disk"
    assert any(qdir.iterdir()), "quarantine dir must not be empty"


@pytest.mark.behavior_tested
def test_n4b_exposed_artifact_with_undecodable_receipt(tmp_path):
    q, job, tok = _lease(tmp_path, key="j4b")
    out = tmp_path / "out"
    _write_receipt(out, job, tok, _sha(b"x"), corrupt=True)
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(b"some-artifact")

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert not rep.is_published()
    assert ISSUE_CORRUPT_RECEIPT in rep.issues_by_kind()
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    assert res.completed is False
    assert len(res.quarantined) > 0


# ── N5: zombie staging + expired lease (stale worker fenced) ─────


@pytest.mark.behavior_tested
def test_n5_zombie_staging_fenced_from_stale_worker(tmp_path):
    q, job, live = _lease(tmp_path, key="j5")
    out = tmp_path / "out"
    # a zombie's own token has no live lease (it was taken over / expired):
    zombie_tok = "tok-zombie"
    zk = _staged(out, job, zombie_tok)
    zk.parent.mkdir(parents=True, exist_ok=True)
    zk.write_bytes(b"zombie-residue")

    rep = reconcile_proxy_job(out, job, expected_token=live)
    assert ISSUE_ZOMBIE_STAGING in rep.issues_by_kind()

    # the live holder MAY discard the zombie residue:
    live2 = q.lease(job, "w1", ttl_seconds=60)
    res_live = apply_recovery(out, job, rep, queue=q, worker="w1", token=live2)
    assert not zk.exists()
    assert zk.parent in [Path(p) for p in res_live.discarded]

    # the STALE worker (zombie's own dead token) must be fenced from it:
    rep2 = reconcile_proxy_job(out, job, expected_token=zombie_tok)
    res_zombie = apply_recovery(out, job, rep2, queue=q, worker="zombie",
                                token=zombie_tok)
    assert res_zombie.completed is False
    assert "lease" in res_zombie.reason.lower()


# ── N6: process restart, token takeover, re-entry recovery ───────


@pytest.mark.behavior_tested
def test_n6_takeover_then_recovery_of_new_generation(tmp_path):
    q, job, _tok_a = _lease(tmp_path, key="j6")
    out = tmp_path / "out"
    _expire(q, job)                      # A's lease dies (worker restart)
    tok_b = q.lease(job, "wB", ttl_seconds=60)  # takeover, new generation
    payload = b"generation-b"
    st = _staged(out, job, tok_b)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_bytes(payload)
    _write_receipt(out, job, tok_b, _sha(payload))

    rep = reconcile_proxy_job(out, job, expected_token=tok_b)
    assert ISSUE_PENDING_RENAME in rep.issues_by_kind()
    res = apply_recovery(out, job, rep, queue=q, worker="wB", token=tok_b)
    assert res.completed is True
    assert _sha(_published(out, job).read_bytes()) == _sha(payload)
    assert reconcile_proxy_job(out, job, expected_token=tok_b).is_published()


# ── N7: forged argv[-1] / staged_path in the receipt ────────────


@pytest.mark.behavior_tested
def test_n7_forged_receipt_path_is_never_trusted(tmp_path):
    q, job, tok = _lease(tmp_path, key="j7")
    out = tmp_path / "out"
    evil = tmp_path / "OUTSIDE" / "evil.mp4"
    evil.parent.mkdir(parents=True, exist_ok=True)
    evil.write_bytes(b"do-not-touch-me")
    # receipt FORGES argv[-1] to point at the out-of-root file; the real
    # staged path (re-derived) holds the promised hash:
    st = _staged(out, job, tok)
    st.parent.mkdir(parents=True, exist_ok=True)
    good = b"good-recovery"
    st.write_bytes(good)
    _write_receipt(out, job, tok, _sha(good), argv_last=str(evil))

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    # recovery re-derives the safe path; it must NOT follow argv, and the
    # out-of-root file must be byte-identical afterwards:
    assert evil.read_bytes() == b"do-not-touch-me"
    assert res.completed is True
    assert _sha(_published(out, job).read_bytes()) == _sha(good)


# ── N8: path traversal / symlink staged path ────────────────────


@pytest.mark.behavior_tested
def test_n8_symlink_staged_path_is_refused(tmp_path):
    q, job, tok = _lease(tmp_path, key="j8")
    out = tmp_path / "out"
    outside = tmp_path / "outside-target.mp4"
    outside.write_bytes(b"outside-bytes")
    st = _staged(out, job, tok)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.symlink_to(outside)  # staged "file" is a symlink escaping the root

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert ISSUE_UNSAFE_PATH in rep.issues_by_kind()
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    assert res.completed is False
    assert not _published(out, job).exists(), "must not expose a symlink"
    assert outside.read_bytes() == b"outside-bytes"


# ── N9: lease last-check vs publish race -> sha drift at apply ──


@pytest.mark.behavior_tested
def test_n9_sha_drift_between_assessment_and_apply(tmp_path):
    q, job, tok = _lease(tmp_path, key="j9")
    out = tmp_path / "out"
    st = _staged(out, job, tok)
    st.parent.mkdir(parents=True, exist_ok=True)
    original = b"original-staged"
    st.write_bytes(original)
    _write_receipt(out, job, tok, _sha(original))
    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert ISSUE_PENDING_RENAME in rep.issues_by_kind()
    # the source rewrites the staged file after assessment (drift):
    st.write_bytes(b"drifted-content")
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    # the drifted artifact must NOT be published (the receipt promised the
    # original hash): refuse, and surface the drift.
    assert res.completed is False
    assert not _published(out, job).exists()
    assert "drift" in res.reason.lower() or ISSUE_SHA_DRIFT in \
        reconcile_proxy_job(out, job, expected_token=tok).issues_by_kind()


# ── N10: two recoveries must be idempotent ──────────────────────


@pytest.mark.behavior_tested
def test_n10_recovery_is_idempotent(tmp_path):
    q, job, tok = _lease(tmp_path, key="j10")
    out = tmp_path / "out"
    data = b"idempotent-gen"
    st = _staged(out, job, tok)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_bytes(data)
    _write_receipt(out, job, tok, _sha(data))
    rep = reconcile_proxy_job(out, job, expected_token=tok)
    r1 = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    assert r1.completed is True
    first_sha = _sha(_published(out, job).read_bytes())
    # second recovery is a no-op: same outcome, no corruption, no re-publish
    rep2 = reconcile_proxy_job(out, job, expected_token=tok)
    r2 = apply_recovery(out, job, rep2, queue=q, worker="w1", token=tok)
    assert _sha(_published(out, job).read_bytes()) == first_sha
    assert rep2.is_published() and rep2.published_sha == first_sha
    assert not st.exists()
    assert "complete_rename" not in r2.applied, \
        "a second recovery over a healthy publish must not re-rename"
    assert r2.completed is True


# ── N11: recovery never touches another job or a healthy publish ─


@pytest.mark.behavior_tested
def test_n11_recovery_does_not_touch_other_jobs(tmp_path):
    q = job_queue.DurableJobQueue(tmp_path / "jobs.db")
    row1 = q.enqueue("proxy1", idempotency_key="j11a")
    row2 = q.enqueue("proxy2", idempotency_key="j11b")
    job_a, job_b = row1["job_id"], row2["job_id"]
    out = tmp_path / "out"
    # job A is healthy & published:
    healthy_a = b"job-a-healthy"
    tok_a = q.lease(job_a, "wA", ttl_seconds=60)
    _write_receipt(out, job_a, tok_a, _sha(healthy_a))
    _published(out, job_a).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job_a).write_bytes(healthy_a)
    # job B has a pending gen to recover:
    tok_b = q.lease(job_b, "wB", ttl_seconds=60)
    payload_b = b"job-b-gen"
    st = _staged(out, job_b, tok_b)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_bytes(payload_b)
    _write_receipt(out, job_b, tok_b, _sha(payload_b))
    a_receipt_before = _receipt(out, job_a).read_text()

    rep = reconcile_proxy_job(out, job_b, expected_token=tok_b)
    res = apply_recovery(out, job_b, rep, queue=q, worker="wB", token=tok_b)
    assert res.completed is True
    # job B recovered:
    assert _sha(_published(out, job_b).read_bytes()) == _sha(payload_b)
    # job A byte-for-byte untouched (artifact + receipt):
    assert _sha(_published(out, job_a).read_bytes()) == _sha(healthy_a)
    assert _receipt(out, job_a).read_text() == a_receipt_before


# ── N12: receipt-overwrite shape (one shared receipt slot per job) ──
#
# proxy_generator writes the SAME out/{job}__...receipt.json for EVERY
# generation of a job+source+profile. A newer generation that writes its
# receipt in the receipt-first window but crashes before os.replace leaves:
#   published slot = OLDER gen's healthy bytes   (A)
#   receipt        = NEWER gen's promise         (B)
#   NEWER staged   = NEWER gen's bytes, sha==B   (B)
# A valid staged source is authoritative: it rotates in atomically under its
# OWN live lease (N12a), and is DEFERRED (BLOCKED) when the live holder is a
# DIFFERENT generation (N12b) — preserving the older healthy bytes. The older
# healthy version is NEVER unconditionally quarantined to empty the slot.


@pytest.mark.behavior_tested
def test_n12a_valid_newer_generation_rotates_in_under_own_lease(tmp_path):
    q, job, tok = _lease(tmp_path, key="j12a")
    out = tmp_path / "out"
    # gen A: a healthy published slot (its receipt was already overwritten):
    healthy_a = b"gen-A-healthy"
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(healthy_a)
    # gen B (the live holder's OWN gen): newer receipt + newer staged,
    # but its rename never landed:
    newer_b = b"gen-B-newer"
    st = _staged(out, job, tok)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_bytes(newer_b)
    _write_receipt(out, job, tok, _sha(newer_b))

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert ISSUE_PENDING_RENAME in rep.issues_by_kind()
    assert not rep.is_published()

    # the holder is completing its OWN generation -> atomic rotation in:
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    assert res.completed is True
    assert _sha(_published(out, job).read_bytes()) == _sha(newer_b), \
        "a valid newer generation under its own live lease rotates in"
    assert reconcile_proxy_job(out, job, expected_token=tok).is_published()


@pytest.mark.behavior_tested
def test_n12b_crashed_foreign_generation_is_blocked_older_preserved(tmp_path):
    q, job, tok_holder = _lease(tmp_path, key="j12b")
    out = tmp_path / "out"
    # gen A: a healthy published slot, preserved in place:
    healthy_a = b"gen-A-healthy"
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(healthy_a)
    # gen B is a CRASHED/foreign generation: its receipt + staged exist,
    # but the live lease holder is a DIFFERENT generation (tok_holder):
    tok_b = "tok-gen-B-dead"
    newer_b = b"gen-B-crashed"
    st_b = _staged(out, job, tok_b)
    st_b.parent.mkdir(parents=True, exist_ok=True)
    st_b.write_bytes(newer_b)
    _write_receipt(out, job, tok_b, _sha(newer_b))

    rep = reconcile_proxy_job(out, job, expected_token=tok_holder)
    assert ISSUE_PENDING_RENAME in rep.issues_by_kind()

    # the live holder is NOT gen B: B must not be auto-published, and A's
    # healthy artifact must not be quarantined/destroyed either:
    res = apply_recovery(out, job, rep, queue=q, worker="wC", token=tok_holder)
    assert res.completed is False
    assert len(res.deferred) > 0, "a foreign generation's pending is BLOCKED"
    assert _sha(_published(out, job).read_bytes()) == _sha(healthy_a), \
        "the healthy older version must survive a crashed foreign generation"
    assert st_b.exists() and _receipt(out, job).exists(), \
        "B's evidence is preserved, not destroyed"


# ── N13: a receipt in our namespace naming ANOTHER job ────────────


@pytest.mark.behavior_tested
def test_n13_foreign_job_receipt_never_confirm_nor_quarantine(tmp_path):
    q, job, tok = _lease(tmp_path, key="j13")
    out = tmp_path / "out"
    healthy = b"our-healthy"
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(healthy)
    _write_receipt(out, job, tok, _sha(healthy))   # our valid receipt
    # tamper: flip the receipt's job_id to a FOREIGN job under the same slot:
    rec = json.loads(_receipt(out, job).read_text())
    rec["job_id"] = "some-other-job"
    _receipt(out, job).write_text(json.dumps(rec))

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert ISSUE_FOREIGN_RECEIPT in rep.issues_by_kind()
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    # a foreign receipt cannot confirm OUR publish -> fail-closed, no auto
    # confirm; the artifact AND the (foreign) receipt are both preserved:
    assert res.completed is False
    assert _sha(_published(out, job).read_bytes()) == _sha(healthy), \
        "the artifact is preserved, not quarantined, when its receipt is foreign"
    assert _receipt(out, job).exists(), "the foreign receipt is preserved"


# ── N14: holder's live lease + a FOREIGN generation's pending receipt ──
#
# This drives the spec §4 deferred branch DIRECTLY (which N12b does NOT
# reach — N12b bails earlier at the lease fence because worker!=holder).
# Here the worker/token IS the live holder, so the lease check passes; the
# pending receipt belongs to a DIFFERENT (crashed) generation, which must
# be BLOCKED (deferred), never auto-published, while the older exposed
# bytes are preserved.


@pytest.mark.behavior_tested
def test_n14_live_holder_blocks_foreign_generation_pending(tmp_path):
    q, job, tok = _lease(tmp_path, key="j14")  # live lease: w1 / tok
    out = tmp_path / "out"
    # an older, healthy exposed artifact in the shared slot:
    older = b"older-healthy"
    _published(out, job).parent.mkdir(parents=True, exist_ok=True)
    _published(out, job).write_bytes(older)
    # a FOREIGN (crashed) generation B owns the pending receipt + staged:
    tok_b = "tok-gen-B-crashed"
    newer_b = b"gen-B-newer"
    st_b = _staged(out, job, tok_b)
    st_b.parent.mkdir(parents=True, exist_ok=True)
    st_b.write_bytes(newer_b)
    _write_receipt(out, job, tok_b, _sha(newer_b))

    rep = reconcile_proxy_job(out, job, expected_token=tok)
    assert ISSUE_PENDING_RENAME in rep.issues_by_kind()

    # the live holder (w1/tok) applies: lease passes, but the pending gen
    # is not the holder's own generation -> deferred (BLOCKED), not
    # auto-published, and the older exposed bytes are preserved.
    res = apply_recovery(out, job, rep, queue=q, worker="w1", token=tok)
    assert res.completed is False
    assert len(res.deferred) > 0, "a foreign generation's pending is BLOCKED"
    assert "lease fence" not in res.reason, \
        "this must be the generation-mismatch defer, not the lease fence"
    assert _sha(_published(out, job).read_bytes()) == _sha(older), \
        "the older healthy exposed bytes must survive a foreign pending"
    assert st_b.exists() and _receipt(out, job).exists(), \
        "the foreign generation's evidence is preserved, not destroyed"
