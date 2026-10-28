# Windows CPU Pilot — A770 工作站部署包規格（P12.2-RC，2026-10-28）

狀態：SPEC 完成（本輪）；**實際部署 = 未授權**（需：A770 工作站可用＋顯卡驅動狀態確認＋磁碟配置許可）。

## 1. 目標與明確不做的事
- 做：A770 工作站上跑 **CPU-only** Proxy 管線（`ffmpeg -hwaccel` 全數關閉），
  含 Crash Recovery 冒煙、SourcePin 三刻點、capacity gate、retry budget 的
  **實機行為驗證**（本地 330 測試只能證明「不崩」，不能證明「Windows 上
  UNC/rename/NTFS 語意正確」）。
- 不做：不裝 CUDA/GPU 管線（A770 硬體在 pilot 期間 **HARDWARE_BLOCKED**，
  只當 CPU host 用，不碰顯示卡軟體棧）；不動真實 SD/NAS；不自啟；
  不改正式磁碟資料；所有 pilot 產物落在**獨立 pilot 卷區**。

## 2. 部署包結構（單一 self-contained 資料夾，可整包移除＝rollback）
```
pilot-dit22-windows\
  run.ps1                  ← 唯一入口：census → 安裝 → 冒煙 → 出報告
  uninstall.ps1            ← 反向：刪 pilot 卷區、移除 service 註冊、還原 PATH
  census.ps1               ← 唯讀 Windows 普查（§5 表）
  requirements-win.txt     ← pip freeze 生成＋版本鎖定（§3）
  ffmpeg\, ffprobe\        ← 官方 Windows build（§4 capability check 驗證）
  src\, tests\             ← 從 repo 複製（untracked -encoders 絕不帶上）
  pilot-data\
    synthetic\             ← §6 安全測試資料（本輪生成、可重放）
    out\, receipts\, evidence\
  jobdb\                   ← §7 SQLite Job DB（pilot 專屬，非 v4 files.db）
  logs\
```

## 3. Python dependencies（A770 前置普查欄位）
- Python **3.10–3.12**（pyproject classifiers；測 3.12 鎖定）。
- 本輪 venv 版本基線（pip freeze 生成 `requirements-win.txt` 時鎖定）：
  `numpy 2.5.4`、`pillow 13.0.0`、`qdrant-client 1.20.0`（pilot 可選裝）、
  `pytest 9.1.1`、`ruff 0.17.2`。
- `av`（PyAV）：pilot 才裝，版本必須與本輪 venv 同 major（memory_guard 的
  O(chunk+1 frame) 契約綁定解碼器版本，跨 major 需重跑 §12 evidence 檔）。

## 4. FFmpeg/FFprobe capability check（run.ps1 step 2，fail-stop）
```
ffprobe -version          # 記 build 日期＋git rev 入 evidence
ffmpeg -hide_banner -formats | Select-String lavfi
ffmpeg -f lavfi -i testsrc2=duration=1:size=320x240:rate=29.97 -frames:v 30 -f null -
# 通過判準：三行全 exit 0；缺任一 → 停 pilot、回報缺件，不繼續
```
CPU-only 宣告：`-hwaccel none` 預設、不載入 cuda/vulkan filters（普查記
`ffmpeg -filters | findstr cuda` 結果作證據）。

## 5. Windows Census（唯讀，A770 上執行後回填本節表格）
| 欄位 | 值 | 來源 |
|---|---|---|
| CPU / 實體核 | ＿ | `Get-CimInstance Win32_Processor` |
| RAM 總量/可用 | ＿ | `Get-CimInstance Win32_ComputerSystem` |
| 磁碟卷別與容量（C:/D:/pilot 卷） | ＿ | `Get-PSDrive` |
| NTFS 8.3 短名稱啟用狀態 | ＿ | `fsutil 8dot3name`（卷別級） |
| NTFS oplock/重解析點（reparse point）掃描 | ＿ | `fsutil reparsepoint query`（pilot 卷） |
| UNC 分享路徑（若 pilot 含 NAS 端點；預設**不包含**） | ＿ | `net share` |
| 電源方案（pilot 期間防休眠） | ＿ | `powercfg /getactivescheme` |
| Windows 版本/Build | ＿ | `[Environment.OSVersion]` |
| A770 顯卡（僅記錄，pilot 不使用） | ＿ | `Get-CimInstance Win32_VideoController` |

