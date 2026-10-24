# EVIDENCE｜DIT 2.2 第一輪（P00–P02）

## 執行環境
- Host：macOS（darwin 24.6），Python 3.14.5（system）；venv `/Users/huang/Desktop/dit22-workspace/mnemosyne-venv`
- Git worktree：`/Users/huang/Desktop/dit22-workspace/mnemosyne-dit22`，branch `research/dit22-multimodal-handoff-20261024` @ `ddd79552fde8a1dbc25621dedb0ee8198e772ca6`

## 命令與結果（可重跑）

| # | 命令 | 結果 |
|---|---|---|
| 1 | `git clone --no-checkout` + `git log -1` | main HEAD `ddd7955`（與 SSOT 基線 `ddd79552fde8a1dbc25621dedb0ee8198e772ca6` 完全一致） |
| 2 | `git ls-remote --heads origin 'research/*'` | 無同名分支 → collision-safe 建 `research/dit22-multimodal-handoff-20261024` |
| 3 | `git worktree add -b research/dit22-multimodal-handoff-20261024 …/mnemosyne-dit22` | 成功；`git status` clean（僅新增未追蹤 docs/） |
| 4 | `python3 -m pytest tests/ -q`（system 3.14） | **39 failed / 31 passed**——根因：system python 缺 `qdrant_client`、`watchdog`（未 `pip install -e .`），**非程式回歸** |
| 5 | `python3 -m venv …/mnemosyne-venv && pip install -e ./mnemosyne-dit22 && pip install pytest` | 成功 |
| 6 | `…/mnemosyne-venv/bin/python -m pytest tests/ -q`（worktree） | **70 passed, 5 warnings, exit 0**（初輪）；新增 `tests/fixtures/dit22/` 3 測試後全量重跑 → **73 passed, 4 warnings, exit 0**（本 commit 實際值，獨立 subagent 已重跑確認） |
| 7 | `python3 _archive/2026-06-05-v4-plan/verify.py .`（兩棵 worktree） | **exit 1：61 OK / 44 CHANGED / 0 MISSING**——44 個 CHANGED 檔案最後修改皆 2026-06-05 freeze 後 commit（授權 MIT→AGPL 等），main 自身即不合 manifest；本分支未改 manifest（ADR-DIT2-005） |
| 8 | `gh api repos/<o>/<r>/{commits/HEAD,license,…}` ×19 | 全數成功；pin SHA 與授權記入 `dit22-source-ledger.md` |
| 9 | `git show origin/main:<skill>/SKILL.md | shasum -a 256` ×14 | 14 canonical skills digest 全數取得（`~/.claude/skills/using-superpowers` 與 upstream `590be4c` 逐字一致） |
| 10 | 宿主安裝盤點（`~/.claude/skills/`、`~/.claude/plugins/`） | Addy 25 skills 以 `addyosmani-*` 前鏡安裝；marketplace 克隆 HEAD `13e43f2`；LICENSE = MIT ©2025 Addy Osmani；`commands/` 含 spec/plan/build/test/review/ship 等 8 項 |

## 獨立審查
- Subagent（`claude`）獨立複核：授權結論（arkiv PolyForm、WeMM Apache-2、WrangleBot LGPL、sift-video GPL、無授權檔清單）、pin SHA 表、worktree 狀態、venv 測試、secret 掃描 → 結果已併入本輪（見 STATE.md「獨立 subagent 複核」）。

## 安全與授權狀態
- 雲端 API 呼叫：**0**（Gemini 未啟用，無費用、無外傳）
- 真實素材/相機卡/NAS：**未接觸**（本輪全部 synthetic/文件/上游元資料）
- 第三方授權：arkiv＝C 類（競品限制，僅黑箱參考）；無授權檔來源＝C 類不入 `src/`；GPL（sift-video）＝B 類需分目錄
- v4 七項 invariant：**全數維持**（未改 Qdrant schema、未動 indexer、未開雲端、未自動搬移檔案）

## P03 獨立重驗與校訂（2026-10-24，本輪新執行）

