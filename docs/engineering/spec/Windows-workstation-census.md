# Windows Workstation Census — 唯讀盤點規格（A770 部署準備度）

**產出**：2026-10-27　**狀態**：SPEC／PLAN — **未於 A770 工作站執行任何收集**（工作站未連線；本輪僅定義規格）
**目標機器**：Ryzen 7 5800X / 48GB / Intel Arc A770 16GB / Windows（v4 master plan 的重推理工作站）
**邊界**：本階段**只讀**。不安裝／卸載／搬移／刪除任何軟體與資料。所有實機結果在首輪收集前一律 `HARDWARE_BLOCKED`／未執行，不填假數據。

## 0. 資料庫擁有權（先決）

- 本機（macOS 工作區）**未找到** Workstation-Census-Migration repo（`~` 與 `~/Desktop/dit22-workspace/` 皆無 census/workstation 目錄）。
- **規則**：收集前先確認 GitHub `juhjuhx` org 是否已有 census/workstation repo（用戶核准查詢）。**若存在 → 讀其 ADR 與資料庫擁有權規定後沿用**；若不存在 → 建立**獨立** repo／DB（`workstation-census`），與 DIT 2.2 的 `dit22` namespace、v4 `files.db`、Qdrant 全部分離；**不重建既有 DB、不複製另一份機器真相**。
- Census 資料結構＝append-only 觀測記錄（每次盤點一個 snapshot JSON＋delta），機器「真相」只在該 repo 一處。

## 1. 收集範圍（唯讀，PowerShell／CLI，全部 `-NoProfile`、不觸發執行）

| 群組 | 收集項 | 工具（唯讀） |
|------|--------|-------------|
| OS | Windows 版本／Build、Edition、UEFI/BIOS 啟動模式、虛擬化狀態 | `Get-ComputerInfo` |
| CPU/韞存 | 型號（預設 5800X，實測確認）、SMT、總 RAM（預設 48GB）、NUMA 節 | `Get-ComputerInfo`、`wmic cpu get /format:list` |
| GPU | Intel Arc A770 裝置存在、**顯示卡驅動版本**、显存 16GB、顯示輸出 | `Get-CimInstance Win32_VideoController`、`wmic path win32_videodevice get DriverVersion`、`dxdiag`（唯讀 txt 導出） |
| A770 能力 | QSV 編碼器／解碼器（ffmpeg `-encoders` 中 `qsv.*`）、OpenVINO 是否安裝與版本、Vulkan ICD（Intel）、oneVPL/ffmpeg QSV 可用性 | `ffmpeg -hide_banner -encoders`、`ffmpeg -init_hw_device qsv`（dry，不落檔）、`vulkaninfo --summary`、`opencl` runtime 偵測（`sycl-ls` 若存在） |
| 軟體位置 | Python（版本／多版本）、FFmpeg/FFprobe（版本／建置／QSV 代碼）、MediaInfo、Scoop（`F:\Apps\Scoop` 確認）、WinGet、UniGetUI、Hermes（預設 `F:\Hermes`）實際位置與版本 | `Get-Command`、`where.exe`、各工具 `--version` |
| 磁碟 | C/D/E/F 容量（Total/Free/AllocUnitSize）、**檔案系統擁有者**（NTFS ReFS 判定）、NTFS 壓縮狀態、卷標、S.M.A.R.T. 基本健康（`Get-PhysicalDisk`） | `Get-Volume`、`Get-Disk`、`Get-PhysicalDisk`、`fsutil volume diskfree` |
| 安裝位置異動 | 應用程式寫入 C: 的量、%LOCALAPPDATA%／%PROGRAMDATA% 大目錄（前 50 名）、暫存目錄（%TEMP%、Prefetch、CrashDumps）大小與可重建性 | `Get-ChildItem -Recurse` 量測（唯讀、不修改）、`Get-CimInstance Win32_Service` 落盤路徑 |
| 外接 | 外接 HDD 掛載點與健康、讀卡器（USB 介面卡列示）、SMB Share 目前連線、NAS 實體（IP/型號/provider 指紋） | `Get-WmiObject Win32_DiskDrive`、`Get-SmbConnection`、`Get-SmbMapping` |
| 檔案擁有者／權限 | 素材目錄 ACL 基本狀態（誰擁有、是否有未繼承項） | `Get-Acl` 摘要（不修改） |

**每組產出＝JSON 行**（timestamp＋raw 值＋collect command），匯入 census repo 的 `snapshots/YYYYMMDD-HHMM.json`；不修改被觀測目標。

## 2. 四份產出模板（首輪收集後填，現況全為佔位）

### 2.1 `WORKSTATION_CENSUS_REPORT.md`
- §1 OS/硬體（含「與預設 5800X/48GB/A770 的差異」列）
- §2 軟體位置對照表（預期 `F:\Apps\Scoop`、`F:\Hermes` vs 實測）
- §3 磁碟壓力表（C/D/E/F 使用率 top10 佔用來源、可重建/不可重建分類）
- §4 外接裝置與 NAS 實體身分（device-identity provider 輸入：vendor/serial/size/mount 指紋）
- §5 異常安裝與快寫寫入來源清單（附「搬移目標建議」，**不執行**）

