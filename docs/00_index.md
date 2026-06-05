# Master Index — Mnemosyne v4

> Generated: 2026-06-05 · Status: plan-frozen (awaiting hardware deployment)
> Verified: `_archive/2026-06-05-v4-plan/verify.py` reports 105/105 OK

This is the **single entry point** for every artifact in the v4 plan. Every
file in this repository is reachable from here.

---

## 1. Research & Session Logs (`docs/01_對話與調研紀錄/`)

The "why" behind every decision.

| File | What it contains |
|---|---|
| [`2026-06-05_v4規劃會話紀錄.md`](01_對話與調研紀錄/2026-06-05_v4規劃會話紀錄.md) | Full Q&A session that produced v4 |
| [`2026-06-05_調研思考鏈.md`](01_對話與調研紀錄/2026-06-05_調研思考鏈.md) | Reasoning chain: question → hypothesis → research → decision |
| [`2026-06-05_架構A_vs_B_決策矩陣.md`](01_對話與調研紀錄/2026-06-05_架構A_vs_B_決策矩陣.md) | Why dual-machine won over single-machine |
| [`2026-06-05_模型選型_Qwen3.6_vs_Gemma4.md`](01_對話與調研紀錄/2026-06-05_模型選型_Qwen3.6_vs_Gemma4.md) | LLM selection rationale per machine |
| [`2026-06-05_Hermes生態調研紀錄.md`](01_對話與調研紀錄/2026-06-05_Hermes生態調研紀錄.md) | Hermes Agent + Mnemosyne + MCP research |
| [`2026-06-05_開源組件調研紀錄.md`](01_對話與調研紀錄/2026-06-05_開源組件調研紀錄.md) | Qdrant, PySceneDetect, Open WebUI, Tailscale research |
| [`2026-06-05_風險登錄.md`](01_對話與調研紀錄/2026-06-05_風險登錄.md) | 20 risks identified during planning |
| [`2026-06-05_開放問題Q01-Q08.md`](01_對話與調研紀錄/2026-06-05_開放問題Q01-Q08.md) | 8 questions still open at handoff |

## 2. Plan Documents (`docs/02_方案文檔/`)

The "what" — concrete engineering guidance. 16 files.

