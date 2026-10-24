# STATE｜Mnemosyne DIT 2.2（更新：2026-10-24 P09 完成時）

## 目標
依 SSOT 完成 P00–P19；當前進度＝P00–P09 + GitHub 交接（Draft PR #1）。

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
- **P07.1：reuse gate 信任鏈補強（TDD Red→Green）→ `tests/test_dit22_gate_trust.py`（9 負向測試）+ `asset_schema.py` gate 修正**：
  - 根因（systematic-debugging）：P05.1 `readback_evidence` 只驗 `verdict=="PASS" and replica_id is not None`——dangling replica、零副本＋PASS、證據綁未驗證副本、跨 asset 錯誤 replica 皆可偽造 readback → false-safe
  - 修正：gate 改查 `verified_by_id`（該 replica 存在 + 屬本 asset + 已驗證），PASS 字串本身不再是信任來源；新增 `device_identity_trusted` gate（僅當注入 provider 時）＋ `independent_domains(provider)` 可注入 device-identity probe（`StaticDeviceIdentityProvider` 假裝置做行為測試，真硬體維持 HW_BLOCKED）
  - P07 矩陣測試按 `fixture_only`（13）／`behavior_tested`（5）／`hw_blocked`（2）標記（markers 於 `tests/conftest.py` `pytest_configure` 註冊）
  - 收口：P07.1 focused 9 passed；全量 **122 passed**；marker 分組 13/5/2 正確；`PytestUnknownMarkWarning`=0；PERF102 為 HEAD 既有（非本切片引入，未碰）
  - P07.1 addendum（獨立審查 `deleg_af24866c` 建議）：補 `test_unlisted_path_is_fail_closed_non_physical` 釘住 provider 未列出 path＝非物理 fail-closed 預設（commit `8f9dadb`；全量 **123 passed**）
- **P08：NAS 資料保全 staging atomic commit（F12/F13/F14 垂直切片）→ `src/mnemosyne_dit/staging.py`（`StagedArchive`）+ `tests/test_dit22_staging.py`（11 測試）+ spec `docs/engineering/spec/P08-staging-atomic-commit.md`**：
  - 狀態機 PENDING→STAGING→HASHED→COMMITTED／INTERRUPTED→resume／BLOCKED，state **由目錄內容推導**（無 journal 檔，崩潰安全）；partial 絕不暴露至 target；receipt 最後原子寫入，缺 receipt＝非 committed archive
  - Mirror≠backup（F13）：`independence_report(provider)` 只信注入 device 指紋——同 `device_id` 多掛載點折 1 域、NAS share／未列出 path 記 0，report 明言 "availability, not backup"
  - 冪等重入＋篡改偵測：`reentry_check()` receipt 與 target 漂移 → `StagingConflictError`＋`BLOCKED`
  - TDD 抓出 1 真實 bug：hw_blocked 測試把 `str(dict)` 寫進 JSON 檔 → 改 `json.dumps`
  - 收口：focused **11 passed**；全量 **134 passed, 0 failed**（123＋11）；ruff 全綠；真 ZFS/NAS/斷電 restore 演練只落 contract（`@hw_blocked`，`result: None` 不填假數據）
