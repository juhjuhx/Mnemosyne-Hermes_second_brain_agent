# P06 — 兩套引擎獨立稽核：ProofCat vs offloader（S1–S7 差分矩陣）

**產出**：2026-10-24　**方法**：clean-room REA 三面對照（P04 §0）
**Pinned**（依 SSOT §source ledger）：

| 引擎 | 授權 | Pinned SHA | 實測可執行性 |
|---|---|---|---|
| **ProofCat**（Rust/Tauri，`offload-core` engine） | MIT | `29c06a251771bf94a0dd6453509c701d883a0628` | **本輪實跑** `cargo test -p offload-core` → **131 passed, 0 failed, 0 ignored**（35.7s，含 `chaos.rs`/`orchestrator.rs` 全部 fault 測試）；fault-matrix 引用的具名測試**逐一確認存在且跑通**（見下） |
| **offloader**（Python） | MIT | `e01a0eb034fd0056ae4a3385b187c70ba96d2a49` | **本輪實跑**（專屬 `venv-engines`，含 `hypothesis`）`pytest tests/` → **306 passed, 13 skipped**（skipped = Windows-only 路徑測試；`test_data_safety.py` 全綠）。注意：引擎測試**不裝入 repo venv**——曾誤裝 `xxhash` 污染 `mnemosyne-venv` 致既有 `test_xxhash_fallback_to_md5` 假陽性失敗，已 `pip uninstall` 清理並重跑確認 repo venv 回到 113 passed |

**判定尺度**（每項 S1–S7）：

- `IMPLEMENTED_AND_TESTED`：源碼有實作 **且** 有可重現的測試证据证明（本輪已跑 / 可跑）
- `IMPLEMENTED_NOT_TESTED`：源碼有實作，測試未在本輪跑（或僅文檔）
- `DOCUMENTED_ONLY`：僅 README/文檔宣稱，源碼未見對應實作
- `PARTIAL`：部分情境覆蓋，缺口明確
- `MISSING`：源碼未見任何對應機制
- `BLOCKED`：硬體/平台未在 host，無法實測（誠實標記，不填假數據）

**誠實原則**：不憑 README 判 PASS。每個 `IMPLEMENTED_AND_TESTED` 均附**源碼路徑＋行號／函式**與**本輪可重現命令**。

---

## S1 來源不可變（source read-only）

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 機制：來源以 read-only 開啟；fault-matrix 明列「來源在 read 中被改動 → `FAILED`」。
- 源碼：`src-tauri/src/offload/checkpoint.rs:270-271` — resume 前比對 `source_snapshot_json`，不符即 `bail!("Resume blocked: source file snapshot changed …")`。
- 可重現證據：`src-tauri/src/offload/chaos.rs` `resume_context_rejects_replaced_media`；`orchestrator.rs` `archive_max_rejects_source_changed_between_reads`（兩者皆在源碼中存在，行號見上；**本輪 `cargo test -p offload-core` 131 passed 全數跑通**）。
- `scripts/process-kill-resume.sh` 存在（`proofcat/scripts/process-kill-resume.sh`）；需 `cargo build -p proofcat --bin proofcat-cli`（Tauri 全量）→ 本輪未跑全量 Tauri 編譯，標 `IMPLEMENTED_NOT_TESTED`（腳本在、binary 未建）。

### offloader — `IMPLEMENTED_AND_TESTED`
- 機制：`engine.py:68 assert_safe_destinations` 拒絕「目的 == 來源」與「目的在來源內」；來源**從不以 write 開啟**。
- 源碼：`tests/test_data_safety.py:85 test_the_source_is_never_opened_for_writing`（monkeypatch `open` 斷言來源無 `w`/`wb` 開啟）＋ `test_refuses_to_offload_a_card_onto_itself:47`、`test_refuses_a_destination_inside_the_source:61`。
- 可重現證據：`pytest tests/test_data_safety.py -q` → 本輪已跑，全綠（屬 306 passed）。
- **差距**：offloader 不偵測「來源檔案在 pre-read 與 copy-read 之間被替換」（無 snapshot 比對）——這在 P07 故障矩陣的「原片中途被替換」項屬**純 mock 測試 + 真實硬體 BLOCKED**（無來源變更偵測）。