| File | Purpose | Audience |
|---|---|---|
| [`AGENTS.md`](02_方案文檔/AGENTS.md) | Project entry point (read this first if you're an AI agent) | AI agents, future-you |
| [`個人AI第二腦落地方案_v4.md`](02_方案文檔/個人AI第二腦落地方案_v4.md) | **The master plan** (27 sections) | Everyone |
| [`架構B_開源組件整合表.md`](02_方案文檔/架構B_開源組件整合表.md) | Component-by-component integration matrix | Implementers |
| [`Hermes_Agent_整合指南.md`](02_方案文檔/Hermes_Agent_整合指南.md) | How to install + configure Hermes Agent | M1 owner |
| [`Phase_0_啟動手冊.md`](02_方案文檔/Phase_0_啟動手冊.md) | Day 1 launch checklist | Implementer, day 0 |
| [`Phase_1_部署指南.md`](02_方案文檔/Phase_1_部署指南.md) | Service deployment (Ollama, llama.cpp, Qdrant, Mnemosyne) | Days 1-3 |
| [`Phase_2_索引流水線指南.md`](02_方案文檔/Phase_2_索引流水線指南.md) | Indexer + worker queue + embedding pipeline | Days 4-7 |
| [`Phase_3_Hermes整合指南.md`](02_方案文檔/Phase_3_Hermes整合指南.md) | Hermes + Open WebUI + skill install | Days 8-14 |
| [`Phase_4_評估與回饋指南.md`](02_方案文檔/Phase_4_評估與回饋指南.md) | Eval suite + ralph-watchdog + iterations | Ongoing |
| [`Phase_5_進階路線指南.md`](02_方案文檔/Phase_5_進階路線指南.md) | llama.cpp RPC split, KTransformers, Graphiti (optional) | Month 2+ |
| [`評估測試集_v2.md`](02_方案文檔/評估測試集_v2.md) | 100 ground-truth eval queries (human-readable table) | Eval phase |
| [`風險登錄表.md`](02_方案文檔/風險登錄表.md) | 20 risks × mitigation × owner × status | Project mgmt |
| [`Hermes_Skill_範本庫.md`](02_方案文檔/Hermes_Skill_範本庫.md) | Skill templates catalog (filesystem, qdrant, video-slice) | Skill authors |
| [`Open_WebUI_整合指南.md`](02_方案文檔/Open_WebUI_整合指南.md) | Open WebUI ↔ Hermes Agent wiring | UI config |
| [`Tailscale_私網設定指南.md`](02_方案文檔/Tailscale_私網設定指南.md) | Tailscale ACLs, DNS, magic DNS | Network setup |
| [`RPC_拆分指南.md`](02_方案文檔/RPC_拆分指南.md) | llama.cpp RPC for future distributed inference | Phase 5 |

## 3. Architecture Diagrams (`docs/03_架構圖_SVG/`)

The "pictures" — 11 hand-crafted dark-themed SVGs, browsable on GitHub.

| File | Diagram |
|---|---|
| `00_雙機拓樸圖.svg` | M1 + workstation network topology |
| `01_Phase0_啟動流程圖.svg` | Day 1 bootstrap sequence |
| `02_Phase1_服務部署圖.svg` | Service install & launch order |
| `03_Phase2_索引流水線圖.svg` | File → chunk → embed → Qdrant flow |
| `04_Phase3_Hermes技能調用圖.svg` | Hermes → MCP → tool sequence |
| `05_Phase4_評估回饋圖.svg` | Eval → ralph-watchdog → fix loop |
| `06_Phase5_進階路線圖.svg` | RPC split + KTransformers upgrade path |
| `07_Tailscale私網圖.svg` | Tailscale ACL & DNS layout |
| `08_記憶寫入路徑圖.svg` | Hermes → Mnemosyne + Qdrant write path |
| `09_查詢路由圖.svg` | Query complexity → which LLM on which machine |
| `10_風險熱力圖.svg` | 20 risks × probability × impact heatmap |

## 4. Code (`src/`)

Runnable artifacts.

| Path | What |
|---|---|
| `src/hermes_skills/qdrant-search/` | Skill: Qdrant vector search via MCP (SKILL.md + manifest.json + src/ + tests + README) |
| `src/hermes_skills/filesystem-search/` | Skill: metadata-based file lookup via MCP (with FileDB SQLite) |
| `src/hermes_skills/video-slice/` | Skill: PySceneDetect + ffmpeg scene splitting via MCP |
| `src/launchd/` | 6 macOS launchd plists (Ollama, Qdrant, Hermes, Indexer, OpenWebUI, RPC server) |
| `src/systemd/` | 3 Linux systemd units (llama-server with OOMScoreAdjust=-100, Qdrant mirror, RPC server) |
| `src/scripts/` | 8 Python + bash scripts (indexer, qdrant_snapshot, mnemosyne_backup, eval_runner, ralph_watchdog, snapshot, phase0_bootstrap, benchmark_llm) |
| `src/tailscale/acls.json` | Tag-based ACL config (tag:m1, tag:station, tag:phone) |
| `src/ollama/Modelfile.gemma4` | Gemma 4 E2B model spec for `hermes-edge` |

## 5. Tests (`tests/`)

| File | What |
|---|---|
| `tests/eval_v2_100.jsonl` | **100 ground-truth queries** (machine-readable JSONL, 8 categories) |
| `tests/conftest.py` | Shared fixtures (tmp dir, mock HTTP, in-memory Qdrant) |
| `tests/test_index_pipeline.py` | 16 unit tests for `indexer.py` (config invariants, chunking, FileDB) |
| `tests/test_qdrant_named_vectors.py` | Tests for `text_vec(768) + image_vec(512)` invariant |
| `tests/test_mcp_servers.py` | stdio-loop tests for all 3 skill MCP servers |
| `tests/test_hermes_skills.py` | Subprocess integration tests (spawn each server, send real JSON-RPC) |
| `tests/requirements.txt` | Test dependencies (pytest 8.3.4, qdrant-client 1.12.1, scenedetect 0.6.7) |
| `tests/README.md` | How to run; coverage map; which file tests which invariant |

## 6. Backup & Sync (`docs/06_備份與同步/`)

The "what if it all breaks" docs.

| File | What |
|---|---|
| `同步策略.md` | 3-2-1 rule, 4-layer L0-L4, per-layer config, cron examples, monitoring |
| `sync_raid.sh` | L0/L1 → L2 (RAID) rsync + 7/30/90-day rotation |
| `sync_onedrive.sh` | L2 → L3 (OneDrive + rclone crypt, 1Password for password) |
| `版本標籤規範.md` | `v{M}.{m}.{p}-{date}-{phase}` convention + `tag_release.sh` template |
| `還原演練.md` | 6 DR scenarios A-F, quarterly drill schedule, log section |

## 7. Archive (`_archive/`)

The "what was the v4 plan at this exact moment" snapshots.

| File | What |
|---|---|
| `_archive/2026-06-05-v4-plan/README.md` | Archive overview + how to verify/restore |
| `_archive/2026-06-05-v4-plan/manifest.json` | SHA-256 + size for all 100 files (verified 100/100) |
| `_archive/2026-06-05-v4-plan/verify.py` | Run against current repo: 100 OK, 0 CHANGED, 0 MISSING |
| `_archive/2026-06-05-v4-plan/restore.sh` | Recovery instructions if git history is lost |
| `_archive/2026-06-05-v4-plan/CHANGELOG.md` | What was new in v4 (vs v3) |

## 8. GitHub root

| File | What |
|---|---|
| `README.md` | GitHub landing page |
| `LICENSE` | AGPL-3.0 (code) |
| `LICENSE-DOCS` | CC BY-SA 4.0 (documentation) |
| `CHANGELOG.md` | Keep-a-Changelog format; `[Unreleased]` = current v4 plan freeze |
| `CONTRIBUTING.md` | How to contribute |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 |
| `SECURITY.md` | Vulnerability reporting policy |
| `.gitignore` | Excludes `models/`, `venv/`, `qdrant_storage/`, `mnemosyne.db`, `_backups/` |
| `.github/ISSUE_TEMPLATE/` | 5 templates (bug, hardware_profile, skill_proposal, documentation, feature_request) |
| `.github/PULL_REQUEST_TEMPLATE.md` | Standard PR template |
| `.github/workflows/` | 3 CI workflows (ci, markdown-link-check, structure-check) |

## 9. Examples & extra docs

| Path | What |
|---|---|
| `examples/README.md` | Examples folder overview |
| `examples/hermes_config.yaml` | Sample Hermes Agent config (models, skills, memory, safety flags) |
| `examples/indexer_config.yaml` | Sample indexer config (paths, workers, file type handlers) |
| `src/llama_cpp/README.md` | llama.cpp build flags + server flags for PRISM-DQ 27B and Carnice 35B-A3B |
| `docs/07_更新日誌/README.md` | Phase-end summary folder (reserved for use after deployment) |

## 10. Repo-wide counts (at snapshot)

| Category | Count |
|---|---:|
| Research logs | 8 |
| Plan documents | 16 |
| SVG diagrams | 11 |
| Hermes skills | 3 (each with SKILL.md + manifest.json + src/ + tests + README) |
| launchd plists | 6 |
| systemd units | 3 |
| Python + bash scripts | 8 |
| Test files | 5 (.py) + 1 JSONL + 1 README + 1 requirements + 1 conftest |
| Backup/sync docs | 5 |
| Issue templates | 5 |
| Workflows | 3 |
| Examples | 3 (README + 2 sample configs) |
| **Total tracked files** | **105** (~507KB) |

## Reading order (suggested)

1. This file (`docs/00_index.md`)
2. **Project entry** → `docs/02_方案文檔/AGENTS.md`
3. **Why v4** → `docs/01_對話與調研紀錄/2026-06-05_調研思考鏈.md`
4. **The plan** → `docs/02_方案文檔/個人AI第二腦落地方案_v4.md`
5. **Day 1** → `docs/02_方案文檔/Phase_0_啟動手冊.md`
6. **Diagrams** → `docs/03_架構圖_SVG/00_雙機拓樸圖.svg`
7. **Verify** → `python3 _archive/2026-06-05-v4-plan/verify.py .` (should report 105/105 OK)

---

## Last updated

2026-06-05 — v4 plan frozen; 105/105 files verified by SHA-256 manifest.
