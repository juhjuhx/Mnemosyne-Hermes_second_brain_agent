"""staging.py — DIT 2.2 P08 staging atomic commit (F12/F13/F14).

Pure stdlib, synthetic-friendly, isolated `dit22` namespace. Implements
the P08 spec (`docs/engineering/spec/P08-staging-atomic-commit.md`):

- **Staging atomic commit (F12)**: an archive is only exposed at the
  target AFTER every file's hash has been re-checked and an append-only
  receipt is in place. A partial staging tree is never visible as a
  committed archive (the "complete sealed directory before the
  processing queue" rule).
- **Mirror ≠ backup (F13)**: destinations are judged by an *injected*
  device-identity provider (P07.1 `DeviceIdentityProvider`), never by
  caller-supplied strings or paths. Two mount points of one physical
  device fold to ONE domain; network shares and unlisted paths never
  count. The report says "availability, not backup".
- **Fail-closed crash recovery**: crash/kill between stage and commit
  leaves the archive `INTERRUPTED`; `resume()` re-hashes everything and
  commits only on a full match. Any mismatch (tamper, partial,
  receipt/manifest drift) is `BLOCKED` — a recorded safety state, not a
  re-triable success. State is *derived from the directory contents*,
  so it is crash-safe with no extra journal file.

No SAFE_TO_FORMAT surface exists here (P05.1/P07.1 invariant); this
module only ever grants `COMMITTED` (this archive is complete and
verified), which is a record, not an authorization to delete sources.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from asset_schema import DeviceIdentityProvider

MANIFEST_NAME = ".staging_manifest.json"
RECEIPT_NAME = "receipt.json"
_PARTIAL_SUFFIX = ".dit22-part"


class StagingConflictError(Exception):
    """A receipt/manifest conflict detected on re-entry: the committed
    target no longer matches what the receipt claims. The first valid
    receipt is authoritative; any drift is a tamper path (P05.1 S5)
    and is refused, not silently repaired."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StagedArchive:
    """One staging commit for one job. Paths are created on demand;
    nothing here moves, deletes, or rewrites a *source* — only the
    caller-supplied staged tree is manipulated."""

    def __init__(self, job_id: str, staging_dir: str | Path, target_dir: str | Path):
        self.job_id = job_id
        self.staging_dir = Path(staging_dir)
        self.target_dir = Path(target_dir)
        self._destinations: list[str] = []

    # ── staging ─────────────────────────────────────────────────────

    def stage(self, files: dict[str, bytes]) -> None:
        """Write (or overwrite) staged files under `staging_dir`."""
        for rel, data in files.items():
            p = self.staging_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def _staged_files(self) -> dict[str, Path]:
        """Every real file in the staging tree, rel path -> absolute."""
        out: dict[str, Path] = {}
        if not self.staging_dir.exists():
            return out
        for p in self.staging_dir.rglob("*"):
            if p.is_file() and p.name not in (MANIFEST_NAME,) \
                    and not p.name.endswith(_PARTIAL_SUFFIX):
                out[p.relative_to(self.staging_dir).as_posix()] = p
        return out

    def _hash_staged(self) -> dict[str, str]:
        return {rel: _sha256_file(p) for rel, p in sorted(self._staged_files().items())}

    def _load_manifest(self) -> dict[str, str] | None:
        m = self.staging_dir / MANIFEST_NAME
        if not m.exists():
            return None
        return json.loads(m.read_text())

    def verify_manifest(self) -> dict[str, str]:
        """Re-hash the whole staged tree and persist the manifest.
        This is the gate a crash-recovery resume trusts (plus the
        current directory state)."""
        manifest = self._hash_staged()
        (self.staging_dir / MANIFEST_NAME).parent.mkdir(
            parents=True, exist_ok=True
        )
        (self.staging_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
        return manifest

    # ── commit (F12) ────────────────────────────────────────────────

    def commit(self) -> bool:
        """Atomically expose the staging tree at `target_dir`.

        Fails closed: missing manifest, hash drift, or a missing staged
        file => `False` (state becomes BLOCKED). Success moves each
        file through a `.dit22-part` temp + `os.replace`, and writes
        `receipt.json` LAST — so a target that lacks a receipt is, by
        definition, not a committed archive.
        """
        saved = self._load_manifest()
        if saved is None:
            return False  # never verified -> cannot commit
        current = self._hash_staged()
        if current != saved:
            return False  # tamper / partial -> BLOCKED
        for rel in saved:
            src = self.staging_dir / rel
            dst = self.target_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            part = dst.with_name(dst.name + _PARTIAL_SUFFIX)
            part.write_bytes(src.read_bytes())
            os.replace(part, dst)  # atomic on the same filesystem
        receipt = {
            "job_id": self.job_id,
            "manifest": saved,
            "staged_at_epoch": time.time(),
        }
        part = (self.target_dir / RECEIPT_NAME).with_name(RECEIPT_NAME + _PARTIAL_SUFFIX)
        part.write_text(json.dumps(receipt, indent=2))
        os.replace(part, self.target_dir / RECEIPT_NAME)
        return True

    # ── crash recovery / resume ─────────────────────────────────────

    def resume(self) -> bool:
        """Re-hash after an interruption; commit only on a full match.
        A tampered/short staging tree returns `False` and leaves the
        archive BLOCKED (it is never exposed)."""
        saved = self._load_manifest()
        if saved is None:
            return False
        if self._hash_staged() != saved:
            return False
        return self.commit()

    def _receipt(self) -> dict | None:
        p = self.target_dir / RECEIPT_NAME
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def reentry_check(self) -> None:
        """Idempotent re-entry: a valid receipt is a no-op; any drift
        between receipt and the actual target files raises
        `StagingConflictError` (tamper path, P05.1 S5)."""
        receipt = self._receipt()
        if receipt is None:
            return
        claimed = receipt.get("manifest", {})
        target_files = {
            p.relative_to(self.target_dir).as_posix()
            for p in self.target_dir.rglob("*")
            if p.is_file()
            and p.name != RECEIPT_NAME
            and not p.name.endswith(_PARTIAL_SUFFIX)
        }
        if target_files != set(claimed):
            raise StagingConflictError(
                f"receipt lists {sorted(claimed)} but target has {sorted(target_files)}"
            )
        for rel, digest in claimed.items():
            actual = _sha256_file(self.target_dir / rel)
            if actual != digest:
                raise StagingConflictError(
                    f"target file {rel!r} hash {actual} != receipt digest {digest}"
                )

    def recovery_state(self) -> str:
        """Derived, crash-safe state (no journal file needed):

        - COMMITTED : a valid receipt exists and matches the target.
        - BLOCKED   : a receipt exists but drifted, or the staging tree
                      no longer matches its manifest (tamper/partial).
        - INTERRUPTED: work in flight (staged files present, receipt
                      absent).
        - CLEAN     : nothing here.
        """
        receipt = self._receipt()
        if receipt is not None:
            try:
                self.reentry_check()
            except StagingConflictError:
                return "BLOCKED"
            return "COMMITTED"
        saved = self._load_manifest()
        if saved is not None:
            return "BLOCKED" if self._hash_staged() != saved else "INTERRUPTED"
        if self._staged_files():
            return "INTERRUPTED"
        return "CLEAN"

    def discard(self) -> None:
        """Abandon the staging tree (caller-authorized). Does NOT touch
        the target archive or any source media."""
        import shutil

        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)

    # ── mirror vs backup (F13/F14) ──────────────────────────────────

    def register_destination(self, mount_path: str) -> None:
        """Record where this archive's copies live (mount paths, NOT
        devices — device identity is resolved later via the provider)."""
        self._destinations.append(mount_path)

    def independence_report(self, provider: DeviceIdentityProvider) -> dict:
        """Judge backup independence through the injected device-identity
        provider — the ONLY source of truth for 'is this a distinct
        physical device'. Mirror/RAID1 paths of one device fold to a
        single domain (availability, not backup); non-physical and
        unknown paths never count (fail-closed)."""
        by_device: set[str] = set()
        for path in self._destinations:
            ident = provider.identity_for(path)
            if ident.is_physical:
                by_device.add(ident.device_id)
        domains = sorted(by_device)
        return {
            "domains": domains,
            "independent_backup_count": len(domains),
            "mirror_note": "availability, not backup",
        }