回填前 pilot 不得開始；**UNC/SMB 行預填 `NOT_IN_SCOPE`**（維持
HARDWARE_BLOCKED，pilot 成功不代表 UNC 解禁）。

## 6. Safe test-data generator（可重放、零真實媒體）
- `ffmpeg -f lavfi -i testsrc2=duration=12:size=1280x720:rate=29.97` ＋
  `sine` 音軌 → 720p/29.97/12s `.mp4` 合成樣本×3（含一個**無音軌**樣本、
  一個**非整數 29.97 VFR 近似**樣本）；檔名刻意含 `_P12.2-pilot` 尾標，
  與任何真實素材不碰撞。
- 所有樣本 SHA256 生成即入 receipt 基線；每次重跑重新比對，漂移＝廢棄重造。

## 7. SQLite Job DB（pilot 專屬）
- 位置：`pilot-dit22-windows\jobdb\pilot_jobs.db`（**非** v4 files.db、
  非 Qdrant）；schema 走 `job_queue.create_tables` 全量遷移（P12.2-C3 兩列
  自動補）。pilot 結束＝整包移除，無殘留。

## 8. CPU-only integration runner（pilot 主序列，單線程、無 GPU）
1. admission（SourcePin 建 pin、`manifest_digest_of` 綁定）
2. `safe_artifact_name`（**P12.2-R 命名層正式接線點**：job_id＋generation
   tag＋source stem＋profile 全走 `windows_naming`，MAX_PATH 拒決活驗）
3. proxy generation（`capacity_gate` 以 pilot 卷實際 capacity_probe）
4. 中斷注入：編碼 50% 時 Ctrl-Break（zombie staging）→ 重啟 →
   `recover_staged` 全六例冒煙
5. `artifact_recovery` 判 PUBLISHED/UNPUBLISHABLE 實測
6. editor 回連：ffprobe 驗證 frame count/PTS/audio layout（P11.1-D 證據）
7. retry budget：人為造 3 次失敗，驗 `max_attempts` 精確在第 3 次 exhaustion
8. 低空間：pilot 卷塞到 15% 以下（用可清除的 filler 檔，pilot 結束即刪），
   驗 advisory flag＋capacity gate 新 job 拒決、**既不刪除 filler 也不刪除
   原片**（§storage policy 約束）。

## 9. Logs & diagnostic evidence（判定用）
- `logs\run-<UTC>.log`（逐 step 紀元時間戳）＋`evidence\probe-<seq>.json`
  （每 step 的 ffprobe/capacity/SHA 快照）＋`evidence\recovery-verdict.json`。
- 判定門檻：8 步全綠＋evidence 檔數＝step 數，缺一即 pilot 不通過、
  整包回退。

## 10. Rollback & uninstall
- `uninstall.ps1`：刪 pilot 卷區內容（僅 pilot 路徑白名單）→ 還原 PATH →
  移除 `pilot_jobs.db` → 存 uninstall 收據。**無開機自啟項可刪**
  （本輪不設 service/scheduled task，uninstall 只清資料）。
- pilot 期間任何 step fail-stop → run.ps1 不自動重試（retry budget 的
  實測是 step 7 的**受控**注入，非 pilot 自身的重試器）。

## 11. Pilot 準備度判定（本輪）
SPEC 完成、命名層（§3）TDD 落定（330 含 10 新負向測試）、
capacity/retry/recovery 三者的**實機行為面**在本輪測試裡已是
「不崩」級證據；「NTFS/UNC 語意正確」級證據仍 = A770 上跑 §8 才得。
準備度 **READY-FOR-AUTHORIZATION**（缺的唯一前置＝A770 工作站與授權）。
