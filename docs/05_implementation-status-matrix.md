# Implementation Status & Evidence Matrix — Mnemosyne (RC-1)

> **Purpose**: the single source of truth for what is actually working, at
> what evidence tier. Public docs (README, quickstarts, TUI guide) must
> cite the tiers in this file. **Never collapse tiers into one "DONE"
> label.** Updated 2026-10-28 at RC-1 preparation; baseline commit
> `3d3a2a7` (branch `research/dit22-multimodal-handoff-20261024`).

## Tiers (definitions)

| Tier | Meaning |
|---|---|
| **COMMITTED / CI VERIFIED** | In a git commit with passing CI (or passing local test battery at a pinned commit). |
| **LOCAL TESTED / REVIEWED** | Implemented + tests passing in the local tree + independent review; **not yet committed** (this branch's P11.1/P12.1/P12.2/P12.2-R layers). |
| **SPECIFICATION ONLY** | Design document exists; code not written or not validated on target hardware. |
| **HARDWARE BLOCKED** | Code path exists (or is intentionally absent); real-device validation impossible without the specific hardware (A770, Windows, NAS, camera media). Never claim PASS without physical evidence. |
| **NOT IMPLEMENTED** | No code; roadmap item only. |

---

## Track A — Second Brain v4 (private document/media indexing)

| Component | Tier | Evidence |
|---|---|---|
| v4 plan + 105-file SHA-256 archive snapshot | COMMITTED | `_archive/2026-06-05-v4-plan/verify.py` → 105/105 OK |
| Indexer core (`src/scripts/indexer.py`) + 7 invariants enforced | COMMITTED / CI VERIFIED | `tests/test_index_pipeline.py` (16 tests) in CI at `3d3a2a7` |
| Qdrant named vectors `text_vec(768)+image_vec(512)` | COMMITTED / CI VERIFIED | `tests/test_qdrant_named_vectors.py` |
| 3 MCP skills (qdrant-search / filesystem-search / video-slice) | COMMITTED / CI VERIFIED | `tests/test_mcp_servers.py` + `test_hermes_skills.py` |
| 100-entry eval set | COMMITTED | `tests/eval_v2_100.jsonl` |
| Live Qdrant/Ollama/Hermes integration **on the reference machines** | HARDWARE BLOCKED | machines offline since planning; integration never run on-hardware |
| Local LLM serving (Gemma / Qwen profiles) | SPECIFICATION ONLY | Modelfiles + build flags only; no model weights in repo, no on-hardware run |
| macOS launchd / Linux systemd service units | SPECIFICATION ONLY | units written, never deployed/validated on a running service |

## Track B — DIT 2.2 media subsystem (media pipeline within Mnemosyne)

| Component | Tier | Evidence |
|---|---|---|
| Media probe (ffprobe read-only, FPS/VFR/HDR/timecode degradation) | LOCAL TESTED | `tests/test_dit22_media_probe*` within 330-test battery |
| Source admission gate (fail-closed; test_mode isolation) | LOCAL TESTED / REVIEWED | `test_dit22_source_admission.py` (21) + P11.1-A review (8/8 PASS) |
| Publication fencing (lease obligation, dual check, versioned staging) | LOCAL TESTED / REVIEWED | `test_dit22_publication_fence.py` (13) + P11.1-B full-scope review |
| CPU proxy generation (H.264 browser/editor profiles) | LOCAL TESTED / REVIEWED | `test_dit22_proxy_generator.py` (16) |
| Crash recovery reconciler (read-only PUBLISHED/quarantine verdicts) | LOCAL TESTED / REVIEWED | `test_dit22_artifact_recovery.py` (P11.1-C) |
| Editor proxy validation (PTS/frames/audio read-back, P11.1-D) | LOCAL TESTED / REVIEWED | `test_dit22_editor_validation.py` |
| Memory-bounded scene detection (P12 staged + P12.1 frame cap / RSS guard) | P12 COMMITTED-staged (8 files, byte-fingerprinted); P12.1 LOCAL TESTED / REVIEWED | `test_dit22_scene_detect.py` (16, staged) + `test_dit22_memory_guard.py` (12) |
| Phase-4 integration hardening: SourcePin re-hash (C1/C2), retry budget (C3), capacity gate (C4), path isolation (C5), Windows stem/UNC sentinel (C6) | LOCAL TESTED / REVIEWED | 5 new test files (38) + `deleg_a5ec733f` REVIEWED-complete (0C/0I) |
| Windows-safe artifact naming (`windows_naming.py`) | LOCAL TESTED | `test_dit22_windows_naming.py` (10, incl. MAX_PATH, NFKC/case collisions, UNC status) |
| **Full suite: 330 passed, 6 pre-existing qdrant-client warnings; scoped ruff clean** | LOCAL TESTED (fresh run 2026-10-28) | battery re-executed this round, not inherited |

### Not to be read as operational (explicit exclusions)

| Item | Tier |
|---|---|
| Windows CPU Pilot on the A770 workstation | **SPECIFICATION ONLY** (`docs/engineering/spec/Windows-CPU-pilot-A770.md`); census not collected |
| UNC/SMB cross-volume rename + persistence | **HARDWARE BLOCKED** (`HARDWARE_BLOCKED` sentinel in code; no Windows box tested) |
| A770 GPU / QSV / OpenVINO acceleration | **HARDWARE BLOCKED** (driver state unknown; pilot is CPU-only by design) |
| Real camera media families (Sony BRAW/XAVC etc.) | **UNVERIFIED** (synthetic fixtures only — never claim family support) |
| Power-loss recovery on real hardware | **HARDWARE BLOCKED** (crash-discard logic is tested via simulated aborts, not real outages) |
| 4K long-form proxy workloads | **HARDWARE BLOCKED** (memory guard validated on short segments; long-form untested) |
| Interactive developer TUI | **NOT IMPLEMENTED** (design concepts exist — `docs/dit22-tui-design.md`, TUI dashboard asset is a **CONCEPT MOCKUP**) |
| AI semantic search over media (P13-style) | **NOT IMPLEMENTED** (out of RC-1 scope) |

## Cross-cutting safety invariants (all tiers)

- Original files are never mutated; the index is a rebuildable derived view.
- All DIT probes/read-backs are read-only; recovery reconciler emits verdicts, never deletes.
- 15% free-space metric is **advisory-only** (policy: stop new proxy/embed jobs; auto-delete of originals/music/backups is prohibited by design).
- No cloud AI calls without explicit opt-in; default is 100% local, no telemetry.
