# P04｜Clean-Room REA Functional Contracts

> 建立：2026-10-24｜分支 `research/dit22-multimodal-handoff-20261024` @ `4797966`
> 目的：把 P03 的 F01–F52（尤其 P0 閉環 F01–F15）收斂為**可測試的 clean-room 功能契約**。
> 方法依 SSOT §4 REA + 附錄 A §10：**研究者只從公開標準/授權開源取結論**，clean-room 開發者
> 只依本契約 + ASC 官方 MHL 標準 + 合法開源依賴寫 code，**不從 arkiv／閉源拷 UI/程式碼**。
>
> **本切片交付的是「契約 + 測試規格 + 隔離邊界」，不是實作。** 實作在 P06/P07（ProofCat vs
> offloader 差分 + 故障注入）。所有 test_spec 先寫測試、後寫 code（TDD）。
> 授權狀態：全部 PROPOSED，v4 七項 invariant 未改。

---

## 0. Clean-Room 隔離邊界（硬規則）

1. **研究面（我）**：讀公開 ASC MHL 標準、ProofCat/offloader 的 MIT 程式碼（依其 LICENSE）、
   ffprobe/ExifTool 文件。**不**讀 arkiv PolyForm 競爭限制下的受限實作；arkiv 只做黑箱行為對照。
2. **clean-room 面（後續實作者）**：只能從「本契約 + ASC 官方 MHL schema 範例 + 合法開源依賴」
   起碼，不照抄 arkiv/閉源 UI 資產；第三方保留 LICENSE/NOTICE。
3. **獨立驗證面**：測試者用 ASC 官方 MHL 樣本、外部 `sha256` 獨立 ground truth、真實 USB/NAS
   故障；**不用同一套程式自產自驗期望值**。
4. 任何第三方 GPL/LGPL 元件（sift-video GPL-3）與 AGPL 主體**分目錄**，保留 NOTICE。

---

## 1. `spec/ingest-safety-contract.md` — Offload 安全核心契約（P0，F04/F06/F08/F09/F10/F11）

**可觀察行為契約**（每項給「預期行為 + 反例」，供 TDD 落測試）：

| # | 契約條款 | 預期行為 | 反例（fail-closed 必拒） | test_spec（P07 故障注入） |
|---|---|---|---|---|
| S1 | Source 只讀 guard（F09） | 複製全程 source 只讀；copy 前後 source hash **必不變** | source 路徑含寫入、symlink→`..`、Windows reserved name → 拒 | `test_source_unchanged_on_copy`：source tree hash 前後比對；dest-in-source → REFUSED |
| S2 | 獨立裝置判別（F06） | 兩 dest 必屬**不同故障域/device fingerprint**；unknown 身分 → `BLOCKED` | 兩 NAS share 同 device → 視為同域，不得 GREEN；同 SSD 兩 mount 同拒 | `test_dest_independence`：同 device 兩 dest → `BLOCKED`；不同 device → 允許 |
| S3 | staging + atomic commit（F04） | 寫入 `.staging/<job-id>` → fsync → readback → rename → manifest seal | 直接在 dest 根寫檔；rename 半途失敗 → 無半成品公開 | `test_staging_atomic`：kill -9 mid-write → 不污染已驗證副本；seal 前 dest 不可見 |
| S4 | 冪等重入（F10） | 已驗證檔重跑 → **跳過/確認**，不新增 `stem_0001`；不覆 good replica | collision 改名污染（naive 現狀 `offload_file` line 131–132） | `test_idempotent_rerun`：verified 後再跑 → 無新檔；good replica hash 不變 |
| S5 | ASC MHL chain（F08） | 產 ASC MHL v2，外部 `ascmitc/mhl` 可 `diff/flatten` 讀取；chain tamper 偵測 | 自造不相容 XML；缺 chain 節點 → 報警 | `test_mhl_interop`：外部工具讀 MHL 成功；tamper chain → `MHL_TAMPERED` |
| S6 | 安全狀態機 fail-closed（F11） | `DISCOVERED→…→VERIFIED_AND_BACKED_UP`；任一 gate 缺 → 停於 BLOCKED，**絕不** false `SAFE_TO_FORMAT` | 缺第二設備即達 GREEN；0B 檔漏驗 → 誤判 | `test_state_machine_fail_closed`：每個 gate 缺一個 → 不得 `REUSE_ELIGIBLE`；false-safe=0（P0 FAIL） |
| S7 | 0B 與 Unicode 邊界（F02/F05） | 0B 檔 verified=true（空 hash 有定義）；萬國碼檔名不 crash | 0B 檔當漏驗；長 Unicode 路徑截斷 | `test_zero_byte_and_unicode`：fixture `zero-byte.A` + `故報緣名サンプル.A` |

