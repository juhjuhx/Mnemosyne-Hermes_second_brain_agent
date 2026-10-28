# DIT 2.2 Developer Quick Start

> **Track B, from clone to first proxy.** Everything here is **LOCAL TESTED /
> REVIEWED** in the research branch (330 tests) but **not yet committed** —
> treat this as Developer Preview, and do not represent the Windows/Pilot
> items as operational. See the [status matrix](05_implementation-status-matrix.md)
> for tiers.

## Prerequisites

- Python 3.10–3.12 in a venv.
- `ffmpeg` and `ffprobe` on PATH (CPU baseline; no GPU required).
- No NAS, no camera card, no cloud tokens — synthetic media only.

## Setup

```bash
pip install -e .                # installs test/dev deps from pyproject
pytest tests/ -q               # expect 330 passed, 6 pre-existing qdrant-client warnings
```

## The one-command demo (module-level, 8 steps)

```bash
python examples/dit22_synthetic_demo.py
# keeps nothing by default; to inspect the evidence bundle:
python examples/dit22_synthetic_demo.py --work ./demo_out
# machine-readable: demo_out/evidence/demo_evidence_bundle.json
```

What each step proves (all via real public API calls — no invented commands):

| Step | Function exercised |
|---|---|
| 1 | `media_probe.probe(sha256=True)` — read-only, FPS/timecode/audio |
| 2 | `proxy_generator.generate_proxy(test_mode=True)` — CPU H.264 proxy |
| 3 | receipt read-back — `source_sha256` / `proxy_sha256` equality |
| 4 | corrupt encoder → `ProxyVerifyError`, **nothing published** |
| 5 | `artifact_recovery.reconcile_proxy_job` — read-only verdicts |
| 6 | `editor_validation.validate_editor_proxy` — P11.1-D read-back |
| 7 | `scene_detect.ContentDiffProvider` / `FixedIntervalProvider` (CPU) |
| 8 | `windows_naming.safe_artifact_name` + `capacity_gate.check_capacity` |

## Module-level examples (if you want to call the pieces directly)

```python
import sys; from pathlib import Path
sys.path.insert(0, str(Path("src/mnemosyne_dit")))

from media_probe import probe
from proxy_generator import generate_proxy
from artifact_recovery import reconcile_proxy_job

m = probe("synthetic_source.mp4", sha256=True)      # read-only
r = generate_proxy(
    "synthetic_source.mp4", "browser", "out/",
    source_probe=m, job_id="job-1", lease_token="tok-1", test_mode=True,
)
report = reconcile_proxy_job("out/", "job-1", expected_token="tok-1")
print(r.path, r.proxy_sha256[:12], report.is_published())
```

> `test_mode=True` is the **isolated synthetic path**: it skips the
> formal admission gate and records nothing to a catalog — use it for
> demos and tests. A *formal* job (`job_id` set, no `test_mode`)
> requires a `catalog` + `storage_id` and a trusted replica chain;
> otherwise the source is **denied before ffmpeg runs**.

## Recovery & safe failure (deliberate, read-only)

- Crash residue (zombie staging, orphan receipts, stale workers) is
  classified by `reconcile_proxy_job` with a `safe_action` attached —
  it **never deletes**.
- A corrupted encode is caught at the verify gate; the staged artifact
  is discarded, nothing is published.
- Low free space (< 15%) is **advisory-only**: it stops *new*
  proxy/embed jobs and never deletes originals, music, or backups.

## What this quick start does NOT cover (honest limits)

- **Windows CPU Pilot** — spec only (`docs/engineering/spec/Windows-CPU-pilot-A770.md`); no execution.
- **UNC/SMB, A770 GPU, real camera media, power-loss** — HARDWARE BLOCKED / UNVERIFIED.
- **Interactive TUI** — not implemented; see `dit22-tui-design.md` (labeled concept).
