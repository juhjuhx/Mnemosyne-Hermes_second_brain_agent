# Changelog

All notable changes to the Personal AI Second Brain (Hermes Edition) project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — DIT 2.2 multimodal research consolidation & Claude Code handoff (2026-10-24)

Research-only branch `research/dit22-multimodal-handoff-20261024`; **no
v4 behavior change, no cloud, no hardware claims**.

- `docs/research/Mnemosyne_DIT_2_2_CONSOLIDATED_MASTER_2026-10-24.md` —
  one-piece research SSOT (DIT 2.0/2.1/2.2 consolidated, appendices
  preserved verbatim)
- `docs/research/Mnemosyne_DIT_2_2_CLAUDE_CODE_AUTONOMOUS_PROMPT_2026-10-24.md` —
  copyable autonomous engineering prompt with source URLs
- `docs/research/dit22-source-ledger.md` — 19 upstream repos pinned to
  exact commits + license status + reuse verdicts
- `docs/research/dit22-licence-matrix.md` — A/B/C license tiering
- `docs/research/dit22-architecture-decisions.md` — 5 PROPOSED ADRs
  (cloud opt-in, vector profile isolation, queue parallelism, DIT
  safety state machine, frozen-archive verify.py drift)
- `docs/engineering/{TASK,PLAN,STATE,EVIDENCE}.md`,
  `dit22-skill-execution-ledger.jsonl`, `dit22-acceptance-matrix.md`
- `tests/fixtures/dit22/` — deterministic synthetic camera-card fixture
  generator + 3 contract tests (synthetic data only; verifies
  determinism, hash readback, copy-to-destination; no real media, no
  binaries in git)
- Baseline recorded: `pytest tests/` → 73 passed (venv, Python 3.14.5);
  `_archive/2026-06-05-v4-plan/verify.py` → exit 1 on main itself
  (44/105 files changed since the 2026-06-05 freeze; see ADR-DIT2-005)

### Added — DIT 2.2 P03 requirements map (2026-10-24)

- `docs/engineering/spec/F01-F52-requirements-map.md` — F01–F52
  requirements map grounded in the **actual repo source** (not docs):
  `indexer.py` (7 invariants), the naive `dit-offload` / `dit-metadata`
  MCP servers, and the `tests/fixtures/dit22/` synthetic generator. Each
  feature is tagged `repo_now` (DONE/PARTIAL/NAIVE/GAP) + a `test_spec`.
  Tallies: DONE 0 / PARTIAL 4 (F21,F31,F38,F49) / NAIVE 2 (F02,F05) /
  GAP 43 / HARDWARE_BLOCKED F42 (A770 not on host).