**安全 core 候選**（P06 差分）：ProofCat（Rust 核心，fail-closed 狀態機 + 雙實體 dest + MHL）vs
offloader（Python，`--verify full` + 報表 + 歷史兩缺陷回歸）；naive `dit-offload` **不勝出**（缺 S1–S6 全數）。
S2 的 device fingerprint 是**自研**（兩引擎皆需外接），是本契約對引擎的附加要求。

---

## 2. `spec/asset-schema.md` — Canonical ID / 資料模型（P05，F03/F35）

**核心不變量**：`asset_id` 由 **content identity** 定義（`sha256(source bytes)` 或 camera reel+file
identity），**與 path 解耦**；同一檔案在不同 NAS path 有多個 `AssetPathObservation`；
perceptual hash 只表相似性，**不**替代校驗身分。

| 模型 | 必要欄位（最小） | 契約 |
|---|---|---|
| `MediaAsset` | `asset_id, source_sha256, camera_family, card_id, reel, source_path, verified_manifest_id` | path 是 observation 非身分；同 content 同 asset_id |
| `Replica` | `replica_id, storage_id, failure_domain, path, hash, verified_at` | 跨故障域標註；RAID1 非兩副本 |
| `Card/OffloadJob` | `job_id, source_id, state, manifest_root, idempotency_key, lease, attempt` | state 走 S6 狀態機；冪等 key |
| `VerificationEvidence` | `evidence_id, file_id, algorithm, hash, device_id, verdict, generated_at` | append-only；mismatch 警報 |
| `AssetPathObservation` | `obs_id, asset_id, storage_id, path, size, mtime, observed_at` | 同 asset 多路徑；跨磁碟穩定 |

**Migration 規則**（依 v4 invariant，expand→dual-read→backfill→switch→contract）：新 schema 進
**新 `dit22` namespace / 新 collection**；v4 SQLite `files`/`chunks` 與 `text_vec(768)/image_vec(512)`
**只讀不改**（ADR-DIT2-002/003）。

test_spec：`test_asset_id_path_decoupled`（同 content 搬 path → 同 id；異 content 同 basename → 異 id）；
`test_observation_multi_path`（同 asset 兩 storage → 兩 observation，asset 唯一）。

---

## 3. `spec/provider-interface.md` — Embedding / AI Provider Adapter（P14–P16）

**可替換 Provider 契約**：每個 embedding/AI provider 實作同一 adapter interface；**不綁定**
單 GPU / 單模型。關鍵：`embedding_profile_id = model+revision+processor+normalize+dtype/quant
+MRL_dim+sample_policy`；不同 profile **絕不跨空間 cosine**，跨模型只 rank fusion（RRF）。

| 方法 | 輸入 | 輸出 | 契約 |
|---|---|---|---|
| `probe()` | — | `{device, backend, os, driver, runtime, vram, ok}` | **GPU 真用**要 device trace 顯示 `torch.xpu`/OpenVINO `GPU`，非 CPU 偽裝；A770 未連 → `BLOCKED` |
| `embed(modality, media, profile)` | text/image/video(+frames)/audio | `{vector, dim, profile_id, source_hash, latency, peak_vram}` | video 音軌另送；WeMM 不含 audio；Gemini 雲端（需 consent） |
| `health()` | — | `AVAILABLE/UNHEALTHY/DISABLED/PRIVACY_BLOCKED/BUDGET_BLOCKED` | 模型狀態；預設無雲端金鑰仍可本地功能 |
| `cost_estimate(profile, bytes, n)` | 用量 | 費用估算 + 上限 | 雲端 provider 才可估算；local=0 |

Provider 清單（P02 ledger）：`openvino_clip/siglip`（baseline，A 可跑 Intel）、`wemm_xpu`（實驗，A770 未實測→BLOCKED）、
`qwen3vl`（對照）、`gemini2`（雲端，ADR-DIT2-001 未核准前 **0 呼叫**）。