| # | 命令 | 結果 |
|---|---|---|
| P03-1 | `…/mnemosyne-venv/bin/python -m pytest tests/ -q`（獨立重跑） | **73 passed, 0 failed, exit 0**（證實 P00–P02 證據） |
| P03-2 | `gh pr view 1 … --json headRefOid` vs `git rev-parse HEAD` | 皆 `bbd6ff71439fd9920998eed1d8f9696128ab5851`，Draft PR #1 真實存在且與 local 同步 |
| P03-3 | `ls -d ~/.claude/skills/addyosmani-* \| wc -l` + `ls …/addy-agent-skills/skills \| wc -l` | **24 / 24**（修正先前記錄「25」；25 為上游 README 宣稱，本 marketplace 克隆 `13e43f2` 實裝 24） |
| P03-4 | `python3 -c "import torch; …xpu.is_available()"`（host M1） | `torch 2.13.0`，**xpu avail False** → F42/A770 標 HARDWARE_BLOCKED，不填 GPU 成績 |
| P03-5 | 讀 `src/hermes_skills/dit-offload/dit_metadata_server.py` | 定位 naive 安全缺口（collision=改名、無 source guard/MHL/fingerprint/狀態機）→ 寫入 `spec/F01-F52-requirements-map.md` repo_now 欄 |

**記錄校訂**：Addy Osmani 宿主實裝數 = **24**（先前 P00–P02 記「25」，以上游 README 為準；本輪改以檔案證據為準，兩處 ledger 已同步修正）。

## P04 clean-room 契約（2026-10-24）

| # | 動作 | 結果 |
|---|---|---|
| P04-1 | 產 `docs/engineering/spec/P04-clean-room-contracts.md`（§0 隔離邊界 + §1–§4 四契約 + §5 收斂判決） | PASS（docs only）；每契約含「可觀察行為 + 反例 + test_spec」 |
| P04-2 | TDD test_spec 落點 | S1–S7 安全契約 / asset_id 解耦 / provider device-truth / MCP denied-tools 皆列規格；具名測試檔落 P07/P16，**本輪未跑**（`NOT_TESTED(spec-only)`，不造假 GREEN） |
| P04-3 | clean-room 授權邊界 | arkiv 只做黑箱行為對照（PolyForm 競品限制守住）；ProofCat/offloader MIT 依 LICENSE 複用；GPL 元件分目錄；無授權檔（offloadmaster/gemini-multimodal-search/mhl-spec 範例 code）不入 `src/` |
| P04-4 | 收口檢查 | `git diff` 僅 docs；venv `pytest` 73 passed（P04 不改 code）；main 未動；無雲端呼叫 |

## P05 canonical asset schema（2026-10-24，可執行垂直切片）

| # | 動作 | 結果 |
|---|---|---|
| P05-1 | 產 `src/mnemosyne_dit/asset_schema.py`（`Dit22Catalog`，4 表全 `dit22_` 前綴，獨立 `dit22.db`） | PASS；asset_id=content sha256 與 path 解耦；**不碰** v4 `files.db`/Qdrant `text_vec(768)/image_vec(512)`（invariant 1/2/3 維持） |
| P05-2 | `tests/test_dit22_asset_schema.py` 8 契約測試 | **8 passed**；全量 **81 passed**（73 既有 + 8 新，無迴歸） |
| P05-3 | TDD 根因修補：初版 `add_*` 用 `upsert_asset` 把 richer row 的 `reel/card_id` 覆成 default | 改 `_seed_asset`（`INSERT OR IGNORE` 只补缺不覆）→ `test_catalog_persists_across_reopen` 綠 |
| P05-4 | fail-closed 語意：`independent_replicas` 把 `unknown` failure_domain 當**非獨立**備份（鏡 ADR-DIT2-004/F13） | `test_unknown_failure_domain_is_not_independent` 綠 |
| P05-5 | ruff（CI 對齊） | `ruff check src/mnemosyne_dit tests/test_dit22_asset_schema.py` → All checks passed；`ruff format` 2 檔整理 |

