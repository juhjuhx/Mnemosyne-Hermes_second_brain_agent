# P4 — Integration Contract Audit (read-only trace, no code change)

> **STATUS UPDATE（P12.2 輪，2026-10-28）**：C1/C2/C3/C4/C5 已由 P12.2 實作緩解（`source_pinner.py`／`job_queue.py` C3 預算+後退／`capacity_gate.py`／`path_isolation.py`，全鏈接線＋38 項新行為測試；該輪全量 320 passed，RC-1 加入 `windows_naming` 10 項測試後為 330 passed，見 `P11.1-safety-integration-review.md` §11.3）。C6 本地可為部分完成（`windows_stem_safe`＋UNC `HARDWARE_BLOCKED` 哨兵；RC-1 另立 `windows_naming.py` 命名層）；UNC/SMB 實機持久性維持 HARDWARE_BLOCKED。本文為原始唯讀審計紀錄（各 CHECK 維持當時的 OPEN 判定，**活處置狀態以 §11.3 對照表為準**）。

Scope: `Source Admission → Durable Job Queue → Media Probe → Proxy
Generation → Artifact Recovery → Scene Detection`. 本輪**純唯讀**對帳各層
間的 ID 一致性與 6 項特別檢查；**未修改任何 P12 staged 檔**，未改任何
既有 P11.1 模組。所有結論標 `已緩解`／`OPEN`（附建議處置切片）。

## 1. ID 一致性追蹤（每層的 ID 來源與去向）

| 層 | 產生／消費的 ID | 證據來源 | 一致性 |
|----|----------------|---------|--------|
| **Source Admission** (A) | `job_id`、`asset_id`＝`asset_id_for_file`（內容 sha256）、`replica_id`、`storage_id`、`source_sha256`、`fingerprint` | `admit_source`＋`record_admission_evidence(catalog, …, job_id, evidence_id=f"adm-{job_id}-…")`，證據落 `file_name=admission/{job_id}` | ✅ job/asset/replica/storage 全綁定；`fingerprint` 是決定性身份 |
| **Durable Job Queue** (Q) | `job_id`(uuid4)、`idempotency_key`、`lease_token`(uuid4)、`lease_worker`、`input_manifest`、`attempt` | P09.1 所有 fenced UPDATE 重查 `job_id+LEASED+exact token+worker+unexpired`；`rowcount=0`→`LeaseFencedError` | ✅ lease 語意嚴格；**`input_manifest` 漂移檢查只出現在 `complete/verify_manifest`（見 A3）** |
| **Media Probe** (P) | `source_sha256`、`fps`、`camera_family`、`family_verified`、`timecode`、`vfr_status` | 純內容探測，**無 job_id** | ⚠️ probe 的 `source_sha256` 與 admission 的 `asset_id` **無代碼交叉驗證**（見 A2） |
| **Proxy Generation** (X) | `job_id`、`lease_token`、`generation_tag(token)`、receipt{`job_id`,`lease_token`,`source_sha256`,`proxy_sha256`,…} | receipt 是提交指標；staging 按 `generation_tag` 版本化；conditional publish 依 receipt `job_id` 圍欄 | ⚠️ receipt **只帶 `source_sha256`（＝asset_id），未帶 `replica_id`/`storage_id`**（見 A2） |
| **Artifact Recovery** (C) | 讀 receipt `job_id`＋`lease_token`→`generation_tag`；lease 經 `queue.job_state(job_id)` | `reconcile` 判定 `rec.job_id==job_id`＋SHA 全合；`apply` 僅 live-lease 下變動 | ✅ 與 Q 的 lease truth 一致；receipt 是 commit 記錄 |
| **Scene Detection** (S) | `source_asset_id`、`camera_reel`、`fps`、SceneSegment{…} | 吃 P10 `source_probe`＋`fps`；**無 `replica_id`、無 `input_manifest`** | ⚠️ scene 探測與 queue 的 `input_manifest` 漂移檢查**解耦**（見 A3/A2） |

**核心結論**：全鏈唯一可靠的跨層主鍵是 **`asset_id`（內容 sha256）＋ `job_id`**。
`replica_id`／`storage_id`／`input_manifest` 只在 catalog/queue 各自域內，**未嵌入
artifact receipt 或 SceneSegment**；由 asset→replica 需回 catalog 解析（可解、非直連）。

## 2. 六項特別檢查（逐項判定）

### C1 — Admission 之後來源被替換的 TOCTOU  【OPEN · 高優先】
- `admit_source` 在 **0-B**（編碼前）算一次 `asset_id_for_file`；`generate_proxy`
  編碼**後**才 `probe(src, sha256=True)` 記入 receipt 的 `source_sha256`。
- **兩次哈希之間無相等性檢查**：來源若在 admission→encode 窗被換頁/改寫，
  receipt 記的 `source_sha256` 會**静默**變成新內容，admission 的 `fingerprint`
  仍是舊內容 → 鏈路斷裂且無警報。
- **同型風險**：`content_diff_bounded`（P12.1）與 `validate_editor_proxy`（P11.1-D）
  都吃 `source_probe`，但**都不複核來源位元**是否仍等於 probe/admission 的 SHA。