test_spec：`test_provider_probe_device_truth`（CPU 成功不稱 A770；device log 必含真 device）；
`test_profile_isolation`（WeMM 512d 與舊 image_vec(512) 不同 profile、不 cross-cosine）；
`test_gemini_disabled_zero_call`（`cloud.enabled=false` → 零 HTTP、零費用）。

---

## 4. `spec/mcp-tools.md` — MCP read-only / guarded / denied 三層（P18，F38/F39/F41）

**分層**（MCP 只呼叫同一授權 API，無捷徑）：

| 層 | 工具 | 授權 | 契約 |
|---|---|---|---|
| **read-only**（免額外 grant） | `search_media`, `get_asset`, `get_ingest_status`, `get_manifest`, `review_queue`, `dit.vector.profiles`, `dit.jobs.status`, `dit.asset.inspect` | 只讀 | 不產生副作用；回結果可回 source TC/PTS |
| **guarded write**（task scope + grant + 額度） | `start_ingest`(僅批准 source), `verify_copy`, `queue_proxy`, `queue_asr`, `queue_vision`, `propose_tags`, `submit_review_decision`, `export_edit_intent`, `retry_job`, `dit.index.request`, `dit.cloud.estimate`, `dit.cloud.approve`(一次性), `dit.export.otio/edl` | 需 grant | 無 grant → deny + **deny audit log**；額度超限拒；人工決策不被 AI 重跑覆蓋 |
| **denied（絕不提供 Agent 工具）** | `format_card`, `delete_original`, `overwrite_good_copy`, `purge_backup`, `disable_audit`, `bypass_license`, `unlock_pro`, 直接寫 NLE timeline | — | 系統**永不自動** erase card / 刪原片 / 過健康備份；人工獨立核准 + 操作記錄 |

**人審守衛**：`GOOD/NG/REVIEW` 一旦被人工設定，AI 重跑**不得覆蓋**；衝突須顯示 provenance。
**雲端守衛**：`cloud.enabled=false` 預設；任何外傳需 ADR + 項目級 + 批次級雙核准 + 費用上限 +
outbound audit；敏感/可識別人素材一徑拒雲端（invariant 5：不做 facial/voice-emotion）。

test_spec：`test_denied_tools_absent`（tool catalog 無 format/delete/purge/bypass）；
`test_guarded_without_grant_denied`（無 grant 的 write → deny + audit）；
`test_human_review_not_overwritten_by_ai`（人工 NG 重跑 AI → NG 保留）；
`test_cloud_default_off_no_http`（cloud 未啟用 → 0 外傳）。

---

## 5. 收斂判決（證據驅動，非功能分數）

- **安全核心**：自研 fail-closed 狀態機 + device fingerprint（S2/S6）為**必要附加**，兩引擎皆要外接；
  首選掛 ProofCat（Rust 安全狀態機 + MHL 原生），offloader 作 Python 整合/報表對照。naive `dit-offload`
  維持「草稿参考」，**不進 P0 勝出**。
- **不可由功能分數補償的 P0 否決項**：任何引擎若「false SAFE verdict」或「可覆寫 good replica / 原片」
  → 直接否決（SSOT §10.1，safety 30% 權重但為一票否決）。
- 授權：ProofCat MIT(A)、offloader MIT(A，`--verify full` 前置)、ASC MHL 工具 MIT(A)、
  mhl-spec 無授權檔(B，範例 code 複用前先釐清)——見 `dit22-licence-matrix.md`。

## 下一切片

- **P05**：以 `asset-schema.md` 落 `dit22` SQLite/新 collection schema 草圖（新 namespace，v4 只讀）+ migration rollback。
- **P07**：以 `ingest-safety-contract.md` S1–S7 落 `tests/fixtures/dit22/` 故障注入 fixture（synthetic）+ 兩引擎差分 harness。
- **P16**：以 `provider-interface.md` + `mcp-tools.md` 落 Gemini 隔離測試（synthetic + 明示核准，`cloud.enabled=false`）。

> 本契約是「可重現功能合約」，非部署聲明。升 PASSED 須附 P07/P14/P16 的 fresh 故障注入 log + device trace + 獨立 code review（SSOT §7）。
