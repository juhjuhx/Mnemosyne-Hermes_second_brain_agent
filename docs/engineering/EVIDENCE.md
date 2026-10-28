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

## P07.1 addendum + P08 NAS staging atomic commit（2026-10-24）

| # | 動作 | 結果 |
|---|---|---|
| P07.1-a | 獨立審查（deleg_af24866c）6 項全 PASS；其建議「unlisted-path fail-closed 只有代碼保證、無測試釘住」→ 補 `test_unlisted_path_is_fail_closed_non_physical` | commit `8f9dadb`；全量 **123 passed** |
| P08-1 | spec `docs/engineering/spec/P08-staging-atomic-commit.md`（writing-plans 先定契約：mirror≠backup 語意表、fail-closed 狀態機、F12/F13/F14 界面、測試分層 markers） | 落定，未動真實 NAS |
| P08-2 | `src/mnemosyne_dit/staging.py`（`StagedArchive`）+ `tests/test_dit22_staging.py`（11 測試，TDD：Red `ModuleNotFoundError` → Green；抓到 1 真實 bug＝hw_blocked 測試把 `str(dict)` 寫進 JSON） | **11/11 passed**；全量 **134 passed, 0 failed**（123＋11）；ruff 全綠 |
| P08-3 | 關鍵語意實測證據 | partial 絕不暴露至 target（crash 零容忍）；receipt 最後原子寫入（缺 receipt＝非 committed）；re-hash 不符→`BLOCKED` 不重試；同 `device_id` 多掛載點折 1 域＋「availability, not backup」註記；NAS share/未列出 path 記 0；receipt 篡改→`StagingConflictError`；冪等重入 no-op |

## P08 addendum + P09 durable job control（2026-10-24）

| # | 動作 | 結果 |
|---|---|---|
| P08-r | P08 獨立審查（deleg_c9de4a9a）6 項全 PASS；非阻塞觀察「commit()/resume() 帶未使用的 provider 參數」→ 移除 dead surface | commit `cf349de`；staging focused **11 passed**、ruff 全綠 |
| P09-1 | spec `docs/engineering/spec/P09-durable-job-queue.md`（writing-plans 先定 F17 契約：冪等 enqueue、lease 排他＋過期接管、checkpoint 重入、input manifest 漂移、不可逆輸入絕不自動重試、多 worker 不違反舊 indexer） | 落定，純 stdlib SQLite，獨立 `dit22_jobs.db` |
| P09-2 | `src/mnemosyne_dit/job_queue.py`（`DurableJobQueue`）+ `tests/test_dit22_job_queue.py`（13 測試，TDD：Red `ImportError` → Green；抓到 1 真實 bug＝`verify_manifest` 對已 JSON-decode 的 dict 再 `json.loads`） | **13/13 passed**；全量 **147 passed, 0 failed**（134＋13）；ruff 全綠 |
| P09-3 | 關鍵語意實測證據 | 同 `idempotency_key` 重入回同 job_id 不增列；未過期他人 lease→`LeaseHeldError`、過期接管 attempt+1、同 worker 重 lease 自己 no-op；manifest 漂移→`FAILED`；`reversible=False` FAILED 後 `retry()`（含 `authorize_manual=True`）→`IrreversibleRetryError`，唯一出路開新 key；v4 隔離＝monkeypatch `sqlite3.connect` spy 斷言零開啟 v4 路徑 |
| P09-r | P09 獨立審查（deleg_5a3282cb）7/7 PASS；其 flag 的真實路徑「read-then-unconditional-UPDATE 在多過程對同一 PENDING/過期 job 同時搶租可雙重持有 live lease」→ **CAS 硬化**：`lease()` 的取租 UPDATE 加 WHERE 條件（`state IN ('PENDING','PAUSED') OR (LEASED AND 過期)`）＋ `rowcount==0` 即敗者 `LeaseHeldError`；connection 加 `busy_timeout=5000` 讓敗者重評估贏家已提交行。另釘 2 確定性測試：`test_cas_second_stale_take_lease_cannot_win`（同取租 UPDATE 連發 2 次，第 2 次 `rowcount==0`、`attempt` 只 +1）＋ `test_expired_takeover_via_second_connection_bumps_attempt_once`（第二連線接管） | commit `e1cfa4d`；P09 focused **15 passed**、全量 **149 passed**、ruff 全綠。多過程公平仲裁仍依 spec §2.6 延後至 ADR-DIT2-003，本次只封閉「雙重 live lease」與「stale 二次接管」路徑 |
| P09.1-1 | spec §4 addendum（writing-plans）：lease fencing 契約 + 外部副作用 fencing 評估（DB CAS 不等於外部檔案防護，P11 proxy 須沿用 P08 receipt shape 並記 `job_id`+`lease_token`）＋6 情境測試矩陣 | 落定於 `docs/engineering/spec/P09-durable-job-queue.md` §4，不擴大 ADR-DIT2-003 部署權限 |
| P09.1-2 | `job_queue.py`：新增 `LeaseFencedError`＋`_fenced_update()`（單一 conditional UPDATE 把完整 fence 塞進 WHERE）；`update_checkpoint`/`pause`/`fail`/`complete` 改 `token=` 必填並經 fenced write；`_assert_leased_to` 加 token 快查（advisory，權威判定在 write 時） | **TDD Red→Green**：9 個 fenced 測試先 Red（P09 只比名稱 → stale 寫入成功）→ 修後 Green |
| P09.1-3 | 關鍵實測證據（`tests/test_dit22_lease_fencing.py`，9 測試全 `@behavior_tested`） | stale token（過期被 w2 接管後 w1 舊 token）對 checkpoint/pause/fail 全 raise `LeaseFencedError` 且 w2 狀態 untouched；同名重啟：新 token 收、舊 token 拒、`attempt`=2；跨連線 stale complete fenced（job 仍 LEASED to w2、`fail_reason` 空）；valid token 下 drift→`FAILED` 與 DONE happy path 不變；fenced 呼叫絕不靜默成功（DONE/FAILED 上連原本有效的 token 也 fenced） |
| P09.1-4 | 收口 | P09.1 focused（fencing 9＋job_queue 15）**24 passed**；全量 **158 passed, 0 failed**（149＋9）；ruff 全綠；v4/媒體/雲端未碰；ADR-DIT2-003 多 worker 部署權限未動 |
| P09.1-r | P09.1 獨立審查（deleg_e2e10053）8 項全 PASS；fence 五條件齊備（job_id/state/lease_token/lease_worker/unexpired-now 同句）、四 API 全經 `_fenced_update`、rowcount=0 一律 raise；stale-token/同名重啟/跨連線/expired-complete 全 fenced；drift/DONE 回歸不變；無 silent-success 洞；diff 零 v4/qdrant/indexer/secret 命中；spec §4 明言 DB fence 不覆蓋外部檔案寫入＋P11 receipt 須記 job_id+lease_token； reviewer 唯一 residual（同名同 token no-op）＝P09 既有契約非缺口 | commit `6cf03cd`；reviewer 自跑 **158 passed**＋ruff 全綠（未裝任何套件進 venv） |

