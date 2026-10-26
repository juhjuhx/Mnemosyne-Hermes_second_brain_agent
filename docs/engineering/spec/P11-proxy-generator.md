# P11 — Proxy Generator（CPU FFmpeg 最小可播放 MVP，TDD 垂直切片）

**產出**：2026-10-24　**方法**：writing-plans 先定契約 → TDD → 獨立審查
**前置**：P10 驗收後開始（本 spec 以 `media_probe.probe()` 為來源對應輸入；P10 未 commit 前本切片不 commit）。
**範圍**：純 stdlib＋`ffmpeg`（subprocess argv、無 shell、CPU 編碼）；最小可播放 golden fixture（`synthetic` 來源，零真實素材）。**不碰原始素材、不啟用 QSV/Vulkan/OpenVINO（留後段）**。

## 1. 目標產出（依使用者合約）

| profile | 編碼 | 容器 | 用途 | 本機 CPU 可行性 |
|---|---|---|---|---|
| `browser` | **H.264** (`libx264` / `h264`) yuv420p 720p cap | **MP4** | 瀏覽器預覽 | ✅ 已驗證可用 |
| `editor` | **DNxHR LB** / **ProRes Proxy** | DNxHR→MXF；ProRes→MOV | NLE 低頻編輯 | ProRes 需 `libx264`? 否＝`prores`/`dnxhr` 编码器依 build 而定；**無 encoder 時 fail-closed 降級 h264 並標 `degraded=True`** |

> editor 目標依**平台實際編碼能力**決定：build 偵測 `ffmpeg -encoders`；缺 `libprores`/`dnxhr` → 誠實降級（不硬編）。

## 2. 介面

`generate_proxy(source, profile, out_dir, *, source_probe=None, job_id=None, lease_token=None, ffmpeg_bin="ffmpeg", timeout_s=..., fps_cap=None) -> ProxyResult`

| 欄位 | 語意 |
|---|---|
| `path` | 發布後 proxy 檔（out_dir 內） |
| `profile` / `codec` / `container` | 實際編碼（含降級後真值） |
| `degraded` | 是否自 editor 目標降級到 h264（真值，供上層告知） |
| `source` | 來源路徑（**唯讀**，本模組絕不開啟寫入） |
| `source_sha256` | 來源對應（取自 P10 probe，若 `source_probe` 提供） |
| `source_fps` / `source_timecode` / `source_reel` / `audio_mapping` | 保存來源對應的 PTS、Timecode、Reel、Audio Mapping（從 `source_probe` 抄寫，不重算） |
| `proxy_sha256` | 產物指紋（可重建驗證） |
| `receipt` | **atomic publish 證據**：`{job_id, lease_token, source_sha256, proxy_sha256, ffmpeg_version, argv, status}` |
| `size_bytes` / `duration_s` | 產物元數據（ffprobe 回讀，不信任編碼器自我報告） |

## 3. 管線：staging → verify → atomic publish（沿用 P08 receipt shape）

1. **Staging**：先寫 `out_dir/.staging/<job_id>/<stem>__<profile>.<ext>`（隱藏暫存目錄）。外部副作用 fencing（P09.1 spec §4.3）：暫存檔名含 `job_id`；若 `lease_token` 提供，`receipt` 記下它——被竊 lease 的寫入者產物可偵測、可清除，**絕不直接寫入正式 out_dir**。
2. **Verify**：產物回讀——(a) 檔存在且非空；(b) ffprobe 可解析；(c) `duration_s` 與來源容差內一致；(d) 音軌數與 `audio_mapping` 匹配。**缺任一 → 刪暫存、丟 `ProxyVerifyError`（fail-closed）**。
3. **Atomic publish**：verify 全過後，**先寫 `receipt.json`（含全部欄位），再 `os.replace()` 暫存檔 → 正式檔**（同目錄原子改名）。缺 receipt＝非 committed（P08 同語意）；正式目錄只出現 verify 過的檔案。
4. **可刪除可重建**：`delete_proxies(out_dir)` 依 `job_id` 或全清 `out_dir`；重建＝重跑 `generate_proxy`，**不触碰來源**。
5. **絕不自動提高 DIT Archive Safety Verdict**：本模組只產 proxy；完成不觸發任何 archive verdict 上升（由上層依 P08 獨性報告決定）。

## 4. 安全契約

1. **不修改原片**：`ffmpeg` 來源以 `-i source` 唯讀輸入；輸出必落 staging 隱藏目錄。對來源 zero write-handle（靜態 grep 可證）。
2. **不隱式 URL**：沿用 P10 的 URL 拒絕（來源是 URL → 拒絕；不傳 `ffmpeg` 任何遠端路徑）。
3. **subprocess 安全**：`ffmpeg_bin` argv list、`shell=False`、`timeout_s`、退出碼≠0 → `ProxyEncodeError`（含 stderr 摘要截斷 2KB）。
4. **encoder 降級 fail-closed**：editor 目標缺 encoder → 不靜默成功，回 `degraded=True`＋實際 codec（誠實降級，絕不偽稱 ProRes）。
5. **v4 隔離**：零 `files.db`／qdrant／indexer import（P09/P10 同款條款）。

## 5. 測試分層（synthetic golden fixture，`@behavior_tested` 為主）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | browser golden：synthetic 24p 320×240 lavfi → H.264 MP4 720p-cap（源已 <720 不放大） | 產物 ffprobe `codec==h264`、`pix_fmt==yuv420p`、`duration_s` 與源容差 0.2s 內；**正式目錄出現 + receipt 存在** |
| 2 | 來源對應保存：傳入 P10 `probe`（含 fps/TC/reel/audio） | `source_fps`/`source_timecode`/`audio_mapping` 抄到 receipt，**未重算** |
| 3 | verify 失敗（人工損壞暫存：截斷產物） | `ProxyVerifyError`；正式目錄**無**該檔；暫存被清 |
| 4 | receipt fencing：同 `job_id` 兩次、不同 `lease_token` | 第 2 次正式檔 receipt 只屬**當前** token；舊 token 產物可偵測可清除（`stale_proxy_detection`） |
| 5 | 可刪除可重建：`delete_proxies` 後重跑 | 源 sha256 不變、重建後 sha256 可重現 |
| 6 | **原片 untouched**：`source_sha256` 全程相等（前後比對） | 來源檔零寫入（hash 相等） |
| 7 | editor 降級：本機 build 缺 ProRes/DNxHR encoder | `degraded=True`＋實際 `codec`（誠實），**不偽稱** ProRes；有 encoder 時走真 DNxHR/ProRes（本機大概率走降級路徑，實測為準） |
| 8 | URL 來源 | 拒絕（不傳 ffmpeg 遠端路徑） |
| 9 | 損壞/空來源 | `ProxyEncodeError`／empty 拒絕；ffmpeg 不產垃圾正式檔 |
| 10 | 不升 verdict：完成後呼叫上層 hook | proxy 完成**不**改任何 archive safety 狀態（以 fake verdict fn 斷言未被調用） |

**驗收**：10 類落；browser golden 真編真回讀（`@behavior_tested`）；editor 依 build 實測（有 encoder 走真值、缺则誠實降級，兩者都斷言不偽稱）；原片 untouched；可刪除可重建；不升 verdict；v4/雲端/真實素材零接觸。

## 6. 不在本切片（留後段）

- Intel Arc QSV、Vulkan、OpenVINO 加速（依合約「先 CPU 跑通 golden 再考慮」）。
- 多 worker 並行 proxy（ADR-DIT2-003 仍 PROPOSED，不動部署權限）。
- 切鏡（P12）、語義分割（P13）。
