"""artifact_recovery.py — DIT 2.2 P11.1-C: replayable proxy publish recovery.

A receipt is NOT standalone proof of success. The only thing that makes a
proxy slot PUBLISHED is a *complete generation*: a hash-matching artifact
plus a matching receipt, both re-derivable from on-disk truth. This module
re-derives that truth and offers a safe, replayable recovery path.

Two-call shape (assessment is read-only; mutation is lease-gated):

    report = reconcile_proxy_job(out_dir, job_id, expected_token=...)
    result = apply_recovery(out_dir, job_id, report,
                            queue=q, worker=w, token=tok)

Design rules (P11.1-C spec):
- `reconcile_proxy_job` NEVER writes. It returns the on-disk verdict.
- `apply_recovery` only mutates under a verified LIVE lease (P09.1
  semantics: state LEASED + holder + exact token + unexpired, read from
  the queue row). It re-reconciles and re-hashes at apply time, so a
  source change between assessment and apply (the last-check window) is
  caught, not trusted.
- No writable path is ever taken from a receipt's `argv`/`staged_path`.
  Every path is re-derived from the trusted output root + the job id
  (namespace prefix) + the receipt's lease_token (-> generation) + the
  receipt filename, and verified to be a regular, non-symlink file
  contained under the root. Out-of-bounds, symlink, and cross-volume
  targets are refused (N7/N8).
- A healthy published artifact — of this or any other job — is never
  clobbered by a failed or newer recovery; a stale worker can never
  trigger a mutation at all (no live lease => no mutation).
- Cross-filesystem + queue-DB transactions are NOT atomic on this host.
  This module does NOT claim a single `os.replace()` covers the whole
  transaction; it makes the pending state REPLAYABLE: after a
  receipt-first crash, the same on-disk inputs re-derive the same
  pending verdict and the same safe completion.
- Windows / UNC / SMB persistence and cross-share rename are
  HARDWARE_BLOCKED here (no real-device evidence on this M1 host);
  the report carries `hardware_blocked_platforms` and cross-volume
  renames are refused, not faked.

Layout expected (written by `proxy_generator`):
    published : out/{job}__{stem}__{profile}{ext}
    receipt   : out/{job}__{stem}__{profile}{ext}.receipt.json
    staged    : out/.staging/{job}/{generation_tag(token)}/{...}
    quarantined: out/.quarantine/{job}/...   (created by recovery)

This module is a pure add-on: it reads the layout proxy_generator writes,
never imports the v4 stack, never touches a real source, no cloud.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from proxy_generator import generation_tag

# HARDWARE_BLOCKED platforms: persistence / rename atomicity cannot be
# verified from this host; never pretend otherwise.
_HARDWARE_BLOCKED = ("windows-unc", "windows-smb", "cross-volume")

# Issue kinds the reconciler can report.
ISSUE_PENDING_RENAME = "pending_rename"     # receipt written, artifact not yet exposed
ISSUE_HASH_MISMATCH = "hash_mismatch"       # artifact present, sha != receipt promise
ISSUE_FOREIGN_RECEIPT = "foreign_receipt"   # receipt in our slot names another job
ISSUE_UNATTRIBUTABLE = "unattributable"    # healthy-looking artifact, no receipt
ISSUE_CORRUPT_RECEIPT = "corrupt_receipt"   # receipt undecodable
ISSUE_ZOMBIE_STAGING = "zombie_staging"    # crash-residue under a generation
ISSUE_SHA_DRIFT = "sha_drift"              # source changed after the receipt promise
ISSUE_UNSAFE_PATH = "unsafe_path"          # symlink / traversal / out-of-bounds
ISSUE_ORPHAN_RECEIPT = "orphan_receipt"     # decodable receipt, no artifact, no staging


@dataclass(frozen=True)
class Issue:
    kind: str
    path: str
    safe_action: str  # complete_rename | quarantine | discard_staging | preserve | investigate


@dataclass(frozen=True)
class ReconcileReport:
    """Read-only verdict on the on-disk publish truth for one job."""

    job_id: str
    expected_token: str | None
    published_generation: str | None   # generation_tag of the authoritative published gen
    published_sha: str | None
    issues: tuple[Issue, ...]
    hardware_blocked_platforms: tuple[str, ...] = _HARDWARE_BLOCKED

    def is_published(self) -> bool:
        return self.published_generation is not None and self.published_sha is not None

    def issues_by_kind(self) -> dict[str, list[Issue]]:
        out: dict[str, list[Issue]] = {}
        for i in self.issues:
            out.setdefault(i.kind, []).append(i)
        return out


@dataclass(frozen=True)
class RecoveryResult:
    job_id: str
    token: str | None
    completed: bool
    applied: tuple[str, ...] = ()
    discarded: tuple[str, ...] = ()
    quarantined: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()
    reason: str = ""
    published_generation: str | None = None
    published_sha: str | None = None


# ── path / hash helpers (safe derivation only) ─────────────────────


def _sha256_file(p: Path) -> str | None:
    """Chunked (8 KB) sha256 — never loads a whole media file."""
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            while True:
                chunk = fh.read(8192)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _contained(p: Path, root: Path) -> bool:
    """`p` resolves to a location strictly under `root`."""
    try:
        p.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _safe_staged(staged: Path, out: Path) -> bool:
    """The staged source is usable: a real file under our root, no
    symlink in the chain, no escape (forged paths / reparse points
    are refused — N8)."""
    if not staged.exists():
        return False
    if staged.is_symlink() or not staged.is_file():
        return False
    if not _contained(staged, out):
        return False
    # every intermediate component under out/.staging must be real:
    for i in range(1, len(staged.parts)):
        if Path(*staged.parts[:i + 1]).is_symlink() and _contained(
            Path(*staged.parts[:i + 1]), out
        ):
            return False
    return True


def _same_volume(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _lease_live(queue, job_id: str, worker: str, token: str) -> bool:
    """P09.1 live-lease truth read from the queue row: state LEASED,
    holder == worker, EXACT token, unexpired. The queue row is the
    source of truth — never a token remembered by the caller."""
    if queue is None:
        return False
    try:
        row = queue.job_state(job_id)
    except KeyError:
        return False
    exp = row.get("lease_expires_at")
    unexpired = exp is None or time.time() < exp
    return (
        row.get("state") == "LEASED"
        and row.get("lease_worker") == worker
        and row.get("lease_token") == token
        and unexpired
    )


def _quarantine(out: Path, job_id: str, src: Path, log: list[str]) -> None:
    """Move unattributable / damaged evidence under out/.quarantine/<job>/.
    Evidence is preserved, never deleted; the published slot is emptied."""
    qroot = out / ".quarantine" / job_id
    qroot.mkdir(parents=True, exist_ok=True)
    dest = qroot / src.name
    n = 1
    while dest.exists():
        dest = qroot / f"{n}-{src.name}"
        n += 1
    os.replace(src, dest)
    log.append(str(dest))


# ── read-only assessment ────────────────────────────────────────────


def reconcile_proxy_job(
    out_dir, job_id, *, expected_token=None
) -> ReconcileReport:
    """Read-only assessment of the on-disk publish truth for `job_id`
    under `out_dir`. NEVER writes.

    A slot counts as PUBLISHED only when an exposed artifact, a
    decodable receipt naming this job, and a matching SHA256 all agree.
    Everything else is classified (pending / mismatch / corrupt /
    unattributable / zombie / drift / unsafe / orphan) with a safe
    action attached — it is never deleted by assessment."""
    out = Path(out_dir)
    issues: list[Issue] = []
    published_gen: str | None = None
    published_sha: str | None = None
    receipted_gens: set[str] = set()
    receipted_bases: set[str] = set()

    def _our_receipts() -> list[tuple[Path, dict | None]]:
        """Receipts under out/ whose SLOT belongs to this job (the job
        namespace prefix in the name) — decodable ones keep their dict,
        undecodable ones carry None."""
        found: list[tuple[Path, dict | None]] = []
        if not out.is_dir():
            return found
        for f in sorted(out.iterdir()):
            if not f.is_file() or not f.name.endswith(".receipt.json"):
                continue
            base = f.name[: -len(".receipt.json")]
            if not base.startswith(f"{job_id}__"):
                continue  # another job's slot — never assessed here
            receipted_bases.add(base)
            try:
                rec = json.loads(f.read_bytes())
            except (OSError, ValueError):
                found.append((f, None))
                continue
            if not isinstance(rec, dict):
                found.append((f, None))
                continue
            found.append((f, rec))
        return found

    for rfile, rec in _our_receipts():
        base = rfile.name[: -len(".receipt.json")]
        artifact = out / base
        if rec is None:
            issues.append(Issue(ISSUE_CORRUPT_RECEIPT, str(rfile), "quarantine"))
            if artifact.is_file():
                issues.append(
                    Issue(ISSUE_CORRUPT_RECEIPT, str(artifact), "quarantine")
                )
            continue
        if rec.get("job_id") != job_id:
            # a slot in our namespace carrying a FOREIGN job's receipt:
            # untrusted tamper — never touch it, flag it.
            issues.append(Issue(ISSUE_FOREIGN_RECEIPT, str(rfile), "preserve"))
            continue
        tok = rec.get("lease_token")
        gen = generation_tag(tok)
        receipted_gens.add(gen)
        promised = rec.get("proxy_sha256")
        # A valid, hash-matching staged source is AUTHORITATIVE even when an
        # exposed artifact is present but mismatched to the receipt (the
        # receipt-overwrite shape: a newer generation wrote its receipt in
        # the receipt-first window, its rename never landed, and the older
        # exposed bytes still sit in the shared slot). Its pending rename
        # completes atomically (os.replace) and supersedes the older exposed
        # bytes — it is NEVER quarantined first. Only when NO valid staged
        # source exists do we fall back to fail-closed quarantine.
        staged = out / ".staging" / job_id / gen / base
        staged_valid = (
            promised is not None
            and _safe_staged(staged, out)
            and _sha256_file(staged) == promised
        )
        if staged_valid:
            issues.append(
                Issue(ISSUE_PENDING_RENAME, str(staged), "complete_rename")
            )
            continue
        if artifact.is_file():
            actual = _sha256_file(artifact)
            if promised and actual == promised:
                # a COMPLETE generation: the authoritative published state.
                published_gen, published_sha = gen, actual
                continue
            # exposed artifact, mismatched to the receipt, and NO valid
            # staged source to replace it with: fail-closed quarantine
            # (bytes are preserved under .quarantine/, slot emptied).
            issues.append(Issue(ISSUE_HASH_MISMATCH, str(artifact), "quarantine"))
            issues.append(Issue(ISSUE_HASH_MISMATCH, str(rfile), "quarantine"))
            continue
        if staged.is_symlink() or (
            staged.exists() and not _safe_staged(staged, out)
        ):
            # symlink / reparse-point / out-of-bounds staged source: never
            # expose it; preserve for the operator.
            issues.append(Issue(ISSUE_UNSAFE_PATH, str(staged), "preserve"))
        elif staged.exists():
            # usable bytes that drifted from the receipt promise: no
            # automatic action, operator decides (N9).
            issues.append(Issue(ISSUE_SHA_DRIFT, str(staged), "investigate"))
        else:
            # receipt with neither artifact nor staging source left: the
            # only trace of a crash in the receipt-first window.
            issues.append(Issue(ISSUE_ORPHAN_RECEIPT, str(rfile), "quarantine"))

    # artifacts in our namespace with no receipt at all: unattributable.
    if out.is_dir():
        for f in sorted(out.iterdir()):
            if not f.is_file() or f.name.endswith(".receipt.json"):
                continue
            if not f.name.startswith(f"{job_id}__"):
                continue
            if f.name in receipted_bases:
                continue
            issues.append(Issue(ISSUE_UNATTRIBUTABLE, str(f), "quarantine"))

    # staging residue with no receipt claiming it: zombie generations.
    # Unsafe residue (a symlink / reparse point escaping the root) is
    # flagged UNSAFE_PATH and preserved — it is never discarded or
    # exposed (N8).
    job_staging = out / ".staging" / job_id
    if job_staging.is_dir():
        for gen_dir in sorted(job_staging.iterdir()):
            if not gen_dir.is_dir() or gen_dir.name in receipted_gens:
                continue
            files = [f for f in gen_dir.iterdir()
                     if f.is_file() or f.is_symlink()]
            if not files:
                continue
            unsafe = [f for f in files if not _safe_staged(f, out)]
            if unsafe:
                for f in unsafe:
                    issues.append(Issue(ISSUE_UNSAFE_PATH, str(f), "preserve"))
            else:
                issues.append(
                    Issue(ISSUE_ZOMBIE_STAGING, str(gen_dir), "discard_staging")
                )

    return ReconcileReport(
        job_id=job_id,
        expected_token=expected_token,
        published_generation=published_gen,
        published_sha=published_sha,
        issues=tuple(issues),
    )


# ── lease-gated replay ─────────────────────────────────────────────


def apply_recovery(
    out_dir, job_id, report, *, queue, worker, token
) -> RecoveryResult:
    """Replay the SAFE subset of a ReconcileReport for `job_id`.

    - Any mutation requires a LIVE lease on the queue (P09.1): the
      caller's (worker, token) must match the queue row exactly. A
      stale or zombie worker is fenced out with zero writes.
    - The state is RE-RECONCILED and re-hashed here: a source change
      between the caller's assessment and this call (drift) is refused,
      not trusted.
    - A healthy published generation is never clobbered; quarantine
      moves evidence to out/.quarantine/ (preserved), never deletes;
      zombie staging of unclaimed generations is discarded (P08
      crash-discardable material) but ONLY under the live lease.
    - An old generation is not re-attributed to a new token: takeover
      does not inherit a pending state it did not produce — only the
      generation a receipt actually names may be completed.
    """
    out = Path(out_dir)
    if not _lease_live(queue, job_id, worker, token):
        return RecoveryResult(
            job_id=job_id,
            token=token,
            completed=False,
            deferred=report.issues,
            reason=(
                f"lease fence: {token!r} is not {worker!r}'s live lease for "
                f"{job_id!r} (the queue row is the truth source); no "
                f"mutation applied"
            ),
        )

    # re-assess now: the caller's `report` may be stale (N9).
    fresh = reconcile_proxy_job(out, job_id, expected_token=token)
    kinds = fresh.issues_by_kind()
    applied: list[str] = []
    discarded: list[str] = []
    quarantined: list[str] = []
    deferred: list[str] = []
    notes: list[str] = []
    completed_rename = False
    pub_gen: str | None = fresh.published_generation
    pub_sha: str | None = fresh.published_sha

    # 1) COMPLETE PENDING RENAMES FIRST. A valid, hash-matching staged source
    #    is authoritative for its slot: os.replace atomically supersedes any
    #    mismatched exposed bytes (the receipt-overwrite shape). We run this
    #    BEFORE quarantine so a valid newer generation is never destroyed.
    #    Only the holder's OWN generation is auto-completed (a legitimate
    #    replay of an interrupted publish). A pending rename belonging to
    #    ANOTHER generation is a takeover candidate: it is deferred, never
    #    auto-published, and the exposed (possibly older, healthy) bytes are
    #    preserved in place (spec §4: no auto-adoption of foreign gens).
    for iss in kinds.get(ISSUE_PENDING_RENAME, []):
        staged = Path(iss.path)
        if not _safe_staged(staged, out):
            deferred.append(iss.path)
            notes.append(f"unsafe staged path preserved: {staged}")
            continue
        base = staged.name
        target = out / base
        rfile = out / f"{base}.receipt.json"
        promised, rec_tok = None, None
        try:
            rec = json.loads(rfile.read_bytes())
            if isinstance(rec, dict) and rec.get("job_id") == job_id:
                promised, rec_tok = rec.get("proxy_sha256"), rec.get("lease_token")
        except (OSError, ValueError):
            pass
        if not promised:
            deferred.append(iss.path)
            notes.append(f"pending rename skipped: no matching receipt for {base}")
            continue
        now_sha = _sha256_file(staged)
        if now_sha != promised:
            # the source moved after the receipt promise (N9): refuse, preserve.
            deferred.append(iss.path)
            notes.append(
                "sha drift detected: staged hash no longer matches the "
                "receipt's promise; publish refused, evidence preserved"
            )
            continue
        if generation_tag(rec_tok) != generation_tag(token):
            # not the holder's own generation: a deferred takeover candidate.
            # The exposed bytes (a possibly older healthy gen) are preserved;
            # the operator re-verifies provenance before promoting this gen.
            deferred.append(iss.path)
            notes.append(
                f"pending gen {generation_tag(rec_tok)!r} is not the live "
                f"holder's gen {generation_tag(token)!r}; deferred (BLOCKED), "
                f"exposed bytes preserved, no auto-publish"
            )
            continue
        if target.is_file() and _sha256_file(target) == promised:
            continue  # already published & healthy: idempotent no-op
        if not _same_volume(staged, out):
            deferred.append(iss.path)
            notes.append(
                "cross-volume rename refused: os.replace is not atomic "
                "across volumes (HARDWARE_BLOCKED on UNC/SMB)"
            )
            continue
        os.replace(staged, target)
        if _sha256_file(target) != promised:
            # post-rename readback failed: treat as damaged, quarantine.
            _quarantine(out, job_id, target, quarantined)
            applied.append("quarantine:post-rename-mismatch")
            notes.append("post-rename readback mismatch; target quarantined")
            continue
        completed_rename = True
        pub_gen, pub_sha = generation_tag(token), promised
        applied.append("complete_rename")
        # tidy now-empty staging dirs (best effort, this gen only):
        gen_dir = staged.parent
        try:
            gen_dir.rmdir()
            gen_dir.parent.rmdir()
            (out / ".staging").rmdir()
        except OSError:
            pass

    # 2) RE-ASSESS after the renames: a completed rotation now agrees
    #    (artifact == receipt), so only what is STILL untrustworthy is
    #    quarantined — and any exposed artifact a pending rename claims is
    #    never quarantined here (it was preserved, or rotated, in step 1).
    fresh = reconcile_proxy_job(out, job_id, expected_token=token)
    kinds = fresh.issues_by_kind()
    for kind in (
        ISSUE_HASH_MISMATCH,
        ISSUE_UNATTRIBUTABLE,
        ISSUE_CORRUPT_RECEIPT,
        ISSUE_ORPHAN_RECEIPT,
    ):
        for iss in kinds.get(kind, []):
            p = Path(iss.path)
            if not p.exists() or not _contained(p, out):
                continue
            _quarantine(out, job_id, p, quarantined)
            applied.append(f"quarantine:{kind}")
    pub_gen = fresh.published_generation or pub_gen
    pub_sha = fresh.published_sha or pub_sha

    # 3) discard unclaimed zombie generations (P08 crash-discardable,
    #    live-lease-only; receipt-claimed generations are never swept).
    for iss in kinds.get(ISSUE_ZOMBIE_STAGING, []):
        d = Path(iss.path)
        if _contained(d, out):
            shutil.rmtree(d, ignore_errors=True)
            discarded.append(str(d))
            applied.append("discard_staging")

    # 4) deferred, preserved-for-operator issues:
    for kind in (ISSUE_SHA_DRIFT, ISSUE_UNSAFE_PATH, ISSUE_FOREIGN_RECEIPT):
        for iss in kinds.get(kind, []):
            deferred.append(iss.path)
            notes.append(f"{kind} preserved for operator review: {iss.path}")

    completed = completed_rename or fresh.is_published()
    reason = "; ".join(notes) if notes else "recovery complete"
    return RecoveryResult(
        job_id=job_id,
        token=token,
        completed=completed,
        applied=tuple(applied),
        discarded=tuple(discarded),
        quarantined=tuple(quarantined),
        deferred=tuple(deferred),
        reason=reason,
        published_generation=pub_gen,
        published_sha=pub_sha,
    )


__all__ = [
    "ISSUE_CORRUPT_RECEIPT",
    "ISSUE_FOREIGN_RECEIPT",
    "ISSUE_HASH_MISMATCH",
    "ISSUE_ORPHAN_RECEIPT",
    "ISSUE_PENDING_RENAME",
    "ISSUE_SHA_DRIFT",
    "ISSUE_UNATTRIBUTABLE",
    "ISSUE_UNSAFE_PATH",
    "ISSUE_ZOMBIE_STAGING",
    "Issue",
    "ReconcileReport",
    "RecoveryResult",
    "apply_recovery",
    "reconcile_proxy_job",
]