## P05.1 安全模型補強（2026-10-24，獨立審查負向測試 → 最小修補）

| # | 動作 | 結果 |
|---|---|---|
| P05.1-0 | 接手重新驗證（**不信任上輪 81**） | branch @ `b8fb0bc` clean、與 origin 同步；fresh full regression **93 passed** 前（81 基線＋12 新增）；本輪重跑數字為依據 |
| P05.1-1 | 獨立審查 5 風險 → `tests/test_dit22_asset_schema_hardening.py`（12 negative tests，先寫） | Red：collection `ImportError`（`EvidenceConflictError`/`ReplicaConflictError`/`reuse_eligibility` 不存在於 module）→ 確立契約缺口 |
| P05.1-2 | 最小修補 `asset_schema.py`（僅 dit22 namespace，v4 零接觸） | `PRAGMA foreign_keys=ON`（前為 SQLite 預設 OFF，REFERENCES 未強制）；`upsert_asset` 改 `COALESCE` gap-fill（已知 card/reel 不被 NULL 覆）；`add_evidence` append-only（同值冪等／異值 `EvidenceConflictError`）；`add_replica` 同 id 異值 `ReplicaConflictError`；新增 fail-closed `reuse_eligibility()`（readback＋trusted-device，缺任一→`BLOCKED`，絕不吐 `SAFE_TO_FORMAT`） |
| P05.1-3 | 負向測試收口 | **12/12 passed**；全量 regression **93 passed, 0 failed**（本輪自己重跑，非引用上輪 81） |
| P05.1-4 | `ruff check` 觸及 3 檔（src＋2 test） | All checks passed（import 排序／blind-exception／SIM117 各 1 修正） |
| P05.1-5 | ledger 純 JSONL 化 | `dit22-skill-execution-ledger.jsonl` 拆純 JSONL（27 記錄＋4 本輪新增＝31，逐行可 parse 0 bad）；14 行混入 markdown 綜合 → 拆至新增 `dit22-skill-execution-report.md` |

## P06 兩引擎獨立稽核（2026-10-24，S1–S7 差分，實跑證據）

| # | 動作 | 結果 |
|---|---|---|
| P06-1 | Pinned 克隆 ProofCat `29c06a2` / offloader `e01a0eb` 至 `refs/`（workspace 外，不入 repo） | 兩 SHA 逐一 `git checkout` 確認 |
| P06-2 | `cargo test -p offload-core`（ProofCat 引擎，Tauri-independent） | **131 passed, 0 failed, 0 ignored**（35.7s）——fault-matrix 具名測試（`chaos.rs`/`orchestrator.rs`）全數跑通；全量 Tauri binary（`process-kill-resume.sh`）未編譯 → 該項 `IMPLEMENTED_NOT_TESTED` |
| P06-3 | offloader 引擎測試（專屬 `venv-engines`，含 `hypothesis`，**不裝入 repo venv**） | `pytest refs/offloader/tests -q` → **306 passed, 13 skipped**（skipped＝Windows-only）；`test_data_safety.py` 全綠 |
| P06-4 | 污染復發與清理：誤將 offloader `xxhash` 裝入 repo venv → `test_xxhash_fallback_to_md5` 假陽性失敗 | `pip uninstall offloader xxhash reportlab` 清污染，repo venv 重跑 → 113 passed（恢復）；引擎測試 thereafter 一律走 `venv-engines` |
| P06-5 | 產 `docs/engineering/spec/P06-differential-engine-audit.md`（S1–S7 逐項判定＋源碼路徑/行號/可重現證據＋平台差分） | 判定：PC S1/S3/S4/S5/S6/S7 `IMPLEMENTED_AND_TESTED`；offloader S1/S3/S5/S7 `IMPLEMENTED_AND_TESTED`、S2/S4 `PARTIAL`、S6 `DOCUMENTED_ONLY`；S2/S7-ReservedName/斷電/真 NAS/真 SD 依情境 `PARTIAL`/`MISSING`/`BLOCKED`；DIT Adapter 必補 S2 device fingerprint、S4 job checkpoint、S6 fail-closed gate（→ P07 落測試） |

