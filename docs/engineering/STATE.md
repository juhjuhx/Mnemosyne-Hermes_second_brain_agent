# STATE｜Mnemosyne DIT 2.2（更新：2026-10-24 P05.1 完成時）

## 目標
依 SSOT 完成 P00–P19；當前進度＝P00–P05.1 + GitHub 交接（Draft PR #1）。

## 本輪重新驗證（不信任上輪數字）
- 接手重驗：branch `research/dit22-multimodal-handoff-20261024` @ `b8fb0bc`，tree clean，與 origin 同步
- 本輪 fresh full regression：venv `pytest tests/ -q` → **93 passed**（P05 前 81 + P05.1 新增 12，0 failed，本輪自己重跑，非引用上輪 81）
- ruff：P05.1 觸及檔案全綠（`All checks passed`）

## 已完成
- 隔離 worktree + 分支：`research/dit22-multimodal-handoff-20261024` @ `ddd7955`（現 HEAD `bbd6ff7`）
- P00/P01：skills 安裝稽核 → `docs/research/dit22-source-ledger.md`（Skills 節）
- P02：19 來源 pin + 授權 → `dit22-source-ledger.md` + `dit22-licence-matrix.md`（A/B/C）
- SSOT + Prompt 歸檔 → `docs/research/Mnemosyne_DIT_2_2_CONSOLIDATED_MASTER_2026-10-24.md`（SHA-256 `18e0afc7…`）/ `Mnemosyne_DIT_2_2_CLAUDE_CODE_AUTONOMOUS_PROMPT_2026-10-24.md`（SHA-256 `79e44181…`）
- ADR 四案（PROPOSED）→ `docs/research/dit22-architecture-decisions.md`
- ledger → `docs/engineering/dit22-skill-execution-ledger.jsonl`
- 獨立 subagent 複核：授權結論、pin SHA、worktree 狀態、venv 測試、secret 掃描
- **P03：F01–F52 需求 map + 測試規格 → `docs/engineering/spec/F01-F52-requirements-map.md`（grounded in real source：indexer.py / naive dit-offload / dit-metadata / dit22 fixtures；DONE 0 / PARTIAL 4 / NAIVE 2 / GAP 43 / HARDWARE_BLOCKED F42）**
- **P04：clean-room REA 功能契約 → `docs/engineering/spec/P04-clean-room-contracts.md`（§0 三面隔離 + §1 ingest-safety S1–S7 + §2 asset-schema + §3 provider-interface + §4 mcp-tools 三層 + §5 收斂判決；TDD test_spec 落 P07/P16，本輪標 spec-only 不造假 GREEN）**
- **P05：canonical asset/observation/replica 資料模型可執行垂直切片 → `src/mnemosyne_dit/asset_schema.py` + `tests/test_dit22_asset_schema.py`（8 tests PASSED；asset_id=content 與 path 解耦、獨立 dit22.db 不碰 v4、unknown failure-domain 不計獨立備份；TDD 抓出並修 asset-seeding clobber bug）→ 全量 81 passed、ruff clean**
- **P05.1：安全模型補強（獨立審查負向測試）→ `tests/test_dit22_asset_schema_hardening.py`（12 negative tests）+ `src/mnemosyne_dit/asset_schema.py` 最小修補**：
  - `independent_replicas()` 純 advisory，module 無 `SAFE_TO_FORMAT` surface；新增 fail-closed `reuse_eligibility()` gate（readback 證據 + 無 untrusted device，缺任一 → `BLOCKED`）
  - `add_evidence()` 由 `INSERT OR REPLACE` 改 append-only：同 id 同值 = 冪等 no-op；不同值 raise `EvidenceConflictError`（首錄 verdict 權威，不可翻案）
  - `upsert_asset()` 改 `COALESCE` gap-fill：已知 card_id/reel 絕不被後續 NULL 覆寫
  - `PRAGMA foreign_keys=ON`（SQLite 預設 OFF，先前 REFERENCES 未強制）
  - `add_replica()` 同 id 異值 raise `ReplicaConflictError`（阻擋 S5 篡改路徑）
  - TDD：先 Red（collection ImportError 確認缺 3 符號）→ 最小修正 → 12/12 Green；全量 93 passed 無迴歸、ruff 全綠
  - **未動 v4 索引契約**（獨立 `dit22` namespace；`PRAGMA foreign_keys`/`COALESCE`/gate 全在 P05 `asset_schema.py` 內）
