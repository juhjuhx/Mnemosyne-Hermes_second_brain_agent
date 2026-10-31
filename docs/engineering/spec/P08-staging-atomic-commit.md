# P08 — NAS 資料保全：staging atomic commit 契約（F12/F13/F14）

**產出**：2026-10-24　**方法**：writing-plans 先定契約 → TDD 垂直切片 → 獨立審查
**範圍**：純 stdlib、synthetic、獨立 `dit22` namespace；**不碰** v4 `files.db`／Qdrant／NAS 實體（NAS/ZFS/SMB 實品維持 `HARDWARE_BLOCKED`）。

## 1. 語意契約（Mirror ≠ Backup）

SSOT §NAS 策略：Mirror/RAID1 用於**可用性**，不算獨立備份。P08 把它落成可測試語意：

| 術語 | 定義 | 是否計獨立備份 |
|---|---|---|
| **staging 檔** | 正在寫入、未 commit 的副本；崩潰可丟棄 | 否 |
| **COMMITTED 檔案** | hash recheck 通過＋原子暴露（receipt 寫入）| 是（一個故障域） |
| **mirror/RAID1 路徑** | 與已知裝置同一 `device_id` 的多掛載點 | **否**（同域折疊，可用性≠備份） |
| **兩 NAS shares 同 appliance** | 同一 appliance 序列號 | **否**（同故障域） |
| **不同物理裝置各一副本** | 不同 `device_id`、皆 `is_physical` | 是（每裝置一域） |
| **network/optical/未列出 path** | provider 判非物理或 unknown | **否**（fail-closed） |

## 2. 狀態機（fail-closed）

```
PENDING → STAGING（寫入）→ HASHED（manifest 全數 recheck 通過）→ COMMITTED（原子暴露＋receipt）
             │崩潰/kill
             ▼
        INTERRUPTED → resume：全數 re-hash → 全合：COMMIT   │ 任一不合：BLOCKED（絕不暴露 partial）
                          discard：移除 staging             │
                                          COMMITTED ── 冪等重入（同 receipt no-op）
```

**硬性規則**：
- `COMMITTED` 之前，target 絕不暴露（partial 不可被 downstream queue 看見；鏡 F12「完整封存目錄才暴露至 Processing Queue」）。
- 任何 re-hash 不合 → `BLOCKED`，狀態機卡死在 fail-closed，人工處置前不可再 commit。
- receipt 是 append-only：同 job 重入若 receipt 已存在且與 manifest 相符 → 冪等 no-op；不符 → `BLOCKED`（`StagingConflictError`）。
- 獨立備份判定**只信 provider 的 device 指紋**（P07.1 `DeviceIdentityProvider`），不信呼叫者字串。

## 3. 可實作界面（`src/mnemosyne_dit/staging.py`）

- `StagedArchive(job_id, staging_dir, target_dir)`
  - `stage(files: dict[rel_path, bytes])` → 寫 staging（含 partial 容錯）
  - `verify_manifest()` → 全數 re-hash，產出 manifest（rel→sha256）
  - `commit(provider=None)` → 原子 `os.replace(staging→target)`＋寫 receipt（manifest＋commit 時間＋domains）；冪等
  - `recovery_state()` → `CLEAN/INTERRUPTED/COMMITTED/BLOCKED`
  - `resume(provider=None)` → re-hash＋commit；任一不符 → `BLOCKED`
  - `discard()` → 移除 staging，狀態回 `CLEAN`
  - `independence_report(provider)` → `{domains: [...], independent_backup_count: n, mirror_note: "availability, not backup"}`（同 device_id 折疊；非物理不計）
- `StagingConflictError`：receipt 與 manifest 衝突（篡改路徑，鏡 P05.1 S5）

## 4. 測試分層（P07.1 markers）

- `@behavior_tested`：實調 `StagedArchive` 並斷言狀態機結果（happy、crash-resume、tamper-blocked、冪等、mirror 折疊、NAS 同 appliance、receipt 篡改）
- `@hw_blocked`：真 NAS/ZFS/SMB/斷電——只建 scenario 狀態＋contract assert，不填實品結果
- `@fixture_only`：只驗 journal/receipt 檔案結構建立

**驗收**：崩潰重放（mock kill）與 restore（synthetic 完整目錄可被重讀）有現物證據；false-safe（partial 被暴露為 COMMITTED）零容忍。
