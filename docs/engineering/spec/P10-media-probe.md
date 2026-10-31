# P10 — Media Probe（FFprobe 唯讀媒體探測，TDD 垂直切片）

**產出**：2026-10-24　**方法**：writing-plans 先定契約 → TDD → 獨立審查
**SSOT P10**：媒體 Metadata / Camera families：Reel/TC/FPS/VFR/color/rotate/sidecar；支持未知媒體。
**範圍**：純 stdlib＋`ffprobe -of json`（subprocess argv、無 shell）；**唯讀**——對輸入檔與 sidecar 一律 O_RDONLY 語意（ffprobe 本身不寫入），禁止修改原片。

## 1. 介面

`MediaProbe`（dataclass）＋ `probe(path, *, sidecar_dir=None, sha256=False, timeout_s=30.0, ffprobe_bin="ffprobe")`：

| 欄位 | 語意 |
|---|---|
| `format` / `duration_s` / `nb_streams` | 容器層（ffprobe format 節） |
| `video[]` | codec、width/height、`pix_fmt`、`r_frame_rate`（**精確 Rational**，保留「30000/1001」不約簡成 float）、`time_base`（`"1/24000"` 原文）、首尾 `pts`＋`pts_time`、`side_data` 含 `rotation` 時記錄 `rotation`、`color_primaries`／`color_transfer`／`color_space`、`hdr`（transfer 含 pq／log / primaries 含 bt2020 等 → `"sdr"｜"hdr-sdr"｜"unknown"`） |
| `audio[]` | codec、`sample_rate`、`channels`、`channel_layout`（多音軌全數列出） |
| `fps` | video 流主 `avg_frame_rate` 的 Rational；無法判斷 → `None`＋`fps_status="unknown"`（降級不假設） |
| `vfr_status` | `"cfr"｜"vfr-likely"｜"unknown"`：有逐幀 PTS 時比對差值，**任一正 delta 偏離中位差 >5% → `vfr-likely`**；<3 幀或資訊不足 → `unknown` 降級，**絕不標 cfr** |
| `timecode` | 依 `start_time`＋fps 家系推導：drop-frame  capable（29.97/30 家族）→ `"drop"`；24/25/48/50/60 → `"non-drop"`；fps unknown → `None`＋`timecode_basis="unresolved"` |
| `camera_family` | 由 format tag／codec／檔名模式分類：`"sony-unknown"`（braw/x-ocn 等無樣本）、`"generic-mxf"`、`"prores"`、`` ；**無樣本 family 一律 `verified=False`** |
| `sidecars` | 掃描 `sidecar_dir`（預設同目錄，唯讀列目錄）：副檔名 mxf sidecar / csv / m3u8 / srt / sidecar JSON；只記錄相對路徑＋sha256（請求時） |
| `source_sha256` | 請求時流式計算（8KB 塊）；否則 `None` |
| `ffprobe_version` | 執行時 `ffprobe -version` 取首行；**證據可重建**＝`to_evidence_json()` 內含 binary 版本、argv、輸入檔 sha256（如已算）、原始 ffprobe JSON（截斷前完整） |

**HDR 判定（保守，erratum）**：`hdr-sdr` 只在 transfer 屬 PQ/HLG 家族（smpte2084 / arib-std-b67 系列）；`sdr` 需 transfer **與** primaries 同屬 SDR 家族；其餘一律 `unknown`。不依「primaries 含 bt2020」單獨判 HDR（build 差異太大，保守降級）。

## 2. 安全契約