## P10 FFprobe 媒體探測（2026-10-24）

| # | 動作 | 結果 |
|---|---|---|
| P10-1 | spec `docs/engineering/spec/P10-media-probe.md`（writing-plans 先定 13 類測試矩陣：精確 Rational FPS／VFR 降級／drop-non-drop TC／color-HDR-rotation／多音軌／損壞-空-未知格式／Unicode／URL 拒絕／sidecar／證據可重建／無樣本 camera family UNVERIFIED／malformed JSON） | 落定；synthetic ffmpeg fixtures、零真實素材、零隱式 URL、唯讀 |
| P10-2 | `src/mnemosyne_dit/media_probe.py`（`MediaProbe`＋`probe()`）＋ `tests/test_dit22_media_probe.py`（19 測試：10 `@behavior_tested` 真 ffmpeg fixture＋9 `@fixture_only` classifier/parser 層） | **19/19 passed**；全量 **177 passed, 0 failed**（158＋19）；ruff 全綠 |
| P10-3 | 關鍵實測證據 | 24p `r_frame_rate=="24/1"` 精確字串、VFR 逐幀 PTS 非等距→`vfr-likely`（`-fps_mode vfr` concat fixture）、29.97 drop 家系、雙音軌 32k/48k 獨立、CJK 路徑 probe 成功、URL 在 subprocess 前被 spy 抓出未執行、空檔零 ffprobe 呼叫、malformed JSON 以 fake ffprobe 落 `ProbeError`、camera family 無樣本全 `verified=False`；本機 ffmpeg 9.0.2 不帶 display-matrix/HDR 進 MP4 stream→該路徑改 crafted ffprobe JSON 於 parser 層驗證（不填假數據） |
| P10-r | P10 獨立審查（deleg_6ca7f297）10 項全 PASS；零 write-path／零 URL→subprocess／VFR-HDR-family 全降級未猜值／零偽樣本宣稱；reviewer 兩個 minor flag 已收：(a) `.x-ocn` 未進 UNVERIFIED 循環→補測試；(b) spec 文書漂移（VFR 門檻 0.5%→實作 5%、HDR 判定比 spec 保守）→spec erratum 落定（VFR 任一正 delta 偏離中位差 >5%；HDR 只認 PQ/HLG transfer 家族＋SDR 需 dual-family，不依 primaries bt2020 單判） | 補正後全量 **177 passed**、ruff 全綠 → commit `46b6605`、push |

## P11 Proxy Generator CPU MVP（2026-10-25）

