# PLAN｜DIT 2.2 工作切片（依 SSOT §8 20-phase 路線縮排為可執行切片）

## 第一輪（P00–P02，本 commit 完成）
- [x] P00：repo 真況盤點（HEAD/dirty/remote/branch）、建立隔離 worktree `research/dit22-multimodal-handoff-20261024`
- [x] P00：讀 root AGENTS + `docs/02_方案文檔/AGENTS.md` + SSOT + Prompt
- [x] P01：Skills 安裝稽核（juhjuhx V3 14-core digest、Addy 25 安裝狀態/授權/namespace）
- [x] P02：來源 ledger（19 repo pin + 授權）與 licence matrix（A/B/C 三類）
- [x] SSOT + Prompt 歸檔至 `docs/research/`；建立 `docs/engineering/{TASK,PLAN,STATE,EVIDENCE,ledger,acceptance-matrix}`
- [x] 既有測試：venv 全量 `pytest tests/` 70 passed（system python 缺依賴 → venv 建檔）
- [x] Draft PR 推上 GitHub

## 第二輪（P03–P05，下一切片）
- [x] P03：F01–F52 需求 map 對照 repo 現況 + 測試規格 → `docs/engineering/spec/F01-F52-requirements-map.md`（DONE0/PARTIAL4/NAIVE2/GAP43/BLOCKED-F42）
- [ ] P03：ADR 四案（雲端 opt-in / 向量 profile 隔離 / 佇列並行 / 安全狀態機）已於 `dit22-architecture-decisions.md` 提出 PROPOSED 狀態，待使用者核准
- [x] P04：clean-room REA 功能契約 → `docs/engineering/spec/P04-clean-room-contracts.md`（§0 隔離邊界 + 4 契約 + 收斂判決；TDD test_spec 落 P07/P16）
- [x] P05：canonical ID / 資料模型 schema 草圖（不改 v4 DB，新 `dit22` namespace）→ `src/mnemosyne_dit/asset_schema.py` + `tests/test_dit22_asset_schema.py`（8 tests PASSED；asset_id=content 與 path 解耦、new-namespace 隔離、multi-path observation、unknown failure-domain 不計獨立備份、evidence ledger、重開重建；TDD 抓出並修 asset-seeding clobber reel 的 bug）

## 第三輪（P06–P09，Offload A/B 差分）
- [ ] P06：ProofCat（pinned 29c06a2）vs offloader（pinned e01a0eb）源碼稽核、功能/授權/失敗矩陣
- [ ] P07：故障注入 fixture（`tests/fixtures/dit22/`，synthetic，零真實素材）
- [ ] P08：NAS mirror≠backup 語意测试 + staging atomic commit 合約
- [ ] P09：durable job queue 幂等/lease 設計（不動 v4 indexer）

## 第四輪（P10–P13）media probe / proxy / 切鏡 / 語義分割（依序，各切片獨立 commit）

## 第五輪（P14–P16）A770/OpenVINO baseline → WeMM/Qwen XPU PoC → Gemini 隔離與費用（HARDWARE_BLOCKED 項以 deterministic 測試推進，標 BLOCKED 不造假數據）

## 第六輪（P17–P19）向量 collection 隔離 + 搜尋融合 → MCP/人審/NLE → 平台驗收與 Draft PR 更新（未授權不 merge）

**規則**：每切片先更新 STATE.md + ledger；安全敏感切片跑獨立 subagent 審查；commit 前 `git diff` 掃 secret/素材；push 後回報 SHA + PR URL。