1. **argv 安全**：`subprocess.run([ffprobe_bin, -hide_banner, -loglevel, error, -of, json, ...path])`，`shell=False`；輸入路徑不經 shell 解析。
2. **URL 拒絕**：路徑含 scheme（`://`）或開頭 `http`/`https`/`ftp`/`data:` → `InvalidInputError`，**不執行** ffprobe（絕不隱式開啟網路 URL）。
3. **Timeout**：`timeout_s` 超過 → `ProbeTimeout`（回傳已收部分不充當結果）。
4. **輸出限制**：JSON 回應 > 50MB → `ProbeError("output limit exceeded")`（防畸形容器灌爆）。
5. **損壞／空／未知格式**：ffprobe exit≠0 或 stdout 非 JSON → `ProbeError` 含 stderr 摘要（截斷 2KB）；**空檔案**（size=0）→ 直接 `ProbeError("empty input")`（連 ffprobe 都不呼叫）。
6. **Unicode 路徑**：以 `str(Path)` 传入 argv（subprocess 處理 OS 編碼），測試以 CJK 檔名實測。
7. **唯讀**：module 不開啟寫入句柄；`sha256` 只 `open(rb)`；sidecar 掃描只 `os.scandir`＋stat。
8. **不碰 v4**：無 `files.db`／qdrant／indexer import（P09 同款隔離審查條款）。

## 3. 測試分層（synthetic fixtures，零真實素材）

fixture 一律 `ffmpeg` 生成於 `tmp_path`（synthetic、可重現、`@behavior_tested`）；純 JSON 解析路徑用固定 blob（`@fixture_only`）。

| # | 測試 | 斷言 |
|---|---|---|
| 1 | 24p 合成 MP4 | `r_frame_rate=="24/1"`、`time_base=="1/24"` 或 `"1/24000"`、codec `h264`、`fps` Rational、`vfr_status="cfr"`（逐幀 PTS 等距） |
| 2 | 29.97p（`-r 30000/1001`） | `r_frame_rate=="30000/1001"` 精確字串保留；`timecode` 家系=`"drop"`（drop-frame capable）；`duration_s` 與 nb_frames/fps 一致（容差 2 幀） |
| 3 | VFR 合成（兩段不同速率接起來） | 逐幀 PTS 差值非等距 → `vfr_status="vfr-likely"`（不假設 cfr） |
| 4 | HDR/rotated：`-metadata:s:v:0 rotation=90`＋bt2020/transfer smpte2084 生成 | `rotation==90.0`；`hdr` 依 transfer 判 `hdr-sdr`/`unknown`（合成器不真出 PQ 時 → `unknown` 降級，絕不猜） |
| 5 | 雙音軌（aac＋opus 各一條） | `audio` 長度 2、`sample_rate`／`channel_layout` 各軌獨立 |
| 6 | 損壞檔案（半截 MP4）／空檔案 | `ProbeError`／`empty input`；ffprobe 不被呼叫（空檔） |
| 7 | 未知格式（.foo＝隨機 bytes） | `ProbeError` 含 stderr 摘要；`camera_family` 路徑不爆炸 |
| 8 | CJK Unicode 路徑 | probe 成功、欄位正確 |
| 9 | URL 輸入（`http://x`） | `InvalidInputError` 在 subprocess 之前（用 spy 斷言 ffprobe 未執行） |
| 10 | sidecar 關聯：同目錄放 `<base>.sidecar.json`＋`.csv` | `sidecars` 列兩項相對路徑；source_sha256 可重算比對 |
| 11 | 證據可重建：`to_evidence_json()` | 含 `ffprobe_version`、argv、原始 JSON；同 blob 重放 `from_evidence` 還原同欄位 |
| 12 | Sony BRAW / X-OCN / CinemaDNG family | **無樣本**：`camera_family` 分類器回 `verified=False` 標 `UNVERIFIED`（contract 測試 `@fixture_only`，不偽稱實測） |
| 13 | 未知 JSON（ffprobe 回非 JSON stdout 的 mock） | `@fixture_only`：parser 層 `ProbeError("malformed json")` |

**驗收**：13 類全落；synthetic 全 `@behavior_tested`；真 camera family 標 UNVERIFIED；全量回歸無 regress；v4/雲端/真實素材零接觸。P11 proxy 生成以本模組輸出為輸入契約（PTS/TC/Reel mapping 保留）。