- **處置建議**：單一 `SourceShaPinner`（admission→probe→receipt→scene 全鏈共享的
  期望 sha256），每層入口再核一次；不符 fail-closed。屬新切片，不在本輪。

### C2 — Source SHA256 漂移  【OPEN · 與 C1 同根】
- 見 C1：drift 目前**只在 queue 的 `complete/verify_manifest` 有檢查**，而
  proxy/scene 管線**未接** `verify_manifest`，改用自己的 `source_sha256`（未 pinner）。
- **處置**：把 queue 的 `input_manifest` 設為**唯一** drift 真相源，receipt 與
  probe 都記錄/對帳同一份 manifest 摘要（見 A3）。

### C3 — Job 重試及資源飽和  【OPEN · 中優先】
- `retry()` 對 **irreversible** job 一律 `IrreversibleRetryError`（✅ 有保護）；
  但 **reversible job 可無限重試**、**無並發 worker 數上限、無整體資源配額**。
- lease TTL 預設 300s，編碼超時 120s：資源飽和時 encode 可能撞超時→kill→重試→
  再飽和，**無 backoff / 配額閘**。
- **處置**：queue 層加 `max_concurrent`＋重試配額（屬 P09 延伸，本輪不實作）。

### C4 — 目的端空間不足  【OPEN · 中優先】
- 無**編碼前** free-space gate；目的目錄滿會落到 ffmpeg `ProxyEncodeError`
  （fail-safe，但事後）。P12.1 的 `plan_budget` 是**記憶體** budget，非磁碟空間。
- **處置**：proxy 發布前依 `planned_bytes`（＝目標代理大小估）對 `out_dir` 做
  `statvfs` 低空間阻擋（對接 Windows census 的 15% 建議預警值；屬正式低空間閘）。

### C5 — 來源與輸出目錄路徑相同  【OPEN · 低優先】
- 若 `out_dir` == 來源目錄：artifact 名 `{job}__{stem}__{profile}{ext}` 與來源檔名
  不同（含 `job_tag`），**不會覆寫來源**；但會**污染來源目錄**（寫入 `.staging/`、
  `.quarantine/` 兄弟目錄）。非破壞性，但會 dirty 來源卷。
- **處置**：文档級警示＋可选的 `out_dir != source_dir` 前置檢查（避免把暫存寫進
  受保護的相機卡/NAS 卷；對「真實 SD/NAS」場景尤其重要）。

### C6 — Windows 保留名稱、Unicode、UNC  【OPEN · HARDWARE_BLOCKED 標記】
- **artifact 檔名**＝`{job_tag}__{stem}__{profile}{ext}`；`job_tag`=uuid4（安全），
  但 **`stem` 直接取自來源檔名**：來源若含 `:`、`\\`、`<`、`>` 或 Windows
  保留裝置名語意（如 `CON`、`NUL`、`COM1`），在 **Windows/NTFS 上會產出非法檔名**。
  （`job__CON__browser.mp4` 的 stem `job__CON__browser` 非保留名、暫安全；
  但 `bad:name` 這類**來源 stem 裡的非法字元**會直傳。）
- **UNC/SMB**：`out_dir` 走 UNC 時跨卷 `os.replace` 非原子（P11.1-C 已標
  HARDWARE_BLOCKED）；本機 M1 **無 Windows 端實測**。
- **處置**：(a) artifact 檔名做 **Windows-safe 淨化**（非法字元 → 置換，保留
  sha 可回溯）；(b) UNC/SMB 場景維持 HARDWARE_BLOCKED，需 Windows 工作站
  實測（對接既有 census，勿在本機 M1 假裝通過）。

### C7 — 測試模式不能冒用正式 Verified Source  【已緩解 ✅】
- `generate_proxy(test_mode=True, catalog=…)` → `ProxyInputError`（A 已釘測試）；
  `test_mode` 路徑**不經 admission gate、不寫 catalog 證據行**（count-before/after
  釘死）；synthetic fixture **無法偽裝成 verified source**。✅ 無缺口。

## 3. 未緩解項的分片建議（**不在本輪實作**，依授權顺序）
1. **SourceShaPinner**（C1/C2 同根）：全鏈單一 drift 真相源，每層入口複核。
2. **低空間阻擋閘**（C4）：`statvfs` 對 `out_dir`，對接 census 15% 預警。
3. **Windows 檔名淨化＋UNC 標記**（C6）：本地可做的淨化邏輯；UNC 實測 HARDWARE_BLOCKED。
4. **重試配額／並發上限**（C3）：queue 層延伸。
5. **out_dir≠source_dir 前置警示**（C5）：非破壞性建議。

## 4. 邊界聲明
- 本審計**純唯讀**，未改 P12 staged 8 檔、未改任何 P11.1 模組、未 commit/push。
- 所列 OPEN 項**無一在此切片實作**（避免擴充 scope）；各附建議分片。
- 與 P11.1-C（crash recovery）、P11.1-D（editor 驗收）、P12.1（記憶體有界）
  已收口切片**正交**：本文只指出**跨層契約缺口**，不重做已完成工作。