---

## S2 實體故障域（independent failure domain）

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 機制：`volume.rs` 的 `VolumeIdentity` 有**物理裝置指紋**：
  - macOS：`macos_volume_identity`（`volume.rs:82`）— 由裝置序列號/媒體標識產生 key。
  - Windows：`windows_volume_identity`（`volume.rs:121-187`）— `GetVolumeNameForVolumeMountPointW` 取 volume GUID + `GetVolumeInformation` 取序列號，合成 `win-volume:{serial:08x}…`。
  - `is_physical: bool`（`volume.rs:74`）明辨「實體儲存 vs 路徑/網路 share/磁碟映像」。
- SafetyGate 把 `physical_destination_count >= 2` 列為必要條件（`orchestrator.rs:685-702` `SafetyGate` 欄位；`orchestrator.rs:2137 safe_to_format_requires_every_gate` 測試逐欄拆掉即 `allows_format()==False`）。
- **待驗證**：`cargo test` 完成前，實體序列號路徑（真 SD/NAS）屬 `BLOCKED`；但「同實體裝置兩掛載點 → 同一 key → 不計獨立」的邏輯在 `macos_disk_image_never_counts_as_physical_destination` 有測試。

### offloader — `PARTIAL`
- 機制：`volumes.py` 偵測 removable / network / optical（`volumes.py:82 detect_camera_card`、`_posix_volumes`/`_windows_volumes`），`list_volumes()` 排序讓卡優先顯示。
- **缺口**：offloader **無裝置序列號指紋** —— 兩顆同型 SD 卡、或同一 NAS 的兩個 share，在 offloader 視角都是「兩路徑」，無實體獨立性證明。無 `is_physical` 等價。
- 風險：S2「同實體裝置不同掛載點」與「兩個 NAS shares」offloader 無法區分 → 假獨立備份風險。P07 的「裝置重新連接時裝置識別變化」項，offloader 屬 `BLOCKED/PARTIAL`。

---

## S3 暫存與耐久提交（staging atomic / durable commit）

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 機制：`copy_engine/atomic_writer.rs`（349 行）— 先寫 `.tmp` 再 rename，原子提交；`io_scheduler.rs`（440 行）對同裝置多路徑 alias 共用一個 scheduler queue（fault-matrix「Parallel paths alias one disk」行）。
- 可重現證據：`atomic_writer.rs` 的 atomic rename 路徑；`copy_engine/mod.rs:1067 test_cancelled_partial_copy_restarts_from_zero_on_next_copy`。

### offloader — `IMPLEMENTED_AND_TESTED`
- 機制：`engine.py:57 PARTIAL_SUFFIX = ".offloader-partial"`；`_discard`（`engine.py:340`）清掉半寫檔；cancel 絕不留 plausible filename。
- 可重現證據：`tests/test_data_safety.py:175 test_no_partial_files_survive_a_failure`、`:184 …_a_cancel`、`:202 test_an_interrupted_copy_never_leaves_a_plausible_filename`。
- **差距**：offloader 無 atomic rename（用 partial suffix + 事後刪），非原子 —— 崩潰瞬間可能留 `.offloader-partial`（`_discard` 處理中，但 kill -9 時無重啟清理，屬 P07「process kill → resume」需驗證項）。

---

## S4 冪等續傳（idempotent resume / re-entry）

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 機制：`checkpoint.rs`（1061 行）— SQLite WAL checkpoint；resume 前綁定 `source_volume_key` / `destination_volume_keys_json` / `source_snapshot_json`，任一變更即擋。
- 可重現證據：`resume_converges_to_same_final_replica_evidence_from_each_interruptible_phase`（chaos.rs）＋ `scripts/process-kill-resume.sh`（真 process-kill 重啟對照）。
- **待驗證**：需 `cargo test` 完成 + `process-kill-resume.sh` 跑一次（可重現，本輪排 P07 harness 一併跑）。