## P07 故障注入差分 harness（2026-10-24，synthetic，零容忍 false-SAFE）

| # | 動作 | 結果 |
|---|---|---|
| P07-1 | `tests/fixtures/dit22/fault_matrix.py`：16 個 deterministic 場景，每個帶四值分類（ENGINE_NATIVE / DIT_ADAPTER_GUARD / MOCK_SIMULATION / HW_BLOCKED） | 覆蓋：src==dest、dest 在 src 內、symlink traversal、同裝置兩路徑、兩 NAS share、寫入中斷、磁碟滿、kill+resume、原片中途被替換、重跑損 good replica、裝置重連指紋變、MHL 篡改、0-byte/Unicode/大小寫/Windows reserved name、偽造 verified flag、偽造 failure_domain、缺 readback evidence |
| P07-2 | `tests/test_dit22_fault_matrix.py`：20 測試，S6 三項經 P05.1 `reuse_eligibility()` 實測（`_gate_for`），`test_no_scenario_yields_false_safe_to_format` 為聚合零容忍斷言 | **20/20 passed**；偽 verified/缺 readback → `BLOCKED`、positive control → `ELIGIBLE_FOR_REVIEW`（絕非 `SAFE_TO_FORMAT`） |
| P07-3 | TDD 抓出 2 個真實 bug：①`_make_card` reel 命名 `A001`→`AA0010101.A` 雙 A 錯（全套場景 FileNotFoundError）；②symlink 場景 state 漏 `outside_secret` key | 各修一處 → 綠 |
| P07-4 | 全量回归（repo venv，xxhash 已清） | **113 passed, 0 failed**（93 前＋20 P07）；`ruff check` 觸及 4 檔全綠 |

## P07.1 reuse gate 信任鏈補強（2026-10-24，TDD Red→Green）

| # | 動作 | 結果 |
|---|---|---|
| P07.1-1 | 根因定位（systematic-debugging）：P05.1 `readback_evidence` gate 只驗 `verdict=="PASS" and replica_id is not None`——dangling replica_id、零副本卻有 PASS 證據、證據綁未驗證副本、跨 asset 證據皆被誤判為 readback 成立 | false-safe 信任來源確認；PASS 字串 ≠ 可信任的實際驗證 |
| P07.1-2 | `tests/test_dit22_gate_trust.py` 9 個行為負向測試先寫（TDD Red） | Red：`ImportError: StaticDeviceIdentityProvider`；5 信任鏈案例＋4 注入 provider 案例全數針對缺口 |
| P07.1-3 | `asset_schema.py` 最小修正：gate `readback_evidence` 改查 `verified_by_id`（replica 存在＋屬本 asset＋已驗證）；新增 `device_identity_trusted` gate（僅注入 provider 時）＋ `independent_domains(provider)` ＋ `DeviceIdentity`/`DeviceIdentityProvider`/`StaticDeviceIdentityProvider`（假裝置行為測試，未列出 path → 非物理 fail-closed） | 9/9 GREEN；P05.1 既有 12 gate 測試全數保持綠（同 asset 內掛鉤證據行為不變） |
| P07.1-4 | P07 矩陣測試標記：`fixture_only`（13）／`behavior_tested`（5）／`hw_blocked`（2），markers 於 `tests/conftest.py` `pytest_configure` 註冊（pytest 9 已無 `register_marker`） | 分組驗證：`-m fixture_only` 13 / `-m behavior_tested` 5 / `-m hw_blocked` 2；`-W error::PytestUnknownMarkWarning` 29 passed 0 warning |
| P07.1-5 | 收口 | P07.1 focused **9 passed**；全量 **122 passed, 0 failed**（113＋9）；ruff 觸及 4 檔全綠（`conftest.py` 唯一 PERF102 為 HEAD 既有，非本切片引入，未碰） |