- **P05.1：`dit22-skill-execution-ledger.jsonl` 拆純 JSONL**：27 機器記錄留 `.jsonl`（逐行可 parse，0 bad），14 行混入之 markdown 綜合拆至新增 `dit22-skill-execution-report.md`（人類可讀）
- **P06：兩引擎獨立稽核 → `docs/engineering/spec/P06-differential-engine-audit.md`（S1–S7 差分矩陣＋源碼路徑/行號＋可重現證據）**：
  - Pinned 克隆 ProofCat `29c06a2`／offloader `e01a0eb` 至 workspace `refs/`（不入 repo）
  - ProofCat `cargo test -p offload-core` → **131 passed**（本輪實跑）；offloader（專屬 `venv-engines`）→ **306 passed, 13 skipped**
  - 判定：PC 強於 S2（device 序列號指紋）/S4（job checkpoint）/S6（8 欄 SafetyGate）；offloader 強於 S1 never-write／S7 負向測試範本；offloader 缺 S2 序列號、S4 job re-entry、S6 狀態機、Windows reserved name（`MISSING`）
  - 污染事件：誤裝 offloader→xxhash 進 repo venv 致 1 既有測試假陽性 → `pip uninstall` 清理，repo venv 重跑 113 passed 恢復；引擎測試 thereafter 一律 `venv-engines`
- **P07：故障注入差分 harness → `tests/fixtures/dit22/fault_matrix.py`（16 場景×四值分類）+ `tests/test_dit22_fault_matrix.py`（20 測試）**：
  - 四值分類：ENGINE_NATIVE／DIT_ADAPTER_GUARD／MOCK_SIMULATION／HW_BLOCKED；false `SAFE_TO_FORMAT` 零容忍由 `test_no_scenario_yields_false_safe_to_format` 聚合斷言（偽 verified flag／偽 failure_domain／缺 readback 全 `BLOCKED`，經 P05.1 `reuse_eligibility()` 實測）
  - TDD 抓出 2 bug：reel 雙 A 命名（全場景 FileNotFoundError）、symlink 場景 state 漏 key；各修一處 → 20/20 GREEN
  - HW_BLOCKED 項（真 NAS／真 SD 重連指紋／斷電）只建 scenario 狀態＋contract assert，不填假數據
- **P06/P07 收口**：全量回归 **113 passed, 0 failed**（93＋20）；ruff 觸及 4 檔全綠；skills ledger 37 條純 JSONL（0 bad）
- **P00–P02 獨立重驗（P03-T04）：venv 73 passed exit 0；Draft PR #1 head `bbd6ff7`==local；Addy on-disk=24（修正先前 25，上游 README 數）**

## 正在做
- P06/P07 commit + push（加入 Draft PR #1），然後 P08/P09 依依賴順序推進

## 失敗/阻塞
- 無 P0 失敗。HARDWARE_BLOCKED：A770、實體 SD/NAS 不在本機（host M1，`torch.xpu.is_available()=False`）→ P07/P14+ 依 SSOT 規則改以 deterministic fixture/unit test 推進並明確標 BLOCKED，不填假數據。
- 雲端 Gemini：0 呼叫、0 費用（v4 local-only 未獲 ADR 核准，維持不變）。

## 下一步
1. P06：ProofCat（pinned 29c06a2）vs offloader（pinned e01a0eb）源碼稽核、功能/授權/失敗矩陣；以 P04 S1–S7 安全契約作差分基準
2. P07：以 S1–S7 落 `tests/fixtures/dit22/` 故障注入 fixture（synthetic）+ 兩引擎差分 harness
3. P09：durable job queue 幂等/lease 設計（用 P05 `dit22` catalog 存 job，不碰 v4 indexer）