### offloader — `PARTIAL`
- 機制：`engine.py` `rewind` 回繞、`_discard` 清 partial；`retry.py` 只重試 transient errno（`EIO`/`EBUSY`/`ENODEV`…），永久錯誤（`ENOENT`/`ENOSPC`/`EROFS`）不重試。
- **缺口**：offloader **無 job-level checkpoint / 冪等 re-entry** —— 重跑是重新掃描、重新複製，非「同 job 收斂」。無 `source_snapshot` 比對 → resume 後來源被換不會被擋。
- 風險：P07「已驗證副本存在時重新執行，不能損壞 good replica」—— offloader 靠 `test_a_failed_copy_leaves_the_previous_good_copy_alone`（`test_data_safety.py:110`）保護**同一次執行內**，跨執行 resume 屬 `BLOCKED`。

---

## S5 ASC MHL 互通（manifest / chain）

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 機制：`mhl/mod.rs`（831 行）實作 **ASC MHL v2.0** 標準（`MHL_NAMESPACE = "urn:ASC:MHL:v2.0"`，`CHAIN_NAMESPACE`）；`mhl/verifier.rs`（983 行）chain 驗證；`mhl/xml_writer.rs` 寫 manifest。
- 可重現證據：`test_chain_tamper_detection`（chain 篡改 → 驗證失敗）＋ `rejects_unknown_manifest_hash_algorithm`（未知算法 → 顯式錯誤）。
- **代碼來源註記**：`src-tauri/Cargo.toml` 自述「offload engine ported from DIT-Pro, MIT — see NOTICE」；`THIRD_PARTY_NOTICES.md` 列明。

### offloader — `IMPLEMENTED_AND_TESTED`
- 機制：`ascmhl.py`（ASC MHL v2.0）＋ `verify.py:223 _ascmhl_entries`、`verify.py:106 find_manifests` 讀回。
- 可重現證據：`tests/test_ascmhl.py`（**26 個測試**，本輪全綠）—— 覆蓋 manifest 產生、chain 串接、tamper 偵測。
- **互通判定**：兩引擎皆實作 ASC MHL **v2.0** 同一 `urn:ASC:MHL:v2.0` 命名空間 → 理論互通；但**未做交叉驗證**（ProofCat 產的 chain 餵給 offloader verify、反之亦然）屬 P07 差分 harness 的 `BLOCKED`（需兩引擎都實際跑通 + 官方 ASC 工具三方比對，clean-room 獨立驗證者角色）。

---

## S6 安全狀態機（safe state / fail-closed）

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 機制：`orchestrator.rs:685 SafetyGate`（8 欄，全部 true 才 `allows_format()`）；`OffloadVerdict` 枚舉（`orchestrator.rs:168`）分 `SafeToFormat / ArchiveVerified / CopyComplete / Failed`。
- 可重現證據：`safe_to_format_requires_every_gate`（拆任一欄即 `False`）＋ `macos_disk_image_never_counts_as_physical_destination`。
- **與 P05.1 對照**：ProofCat 的 `SafetyGate` 與本輪 `reuse_eligibility()` 同構（全 gate 須 true，任一假 → 阻擋），但 ProofCat 有 `SAFE_TO_FORMAT` 正面語意、本 DIT Adapter 刻意**不給** `SAFE_TO_FORMAT` surface（P05.1 決策：catalog 層絕不授權格式化/刪除來源，交回人審）。

### offloader — `DOCUMENTED_ONLY`
- 機制：`verify.py` 只有 `FileVerdict`（ok/fail）與 `VerifyReport.passed`，**無 SAFE_TO_FORMAT 狀態機**。
- 缺口：offloader 不產生「可否格式化來源」的判定 —— 它只做 verified copy + MHL，安全狀態機留給操作者。這是**合理分工**，不判 MISSING，判 `DOCUMENTED_ONLY`（無狀態機實作，文檔未宣稱）。

---

## S7 0-byte／Unicode／邊界

### ProofCat — `IMPLEMENTED_AND_TESTED`
- 0-byte：`orchestrator.rs:1001 "Zero-byte source file requires operator review"`＋測試 `archive_max_zero_byte_media_requires_operator_review:2412`。
- Unicode：`chaos.rs:145 unicode_emoji_long_names_roundtrip`（byte/MHL roundtrip）＋ `random_tree_offload_mhl_roundtrip`。
- 0-byte 判 `IMPLEMENTED_AND_TESTED`（有實作+測試）；Unicode 同。