- P03 also independently re-verified the P00–P02 handoff (venv 73
  passed, Draft PR #1 head `bbd6ff7`) and corrected the Addy Osmani
  on-disk count to **24** (was recorded as 25 from the upstream README
  claim; this marketplace clone `13e43f2` installs 24). No v4 behavior
  change, no cloud call, no real-media touch.

### Added — DIT 2.2 P04 clean-room functional contracts (2026-10-24)

- `docs/engineering/spec/P04-clean-room-contracts.md` — four
  clean-room REA functional contracts + clean-room isolation boundary
  (`P04 §0`): `ingest-safety-contract` (S1–S7: source-readonly,
  independent-device fingerprint, staging atomic commit, idempotent
  resume, ASC MHL interop, fail-closed safety state machine, 0-byte /
  Unicode edge), `asset-schema` (asset_id decoupled from path),
  `provider-interface` (device-truth probe, no cross-model cosine,
  Gemini 0-call until ADR), `mcp-tools` (read-only / guarded / denied
  three-layer; `format_card`/`delete_original`/`purge_backup` never
  exposed to the agent). Each contract carries observable behavior +
  counter-examples + `test_spec` for later TDD slices (P07/P16).
  Marked PARTIAL/spec-only: contracts only, tests not yet run.

### Added — DIT 2.2 P05 canonical asset schema (executable slice, 2026-10-24)

- `src/mnemosyne_dit/asset_schema.py` — new-namespace SQLite catalog
  (`Dit22Catalog`, 4 `dit22_*` tables) implementing the P04 §2 data model:
  `asset_id` is a **content identity** (sha256 of bytes), fully decoupled
  from filesystem path; path observations and replicas are append records
  that never move/rename/delete a source; `independent_replicas()` treats a
  `unknown` failure domain as **non-independent** (fail-closed, mirrors
  ADR-DIT2-004 / F13). Lives in its own `dit22.db`; does not open the v4
  `files.db` or Qdrant named vectors.
- `tests/test_dit22_asset_schema.py` — 8 contract tests (path-decoupled
  identity, new-namespace isolation, multi-path observation, unknown
  failure-domain, evidence ledger, persistence/rebuild). Full suite now
  **81 passed** (73 prior + 8 new, no regression); ruff clean.
- No v4 behavior change, no cloud call, no real-media touch.

### Added — DIT 2.2 P05.1 security-model hardening (independent-review negative tests, 2026-10-24)

- `tests/test_dit22_asset_schema_hardening.py` — 12 negative contract tests
  (written FIRST, Red confirmed via collection ImportError) covering the five
  independent-review findings: advisory replica count, append-only evidence,
  upsert clobber, foreign-key enforcement, re-entry consistency.
- `src/mnemosyne_dit/asset_schema.py` — minimal hardening (dit22 namespace
  only; v4 index contracts untouched):
  - `PRAGMA foreign_keys=ON` at open (SQLite default is OFF; prior
    `REFERENCES` were declared but never enforced)
  - `upsert_asset` conflict path now `COALESCE` gap-fill — a known
    `card_id`/`reel` is never overwritten by a later NULL-carrying upsert
  - `add_evidence` is append-only: identical re-entry is a no-op (resume-safe),
    any value change under the same `evidence_id` raises
    `EvidenceConflictError` (first recorded verdict is authoritative)
  - `add_replica` identical re-entry is a no-op; a value change under the same
    `replica_id` (e.g. swapped `failure_domain`) raises `ReplicaConflictError`
  - new fail-closed `reuse_eligibility()` gate — requires PASS readback
    evidence bound to a replica AND all verified replicas on trusted
    (non-`unknown`) failure domains; missing any → `BLOCKED`. The module
    exposes no `SAFE_TO_FORMAT` surface anywhere.
- `docs/engineering/dit22-skill-execution-ledger.jsonl` split: machine
  records kept as pure JSONL (every line parseable); the 14 interleaved
  markdown synthesis lines moved to a new human-readable
  `docs/engineering/dit22-skill-execution-report.md`.
- Fresh full regression this session: **93 passed, 0 failed** (81 prior +
  12 new); `ruff check` clean on all touched files.

### Added — DIT 2.2 P06 differential engine audit (S1–S7, source-grounded, 2026-10-24)

- Pinned clones of both engines at the exact SSOT SHAs (workspace `refs/`,
  NOT committed to the repo):
  - ProofCat `29c06a2` → `cargo test -p offload-core` → **131 passed**
    (this session; Tauri-independent engine crate). Full-Tauri `process-kill-resume.sh`
    binary NOT built → that one item is `IMPLEMENTED_NOT_TESTED`.
  - offloader `e01a0eb` → dedicated `venv-engines` (with `hypothesis`)
    `pytest tests/` → **306 passed, 13 skipped** (skips are Windows-only
    paths). Engine tests never installed into the repo venv.
- `docs/engineering/spec/P06-differential-engine-audit.md` — S1–S7
  differential matrix. Every verdict carries a source path + line/function +
  a reproducible command. Notable: ProofCat leads on S2 (device serial
  fingerprint), S4 (job checkpoint / WAL resume), S6 (8-field
  `SafetyGate`); offloader leads S1 never-write and S7 negative-test style;
  offloader lacks S2 serial, S4 job re-entry, S6 state machine, and Windows
  reserved names (`MISSING`).
- Contamination incident (recorded, not hidden): offloader's `xxhash` was
  accidentally installed into the repo venv, flipping
  `test_xxhash_fallback_to_md5` to a false failure; resolved with
  `pip uninstall offloader xxhash reportlab` and a clean repo-venv rerun
  (113 passed). Engine suites now run only in `venv-engines`.

### Added — DIT 2.2 P07 fault-injection differential harness (2026-10-24)

- `tests/fixtures/dit22/fault_matrix.py` — 16 deterministic synthetic
  scenarios, each tagged with one of four classifications
  (`ENGINE_NATIVE` / `DIT_ADAPTER_GUARD` / `MOCK_SIMULATION` / `HW_BLOCKED`)
  so the report can separate native engine behavior, adapter-added
  protection, pure mock/simulation, and untested-on-real-hardware cases.
- `tests/test_dit22_fault_matrix.py` — 20 tests. The S6 guard cases drive
  the P05.1 `reuse_eligibility()` gate directly: a forged `verified=True`
  with no readback evidence, a forged failure_domain, and missing readback
  all come back `BLOCKED`; the positive control is
  `ELIGIBLE_FOR_REVIEW` (never `SAFE_TO_FORMAT`).
  `test_no_scenario_yields_false_safe_to_format` is the aggregate
  zero-tolerance assertion.
- TDD caught 2 real bugs while going red→green: a double-`A` reel-name
  bug (`A001`→`AA0010101.A`) that made every scenario raise
  `FileNotFoundError`, and a missing `outside_secret` key in the symlink
  scenario state. Both fixed minimally → 20/20 green.
- Full regression now **113 passed, 0 failed** (93 prior + 20 new);
  `ruff check` clean on all four touched files.
- `HARDWARE_BLOCKED` items (real NAS / real SD re-connect identity /
  power-loss) build the scenario state + contract asserts only — no
  fabricated device or benchmark data.

### Added — v4 dual-machine landing plan (2026-06-05)

This is the **plan-freeze snapshot** of the v4 architecture. The plan
is complete; deployment awaits the two physical machines.

#### Top-level (GitHub landing)
- `README.md` — GitHub landing page
- `LICENSE` (MIT, code) + `LICENSE-DOCS` (CC BY-SA 4.0, docs)
- `CHANGELOG.md` (this file)
- `CONTRIBUTING.md` — how to contribute
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- `SECURITY.md` — vulnerability reporting
- `.gitignore` — excludes models, venv, qdrant storage, mnemosyne db, _backups

#### GitHub workflows + templates
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/hardware_profile.md` (v4-specific: collect M1 vs workstation config)
- `.github/ISSUE_TEMPLATE/skill_proposal.md` (Hermes skills)
- `.github/ISSUE_TEMPLATE/documentation.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/ci.yml` (pytest on push/PR)
- `.github/workflows/markdown-link-check.yml`
- `.github/workflows/structure-check.yml` (ensures docs/, src/, tests/ layout)

#### Documentation — `docs/`
- `docs/00_index.md` — master index
- `docs/01_對話與調研紀錄/` — 8 research-log files:
  - `2026-06-05_v4規劃會話紀錄.md` — full v4 planning session
  - `2026-06-05_調研思考鏈.md` — chain-of-thought for the v4 plan
  - `2026-06-05_架構A_vs_B_決策矩陣.md` — Architecture A vs B comparison
  - `2026-06-05_模型選型_Qwen3.6_vs_Gemma4.md` — model selection rationale
  - `2026-06-05_Hermes生態調研紀錄.md` — Hermes/Mnemosyne/agentskills.io
  - `2026-06-05_開源組件調研紀錄.md` — other open-source components
  - `2026-06-05_風險登錄.md` — risk log narrative
  - `2026-06-05_開放問題Q01-Q08.md` — 8 open questions
- `docs/02_方案文檔/` — 16 plan/guide files:
  - `AGENTS.md` — project entry, invariants
  - `個人AI第二腦落地方案_v4.md` — **master plan, 27 sections**
  - `架構B_開源組件整合表.md` — open-source component table
  - `Hermes_Agent_整合指南.md` — Hermes Agent integration
  - `Phase_0_啟動手冊.md` — Phase 0 (1 day, bootstrap)
  - `Phase_1_部署指南.md` — Phase 1 (2-3 days, deploy services)
  - `Phase_2_索引流水線指南.md` — Phase 2 (3-4 days, indexer)
  - `Phase_3_Hermes整合指南.md` — Phase 3 (5-7 days, Hermes + skills)
  - `Phase_4_評估與回饋指南.md` — Phase 4 (ongoing, eval)
  - `Phase_5_進階路線指南.md` — Phase 5 (advanced, ongoing)
  - `評估測試集_v2.md` — 100-entry eval set (human-readable)
  - `風險登錄表.md` — 20 risks, P × I matrix
  - `Hermes_Skill_範本庫.md` — skill templates catalog
  - `Open_WebUI_整合指南.md` — Open WebUI wiring
  - `Tailscale_私網設定指南.md` — Tailscale mesh + ACL
  - `RPC_拆分指南.md` — RPC splitting for context safety
- `docs/03_架構圖_SVG/` — **11 hand-crafted SVG diagrams** (dark theme):
  - `00_雙機拓樸圖.svg` — M1 + workstation topology
  - `01_Phase0_啟動流程圖.svg` — Phase 0 flow
  - `02_Phase1_服務部署圖.svg` — Phase 1 service deployment
  - `03_Phase2_索引流水線圖.svg` — Phase 2 indexer pipeline
  - `04_Phase3_Hermes技能調用圖.svg` — Phase 3 skill invocation
  - `05_Phase4_評估回饋圖.svg` — Phase 4 eval feedback loop
  - `06_Phase5_進階路線圖.svg` — Phase 5 roadmap
  - `07_Tailscale私網圖.svg` — Tailscale mesh
  - `08_記憶寫入路徑圖.svg` — Memory write paths (Mnemosyne)
  - `09_查詢路由圖.svg` — Query routing (text vs image vs cross-modal)
  - `10_風險熱力圖.svg` — Risk P × I heatmap
- `docs/06_備份與同步/` — 4 sync/restore files:
  - `同步策略.md` — 3-2-1 backup rule, 4-layer L0-L4
  - `sync_raid.sh` — L0/L1 → L2 (RAID) rsync + rotation
  - `sync_onedrive.sh` — L2 → L3 (OneDrive + rclone crypt)
  - `版本標籤規範.md` — `v{M}.{m}.{p}-{date}-{phase}` convention
  - `還原演練.md` — 6 DR scenarios A-F, quarterly drills

#### Source code — `src/`
- `src/hermes_skills/qdrant-search/` — full skill:
  - `SKILL.md`, `manifest.json`, `README.md`
  - `src/qdrant_server.py` (144 lines, MCP stdio)
  - `tests.py` (62 lines, pytest)
- `src/hermes_skills/filesystem-search/` — full skill:
  - `SKILL.md`, `manifest.json`, `README.md`
  - `src/filesystem_server.py` (173 lines, FileDB SQLite)
  - `tests.py` (89 lines, pytest)
- `src/hermes_skills/video-slice/` — full skill:
  - `SKILL.md`, `manifest.json`, `README.md`
  - `src/video_slice_server.py` (222 lines, PySceneDetect + ffmpeg)
  - `tests.py` (63 lines, pytest)
- `src/launchd/` — 6 macOS launchd plists:
  - `ai.brain.ollama.plist`
  - `ai.brain.qdrant.plist`
  - `ai.brain.hermes.plist`
  - `ai.brain.indexer.plist`
  - `ai.brain.openwebui.plist`
  - `ai.brain.rpcserver.plist`
- `src/systemd/` — 3 Linux systemd units:
  - `ai-brain-llama-server.service` (with `OOMScoreAdjust=-100`, `MemoryMax=18G`)
  - `ai-brain-qdrant-mirror.service`
  - `ai-brain-rpc-server.service`
- `src/tailscale/acls.json` — tag-based ACL config (tag:m1, tag:station, tag:phone)
- `src/ollama/Modelfile.gemma4` — Gemma 4 E2B model spec for `hermes-edge`
- `src/scripts/` — 8 Python + bash scripts:
  - `indexer.py` (300 lines, single-worker, v3 invariant enforced)
  - `qdrant_snapshot.py` (92 lines, snapshot + verify + rotate)
  - `mnemosyne_backup.py` (56 lines, sqlite3 hot backup)
  - `eval_runner.py` (137 lines, runs 100-entry eval set)
  - `ralph_watchdog.py` (Hermes watchdog)
  - `snapshot.sh` (35 lines, rsync mirror)
  - `phase0_bootstrap.sh` (Phase 0 setup)
  - `benchmark_llm.sh` (LLM perf benchmark)

#### Tests — `tests/`
- `tests/eval_v2_100.jsonl` — **100-entry machine-readable eval set**
  - 8 categories: text-direct, image-direct, cross-modal, temporal,
    tag-based, conversational, tool-use, edge-case
  - 39% easy / 47% medium / 14% hard
- `tests/conftest.py` — shared fixtures (tmp dir, mock HTTP, in-memory Qdrant)
- `tests/test_index_pipeline.py` — 16 unit tests for indexer.py
- `tests/test_qdrant_named_vectors.py` — invariant tests for Named Vectors
- `tests/test_mcp_servers.py` — stdio-loop tests for all 3 skills
- `tests/test_hermes_skills.py` — subprocess integration tests
- `tests/requirements.txt` — pytest 8.3.4 + qdrant-client 1.12.1 + scenedetect 0.6.7 + ...
- `tests/README.md` — how to run

#### Archive — `_archive/`
- `_archive/2026-06-05-v4-plan/` — snapshot of v4 plan at freeze:
  - `README.md` — archive overview
  - `manifest.json` — SHA-256 + size for all 105 files (verified)
  - `verify.py` — checks current repo against manifest (passes: 105/105)
  - `restore.sh` — restore instructions
  - `CHANGELOG.md` — what was new in v4 vs v3

### Preserved from v3 (DO NOT BREAK)

- **Single worker indexer** — enforced via `if self.workers != 1: raise ValueError`
  and tested by `test_config_rejects_workers_greater_than_one`
- **Qdrant Named Vectors** — `text_vec(768) + image_vec(512)` per point,
  tested by `test_indexer_uses_text_vec_named_vector`
- **Memory never forgotten** — original files preserved, index rebuildable
- **Never auto-move** — indexer suggests via `suggested_move` field, never mutates
- **No facial / voice emotion monitoring**
- **Local-first AI only** — 100% on hardware, no cloud fallback
- **PySceneDetect 0.7 AdaptiveDetector** with 10s cap (v3, F1=91.6%)

### Changed

- Migrated from v3 self-built agent to Hermes Agent v1.x (MIT, 162K★)
- Migrated from v3 custom memory layer to Mnemosyne (SQLite-only, BEAM 65.2%, LongMem 98.9%)
- Migrated from v3 custom skill format to agentskills.io standard
- Replaced Cloudflare-edge hybrid with Tailscale mesh
- Adopted Open WebUI for the Web front-end
- Reorganized to GitHub-ready layout (docs/, src/, tests/, examples/, .github/)
- **License changed from MIT to AGPL-3.0-or-later** (2026-06-05): Root `LICENSE` replaced with FSF AGPL v3 text; SPDX header added. `README.md`, `CONTRIBUTING.md`, `docs/00_index.md`, and all 3 skill `manifest.json` updated. Old MIT references in historical entries (v3 snapshot, Hermes/Mnemosyne attributions) preserved as-is.

### Fixed

- (n/a — initial v4 release)

### Risks

See `docs/02_方案文檔/風險登錄表.md` for the full 20-risk register.
Highlights:
- **R07** (backup failure) — Medium; full mitigation in `docs/06_備份與同步/`
- **R13** (8GB RAM headroom) — Low; ~1GB headroom on M1
- **R18** (Qwen3.6 license check) — Low; will verify before Phase 1

### Deployment plan (next 6-8 weeks)

| Week | Phase | Deliverable |
|---|---|---|
| 1 | Phase 0 | Machines set up, Tailscale mesh live |
| 1-2 | Phase 1 | Ollama + Qdrant + llama.cpp deployed |
| 2-3 | Phase 2 | Indexer pipeline running on M1 |
| 3-4 | Phase 3 | Hermes Agent + 3 skills integrated |
| 4-6 | Phase 4 | Eval set baseline (MRR@10 ≥ 0.6) |
| 6-8 | Phase 5 | Advanced: better embeddings, more skills |

### Research log

See `docs/01_對話與調研紀錄/` for the full session transcripts,
web search records, model selection rationale, and decision matrix
that produced this v4 plan.

### Open questions

See `docs/01_對話與調研紀錄/2026-06-05_開放問題Q01-Q08.md` for the 8
carried-forward questions (M1 Hermes mode, snippet vs chunk, Tailscale
vs Headscale, 27B vs 35B-A3B, MTP on/off, Q3 vs Q4, backup topology,
100 vs 1000 eval).

[Unreleased]: https://github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent/compare/v0.0.0...HEAD