- **P08 addendum（獨立審查 `deleg_c9de4a9a` 6/6 PASS 後）：移除 `commit()`／`resume()` 的 dead `provider` 參數（只有 `independence_report` 用 device probe），避免誤導 API**（commit `cf349de`；focused 11 passed、ruff 全綠）
- **P00–P02 獨立重驗（P03-T04）：venv 73 passed exit 0；Draft PR #1 head `bbd6ff7`==local；Addy on-disk=24（修正先前 25，上游 README 數）**
- **P09：durable job control（F17，TDD 垂直切片）→ `src/mnemosyne_dit/job_queue.py`（`DurableJobQueue`）+ `tests/test_dit22_job_queue.py`（13 測試）+ spec `docs/engineering/spec/P09-durable-job-queue.md`**：
  - 純 stdlib SQLite、獨立 `dit22_jobs.db`（caller 指定路徑；**絕不開啟/寫入 v4 `files.db`**，monkeypatch `sqlite3.connect` 偵測證明零接觸）
  - F17 全欄位：`job_id`／`idempotency_key`（同 key＝冪等 no-op）／`input_manifest`（resume/complete 前重驗，漂移→FAILED）／`lease_token`＋`lease_expires_at`（未過期他人 lease→`LeaseHeldError`；過期可接管 attempt+1；同 worker 重 lease 自己＝no-op）／`checkpoint`（pause→resume 保留進度）／`reversible`
  - **不可逆規則**：`reversible=False` 進 FAILED 後 `retry()` 一律 `IrreversibleRetryError`（含 `authorize_manual=True`）；唯一出路＝人工開新 key 新 job
  - 優先級：claim 按 priority desc、同級 FIFO（`seq`）
  - TDD 抓出 1 真實 bug：`verify_manifest` 對已 JSON-decode 的 dict 再 `json.loads` → 雙重解碼
  - 收口：focused **13 passed**；全量 **147 passed, 0 failed**（134＋13）；ruff 全綠；本 module 零 indexer 邏輯（多 worker 不違反舊 indexer 由靜態 import 可證）
  - **P09 CAS addendum（獨立審查 `deleg_5a3282cb` 7/7 PASS 後，封閉其 flag 的雙重 live lease 路徑）**：`lease()` 取租 UPDATE 加 WHERE 條件（只許 `PENDING/PAUSED` 或「已過期的 LEASED」勝出）＋ `rowcount==0` 時敗者丟 `LeaseHeldError`；connection 加 `busy_timeout=5000`；釘 2 確定性測試（同取租 UPDATE 連發 2 次第 2 次必敗、跨連線過期接管 attempt 只 +1）→ P09 focused **15 passed**、全量 **149 passed**、ruff 全綠。多過程公平仲裁維持 spec §2.6 延後 ADR-DIT2-003
- **P09.1：lease fencing 完整性（TDD Red→Green）→ `tests/test_dit22_lease_fencing.py`（9 測試）+ `job_queue.py` fenced conditional write + spec §4 addendum**：
  - 根因：P09 的 `update_checkpoint`／`pause`／`fail`／`complete` 仍是 read-check-write 且只比 worker **名稱**、未強制 `lease_token` → 舊 token（過期被接管後）或同名重啟 worker 可覆寫新持有者狀態
  - 修正：新增 `LeaseFencedError`；`_fenced_update()` 把完整 fence（`job_id`＋`state='LEASED'`＋`lease_token`＋`lease_worker`＋`lease_expires_at > now`）塞進單一 conditional UPDATE 的 WHERE；`rowcount=0` 一律 fail-closed raise（不靜默、不重讀重試）；四 API 簽名改 `token=` 必填（`fail` 的 `reason` 維持位置參數兼容）
  - 外部副作用評估（spec §4.3）：**DB 層 CAS 不等於外部檔案寫入的完整防護**——外部產物由目的地自己的原子契約 fencing（P08 receipt shape）；P11 proxy publish 必須沿用該 shape 並在 receipt 記 `job_id`＋`lease_token`，使被竊 lease 的寫入者產物可偵測可清除
  - 測試矩陣 6 情境全實測：stale token 三寫入全 fenced、同名重啟舊 incarnation 拒／新 token 收、跨連線 stale complete fenced、valid token 下 drift→FAILED 與 happy path 回歸不變
  - 收口：P09.1 focused（fencing 9＋job_queue 15）**24 passed**；全量 **158 passed, 0 failed**（149＋9）；ruff 全綠；未擴大 ADR-DIT2-003 多 worker 部署權限

## 正在做
- P09 CAS 硬化 commit + push（加入 Draft PR #1）；之後 P10：media probe / proxy 生成（依 SSOT 第四輪）

## 失敗/阻塞
- 無 P0 失敗。HARDWARE_BLOCKED：A770、實體 SD/NAS 不在本機（host M1，`torch.xpu.is_available()=False`）→ P07/P08/P14+ 依 SSOT 規則改以 deterministic fixture/unit test 推進並明確標 BLOCKED，不填假數據。
- P09 本切片只落 **狀態儲存**（queue 不跑活）；多 worker 並行執行（ADR-DIT2-003 佇列並行）仍 PROPOSED 待使用者核准，本輪未啟 daemon。

## 雲端 Gemini：0 呼叫、0 費用（v4 local-only 未獲 ADR 核准，維持不變）。

## 下一步
1. P09 獨立審查收口 → P10：media probe / proxy 生成垂直切片（FFprobe 路徑，不碰原始素材，non-destructive）
2. 第四輪 P10–P13（media probe / proxy / 切鏡 / 語義分割）依序推進
3. ADR 四案仍 PROPOSED 待使用者核准（雲端 opt-in／向量 profile 隔離／佇列並行／安全狀態機）