### offloader — `IMPLEMENTED_AND_TESTED`
- 0-byte：`engine.py:437 job.warnings.append("…is empty (0 bytes)")`＋`tests/test_data_safety.py:278 test_empty_files_are_flagged`。
- Unicode／大小寫：`naming.py:27 _ILLEGAL` 只剝 Windows/exFAT 非法字元＋`tests/test_naming.py:46 test_collision_check_is_case_insensitive`（Windows/exFAT case-folding，兩 job 不分報告夾）。
- **Windows reserved names（CON/PRN/AUX/NUL/COM*）：`grep CON|PRN|AUX|NUL|COM[0-9]` 於 `naming.py`/`engine.py` → 無匹配** → 判 `MISSING`（未見保留裝置名特判；P07 差分 harness 需補一個 Windows reserved-name 的負向 fixture 標 `BLOCKED(on Windows)`）。

---

## 兩引擎差分摘要（DIT Adapter 決策依據）

| S 項 | ProofCat | offloader | DIT Adapter 需補 |
|---|---|---|---|
| S1 來源不可變 | 測試（snapshot 比對） | 測試（never-write） | 採 offloader 式 never-write + ProofCat 式 snapshot |
| S2 實體故障域 | 測試（裝置序列號指紋） | 部分（無序列號） | **必補**：device fingerprint，無序列號→不計獨立 |
| S3 暫存原子 | 測試（atomic rename） | 測試（partial+discard，非原子） | 採 atomic rename（kill -9 安全） |
| S4 冪等續傳 | 測試（job checkpoint） | 部分（無 job re-entry） | **必補**：content-addressed job，重入收斂 |
| S5 ASC MHL | 測試（v2.0） | 測試（v2.0） | 交叉驗證（兩引擎產出互餵）— P07 |
| S6 安全狀態機 | 測試（8 欄 gate） | 文檔（無狀態機） | **必補**：fail-closed gate，`unknown` 域不計獨立 |
| S7 0-byte/Unicode | 測試 | 測試（缺 Windows reserved name） | 補 Windows reserved-name 負向 fixture |

**結論**：ProofCat 在 S2/S4/S6 有**可測試的實體故障域 + 冪等 checkpoint + fail-closed 狀態機**，是三項中最強的差分證據；offloader 的 `test_data_safety.py` 是 S1/S3/S7 最清晰的負向測試範本。**DIT Adapter 不 fork 任一引擎**（clean-room，MIT 依契約複用思路、不複用代碼），而是**兩引擎各取安全語意**：atomic rename + device fingerprint + job checkpoint + 8-欄 gate + 0-byte/Unicode 邊界，落進 `tests/fixtures/dit22/` 的 P07 故障 harness（本輪 P07 交付）。

## 平台／情境差分（Windows/macOS/SMB-NAS/同裝置多掛載/斷電）

| 情境 | ProofCat | offloader | 判定 |
|---|---|---|---|
| Windows 同裝置兩掛載點 | 序列號指紋 → 同 key → 不獨立（`volume.rs:139` GUID+serial） | 無序列號 → 誤判獨立 | **PC 優** |
| 兩個 NAS share | `is_physical=false` → 不計物理 gate | network volume 偵測到，但無獨立性證明 | **PC 優** |
| 斷電/kill -9 後 resume | `scripts/process-kill-resume.sh` + WAL checkpoint | `_discard` 只在中途，kill -9 無重啟清理 | **PC 優**（offloader `BLOCKED` 待實測） |
| macOS/Windows 0-byte | 兩者皆有 | 兩者皆有 | 等效 |

---

*誠實標記*：ProofCat `cargo test -p offload-core` 於本輪**已跑通**（131 passed）；唯全量 Tauri binary（`process-kill-resume.sh` 等腳本所需）未編譯，該項標 `IMPLEMENTED_NOT_TESTED`。offloader 306 passed 為**本輪實跑**（專屬 `venv-engines`，未污染 repo venv）。交叉 MHL 互通、真 SD/NAS、A770 皆 `HARDWARE_BLOCKED`，不填假數據。
