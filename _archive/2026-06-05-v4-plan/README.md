# Archive: 2026-06-05 — Mnemosyne v4 plan freeze

> **Snapshot of the Mnemosyne v4 plan as a GitHub-ready template.**
> Date: 2026-06-05
> Version: v4.0.0-2026-06-05-plan
> Files: 105 (~508KB)

---

## What this is

This directory is a **manifest + verification** of the v4 plan, NOT a copy
of the source files. The actual files live in the parent repository
(`mnemosyne/`). The archive exists to:

1. **Prove** that on 2026-06-05 the v4 plan existed in a particular shape.
2. **Allow anyone** (including a future you) to verify the current state
   of the repo matches this snapshot, byte-for-byte.
3. **Provide a recovery path** if the git history is lost — you can use
   `restore.sh` to reconstruct the entire repo from any working copy
   that matches the manifest.

---

## Files in this archive

| File | Purpose |
|---|---|
| `README.md` | This file |
| `manifest.json` | SHA-256 + size for every file in the repo at snapshot time |
| `restore.sh` | Reconstruct the repo from a working copy that matches the manifest |
| `verify.py` | Check a current copy of the repo against the manifest |
| `CHANGELOG.md` | What was new in this snapshot (vs the v3 plan) |

---

## How to verify the current repo

```bash
python3 _archive/2026-06-05-v4-plan/verify.py /path/to/Hermes_second_brain_agent_AIIinONE
```

Output will look like:

```
[OK] README.md  (sha256: 5a8b...)
[OK] LICENSE  (sha256: c3d2...)
[CHANGED] src/scripts/indexer.py  (expected abc123, got def456)
[OK] src/scripts/indexer.py  (sha256: def456)
...
Summary: 99 OK, 1 CHANGED, 0 MISSING
```

A non-zero exit code means the current repo has drifted from this
snapshot — expected if work has continued past 2026-06-05.

---

## How to restore

If you have *some* working copy of the repo (e.g. from a colleague's
machine, or extracted from OneDrive), and you want to verify it matches
this snapshot:

```bash
python3 verify.py /path/to/copy
```

If you want to *reconstruct* the repo from scratch (because the entire
git history was lost and the only thing you have is this archive +
a oneDrive backup that may be partially corrupted):

```bash
# Step 1: get a partial copy from OneDrive (rsync, rclone, etc.)
rclone copy onedrive-crypt:AI-Brain-Backup/2026-06-05-v4-plan-snapshot /tmp/restore

# Step 2: verify it matches the manifest
python3 _archive/2026-06-05-v4-plan/verify.py /tmp/restore

# Step 3: (if mostly OK) copy the verified files back to the live location
rsync -avh /tmp/restore/ ~/ai-brain-station/repo/
```

---

## What is NOT in this archive

- **Not included** (intentionally): `models/`, `data/`, `venv/`, `.venv/`,
  `node_modules/`, anything in `__pycache__/`, anything in `.git/`.
  These are either generated, downloadable, or version-controlled
  elsewhere.

- **Not included** (could be in the future): the binary LLM weights,
  the trained indexes, the actual RAID/OneDrive contents. The archive
  only contains the *plan and code* — the *data* has its own backup
  pipeline (see `docs/06_備份與同步/`).

- **Not verifiable** across machines: file permissions, ownership,
  timestamps. The manifest only hashes content.

---

## See also

- [`../../CHANGELOG.md`](../../CHANGELOG.md) — the canonical changelog
- [`../../docs/00_index.md`](../../docs/00_index.md) — master index of the v4 plan
- [`../../docs/06_備份與同步/同步策略.md`](../../docs/06_備份與同步/同步策略.md) — the backup strategy that produces this archive
- [`../../docs/06_備份與同步/版本標籤規範.md`](../../docs/06_備份與同步/版本標籤規範.md) — tag conventions; this archive is `v4.0.0-2026-06-05-plan`