### 2.2 `DISK_PRESSURE_POLICY.md`
- 政策：低空間（C: 或 D: <15% 自由）→ **先停新 Proxy/Embedding 工作**（接 Hermes TUI 的 AI Jobs 暫停訊號），**絕不**自動刪原片／重要備份／音樂／不可重建資料
- 可重建快取標記：每個搬移目標用 `REBUILDABLE-OK` sidecar（內含重建指令與驗證方式）；未標記＝不可動
- 搬移順序：暫存/快取 → 可重裝應用 → 模型權重（留本地鏡像路徑）；Registry/AppData/ProgramData/系統共用**不遷移**（Windows 系統管理域，依 §7）
- 所有清理先出 Proposal＋依賴分析＋復原證據（快照 diff），再申請執行授權

### 2.3 `PACKAGE_INVENTORY.json`
- 每個套件：name/version/source(winget|scoop|manual|uni)/location/rebuildable(bool+cmd)/license/last-seen；**與 DIT 素材 catalog 分開維護**（本 JSON ≠ dit22.db）
- 授權風險欄（open-source 選型用，§10 報告引用）

### 2.4 `A770_CAPABILITY_MATRIX.md`
- 矩陣維度：`qsv_encode / qsv_decode / openvino_runtime / vulkan_icd / sycl` × `{supported, driver_version_required, measured(待實測), fallback(CPU)}`
- **現況全列 `measured=HARDWARE_BLOCKED`**（未連線）；填入條件＝工作站可用時實機跑 §3 的三個 baseline 並附原始輸出
- CPU fallback 必達標項（不依賴 GPU 也可跑）：P10 probe、P11 proxy（h264/browser＋editor 依 encoder 能力）、P12 ContentDiff

## 3. GPU 三工作流（§6 對應；收集後建，A770 實測前全 BLOCKED）

- **A. CPU FFmpeg baseline**：P11 browser/editor proxy 端到端（本 macOS 已證明管線邏輯；Windows 重測＝新證據，非引用）
- **B. Intel Arc QSV encode/decode baseline**：`qsv` 硬體的 h264/hevc encode＋decode 可用性與吞吐（首測只記「可用/不可用＋版本＋一次代表性編碼時長」，**不填 Benchmark 排行榜數字**）
- **C. OpenVINO CLIP/SigLIP inference baseline**：模型可載入、batch=1 可推理、輸出維度正確（text_vec 768 / image_vec 512 的 named-vector 不變量**不在此處改動**——只是驗證推理端能產出）
- WeMM／Qwen3-VL：保留後續 Provider PoC；**無設備證據前不宣稱支援、不填 Benchmark**（§6 明令）

## 4. Storage/Offload 整合（§4 對應；引擎以 P06 稽核結果為準）

- 引擎 pin（P06 已實測）：ProofCat `29c06a2517`（MIT，Rust/offload-core，131 passed）、offloader `e01a0eb034`（MIT，Python，306 passed/13 skipped Windows-only）
- 整合契約（Windows 端）：串流複製（chunk-hash、不整片入記憶體）、來源唯讀、**兩個真正獨立故障域**（RAID1 或雙 SMB Share 同一 appliance **不計兩份備份**——判定只信 P07.1 `DeviceIdentityProvider` 的 device 指紋，P08 `independence_report` 語意）、全量 checksum＋**目的端 read-back**、NAS/SMB 斷線恢復（P08 INTERRUPTED→resume，任一 hash 不合＝BLOCKED 不暴露 partial）、staging atomic commit、append-only receipt
- **無真實 NAS/設備 → 全部 HARDWARE_BLOCKED**；不對生產 NAS 做中斷/格式化/刪檔/故障注入（明令禁止）
- rclone/Kopia：僅做 Windows 整合方式研究（認證／排程／log 位置），**不執行**

## 5. P13 語義分割（介面規格輪廓，完整 spec 下一輪；現僅此三行定義）

- 三分法升級：`Fixed Window`（工具，無 confidence）／`Shot Boundary`（P12 已產，`content_cut`／`neural_sbd`）／`Semantic Event Boundary`（P13 主體；segment 帶 event label＋model version＋confidence）
- Segment schema 必帶：`source_asset_id`、來源 frame/PTS/time_base、**原始 shot_id（P12 segment 對應）**、model 版本、事件標籤、confidence；**不捏造人工 ground truth／Precision／Recall／F1**
- P12 未 commit → P13 介面以 P12 `SceneSegment` 為輸入契約**只寫 spec，不寫碼**（§5 授權邊界）

## 6. 執行顺序與核准門

1. 用戶核准：查詢 GitHub org 是否已有 census repo（唯讀）→ 決定 DB 擁有權
2. 工作站首輪收集（用戶於該機執行 §1 唯讀腳本）→ 填 §2 四份產出（首次填實值時逐份独立 commit 於 census 側 repo，非本 repo）
3. §3 三工作流建檔（全 BLOCKED 佔位）→ 工作站可用時實測填值
4. 本 repo 內**不落**A770 實測數據（保持 DIT 2.2 切片純 CPU 證據鏈）；A770 證據只進 census repo

## 7. Hermes TUI / 包管理（§7/§8 對應，本輪不實作）

- 只提最小 TUI 設計檔（下一輪）：7 畫面（Overview/DIT Ingest/Storage/Packages/AI Jobs/Evidence/Approvals），danger action 一律 `read-only → plan → approve → execute`；低空間優先停 Proxy/Embedding、不自動刪不可重建資料
- 包管理：Scoop 優 `F:\Apps\Scoop`、Hermes 主根 `F:\Hermes`；可移動 Python/Node/Model/暫存依套件支援程度設定；可重建快取＝`REBUILDABLE-OK` sidecar；**Registry/AppData/ProgramData/系統共用不遷移**；UniGetUI 原生 TUI 優先，不重開發安裝前端
- 所有檔案清理＝Proposal＋依賴＋復原證據→申請授權（不先斬後奏）