| # | 動作 | 結果 |
|---|---|---|
| P11-1 | spec `docs/engineering/spec/P11-proxy-generator.md`（writing-plans 先定 10 類測試矩陣：browser H.264 MP4 golden、來源對應抄 P10 probe、verify 損壞 gate、receipt fencing stale-token 偵測、可刪除可重建＋原片 untouched、editor 依 build 能力誠實降級、URL 拒絕、損壞/空來源、不觸升 safety verdict） | 落定；CPU FFmpeg 最小 golden（QSV/Vulkan/OpenVINO 依合約留後段） |
| P11-2 | `src/mnemosyne_dit/proxy_generator.py`（`generate_proxy`／`find_stale_proxies`／`delete_proxies`／`detect_editor_capabilities`）＋ `tests/test_dit22_proxy_generator.py`（16 測試：14 `@behavior_tested` 真 ffmpeg encode+ffprobe 回讀＋2 `@fixture_only` 純邏輯） | **16/16 passed**；全量 **193 passed, 0 failed**（177＋16）；ruff 全綠（TDD red 抓到 3 真 bug：URL 檢查撞 Path collapse、prores `-profile auto` 本 build 不接受、corrupt 來源 probe 失敗未降級致誤走 verify 路徑） |
| P11-r | P11 獨立審查（`deleg_32ec0122`）9/9 PASS。兩 Important＝重入／同 output 路徑碰撞測試缺口 → 已補：產物名改 job-namespace（`{job_tag}__{src.stem}__{profile}{ext}`，異 job 同 source+profile+out 永不碰撞；同 job 重入＝原子替換、不重複）＋2 支新測試 `test_reentry_same_job_is_idempotent_replace`、`test_different_jobs_same_source_do_not_collide`；stale behavior test 斷言同步改 job-namespace 檔名。Minor（orphaned staging dir、receipt 缺 job_id 被當 stale）不影響 MVP，記載於 STATE 已知限制 | 補正後 P11 focused **16 passed**、全量 **193 passed**、ruff 全綠；敏感資訊掃描 0 命中；**commit `3d3a2a7` 已 push**（Draft PR #1 遠端 head 驗證一致） |
| P11-3 | 關鍵實測證據 | browser golden：H.264 yuv420p MP4 ffprobe 回讀 + receipt（`job_id`/`lease_token`/雙 sha256/ffmpeg 版本/argv）同目錄原子發布、staging 清乾淨；editor：本 build `dnxhr` 無、`prores` 有→真 ProRes（`degraded=False`）＋ffprobe 回讀 codec 真值，monkeypatch 無 encoder→誠實 h264＋`degraded=True`；stale-token：同 job 兩次不同 token，`find_stale_proxies` 只列舊 token 產物；原片 untouched：全程 SHA256 相等；損壞 encode→`ProxyVerifyError` 且正式目錄零檔案；URL/空來源在 ffmpeg 前被拒（spy 零呼叫）；verdict：API 無 verdict 表面＋產出目錄僅 proxy/receipt |
| P12-1 | spec `docs/engineering/spec/P12-shot-boundary-detection.md`（三分法嚴禁混淆：固定秒數分段＝工具 confidence=None、真 shot detection＝ContentDiff CPU detector、語義分割＝P13 僅 enum 槽位；segment 保留 source_asset_id/frame range/PTS/timebase/camera reel/detector/model_version/confidence；PySceneDetect＋TransNetV2 adapter 誠實 unavailable；A770＝HARDWARE_BLOCKED） | 落定；CPU/synthetic 優先，不裝 scenedetect/tensorflow 進 v4 共享 venv、不填假 benchmark |
| P12-2 | `src/mnemosyne_dit/scene_detect.py`（`FixedIntervalProvider`／`ContentDiffProvider` 零依賴 CPU；`PySceneDetectProvider`／`TransNetV2Provider` adapter 契約＋`_transnet_boundaries` 純邏輯）＋ `tests/test_dit22_scene_detect.py`（16 測試：9 `@behavior_tested` 真 ffmpeg 合成兩場景 fixture＋ContentDiff 解構、7 `@fixture_only` 純邏輯/unavailable 契約） | **16/16 passed**；全量 **209 passed, 0 failed**（193＋16）；ruff 全綠（TDD 抓到：`_transnet_boundaries` 漏 0→1 轉換、URL 安全門須在 is_available 前、推測 320×240 fallback） |
| P12-r | P12 獨立審查（`deleg_57762b1e`）10/10 PASS（mode separation／source immutability／no-guess values／honest unavailability／contiguity／TransNet 邊界數學／門檻敏感度／marker 分層／實際執行／secret 掃描 全 PASS）。3 Minor 全不影響 MVP：#1 推測 320×240 解像度 fallback → 已改 fail-closed（缺解像度拋 `ProviderError`）＋補 `test_content_diff_refuses_unknown_resolution`；#2 empty-pred `[]` 未釘 → 已補測試斷言；#3 `_frame_context` ValueError 無直測 → 已被 provider refusal 測試間接覆蓋 | 補正後 P12 focused **16 passed**、全量 **209 passed**、ruff 全綠；敏感資訊掃描 0 命中；**commit 待 P12 獨立切片** |
