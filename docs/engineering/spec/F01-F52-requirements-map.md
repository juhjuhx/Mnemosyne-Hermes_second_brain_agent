# F01–F52 Requirements Map｜Mnemosyne DIT 2.2（P03）

> 建立：2026-10-24（Asia/Taipei）｜分支 `research/dit22-multimodal-handoff-20261024` @ `bbd6ff7`
> 基礎：SSOT §3/§4 功能領域表 + 附錄 A §4（F01–F52 完整保留）。本 map 把 52 項需求對照
> **本 repo 實際現況**（非文檔理想），標記 `repo_now`（現有程式覆蓋狀態）與
> `test_spec`（該項驗收前必寫的測試）。狀態詞：`NEW / NAIVE / PARTIAL / DONE / GAP`。
>
> **現況摘要**（grounded in source, 非推論）：
> - 既有 naieve MCP：`src/hermes_skills/dit-offload/`（多目的拷貝+MD5）、`dit-metadata/`（ffprobe 相機偵測）。
>   二者缺：source 只讀 guard（F09）、獨立裝置判別（F06）、ASC MHL（F08）、fail-closed 狀態機（F11）、
>   同名衝突「改名」而非「拒絕」（F10 語義錯誤）——P04/P07 須硬化的正是這些。
> - 既有 `src/scripts/indexer.py`：v4 單 worker、`text_vec(768)+image_vec(512)`、`suggested_move` 不搬檔案
>   （invariant 2/3/4 由測試 `test_index_pipeline.py` 鎖定）。DIT 2.2 一律**新增** collection/queue，不碰此檔。
> - 既有 fixture：`tests/fixtures/dit22/generate_fixtures.py`（deterministic synthetic card tree，含 zero-byte / 萬國碼名）。
>
> 優先度：P0=安全關鍵/最低可用；P1=完整工作流；P2=進階；O=可選。

---

## A. Safe Offload（P0，安全閉環核心）

> 領域首要候選：ProofCat（Rust）+ offloader（Python）並列 + ASC MHL 交叉驗證（見 P02 ledger R06/R08/R10/R11）。

| ID | 需求 | 候選 | 關鍵欄位/指標 | repo_now | test_spec（驗收前必寫） |
|---|---|---|---|---|---|
| F01 | Source Discovery（SD/CF/SSD/SMB/NFS/S3 的 volume UID/mount/fs/card signature） | 自研 + ProofCat | `source_id, mount, fs, card_sig, device_id` | **GAP**（無 discovery） | fixture 假 volume，assert 偵測出 device_id 且 SMB 離線時 fail-closed |
| F02 | 卡目錄保真（DCIM/PRIVATE/sidecars 完整遞迴；symlink/特殊檔政策） | offloader | 遞迴樹完整、symlink 明確政策 | **NAIVE**（`discover_media` 只取 CAMERA_EXTENSIONS，漏 sidecar 非媒體型） | 遞迴深度+symlink loop+隱藏檔；assert 不漏 DCIM 側檔 |
| F03 | 資料集身分（Mnemosyne 新 Asset ID：`source_id/asset_id/reel/card/path_observation`，分層 hash） | 自研 canonical ID（P05） | `asset_id=sha256(content)` 與 path 解耦 | **GAP**（naive 用 path.name 判別） | 同檔搬不同 path → 同 asset_id；異 content 同 basename → 異 asset_id |
| F04 | 多目的地複製（來源只讀、A/B 目標獨立、寫 staging、不覆蓋已驗證檔） | ProofCat/offloader | staging、atomic commit、不覆 good | **GAP**（naive 直接 `shutil.copy2` 無 staging/不覆 guard） | 寫入 `.staging/<job>`+rename；已驗證檔重跑不改寫 |
| F05 | 讀回驗證（source+dest 每檔重算 `full`，含零長檔、變動來源警示） | offloader `--verify full` | full readback、0B 案、源改動警報 | **NAIVE**（MD5 一次算，無 source 改動偵測） | 源端 tamper 後重跑 → 警報；0B 檔 verified=true |
| F06 | 真實儲存裝置身分（不把兩 NAS share 當兩實體副本；未知設備不得 SAFE_TO_REUSE） | 自研 device fingerprint | `device_fingerprint, failure_domain` 判別 | **GAP**（無裝置身分判別） | 兩 share 同 device → 視為同故障域；unknown → `BLOCKED`（不得 GREEN） |
| F07 | Hash Ledger（`algorithm/hash/mtime/size/path/generation/device_id/verdict`） | 自研 + ASC MHL | 版本化、append-only ledger | **GAP** | ledger 重放幂等、generation 遞增、mismatch 標警報 |
| F08 | ASC MHL v2 互通（官方工具可讀/比對/產生 chain；維持來源原始樹） | ascmitc/mhl | MHL chain-of-custody、相對路徑 | **GAP**（naive 無 MHL） | 產生 MHL → 外部 `ascmitc/mhl` `diff/flatten` 可讀；chain tamper 偵測 |
| F09 | 原片不可變（source fs 不寫/不重命名/不刪；derived 存另一區） | Mnemosyne invariant | source read-only、derived 分離 | **NAIVE**（naive `copy2` 未 guard source 側；且 collision 改名動到 dest 結構） | dest-in-source、symlink/`..`、同名重名 → 拒絕；source hash 前後不變 |
| F10 | 續傳與冪等（kill/拔線/重插/同名重跑不破壞既有 good replica） | offloader/ProofCat | 冪等重入、不重毀 good 副本 | **GAP**（naive collision = 改新名 `stem_0001`，等同複製污染，非冪等） | 已驗證後再跑 → 不新增 `stem_0001`；kill -9 中繼 → resume 重入成功 |
| F11 | 安全狀態機（verified ≠ backed_up ≠ safe_to_reuse；缺任何 gate fail-closed） | ProofCat 狀態機 | 狀態節點互斥、fail-closed | **GAP** | 任一 gate 缺 → 不得達 `CARD_REUSE_ELIGIBLE`；false-safe=0（P0 FAIL 條件） |

## B. NAS Archive & Backup（P0）

| ID | 需求 | 候選 | repo_now | test_spec |
|---|---|---|---|---|
| F12 | NAS 擷取提交（staging→hash→commit；完整封存目錄才進 Processing Queue） | 自研 adapter | **GAP** | 封存目錄不完整 → 不入 queue；完整 commit → 入 queue |
| F13 | Mirror/RAID 提示（偵測實體獨立備份與快照；RAID1 ≠ 兩份備份） | TrueNAS | **GAP** | 同系統 mirror → 標「同故障域」；不得計為獨立 backup |
| F14 | 獨立備份（分設備/分身份/版本化/離線異地/restore 演練） | rclone/ZFS | **GAP** | restore drill 回讀 hash 相符；RPO/RTO 記錄 |
| F15 | Integrity 再驗證（定期抽樣/季度全量/mismatch 警報） | ASC MHL | **GAP** | 抽樣 re-hash；新增 mismatch → 警報 |

## C. Media Metadata & Derivatives（P1，部分 NAIVE）

| ID | 需求 | 候選 | repo_now | test_spec |
|---|---|---|---|---|
| F21 | 拍攝 Metadata（FPS rational/TC/reel/lens/ISO/shutter/WB/GPS，缺項 null） | ffprobe/ExifTool | **PARTIAL**（`dit-metadata` 有 ffprobe codec/res/fps(可 eval rational)；無 TC/reel/start-TC） | VFR + drop-frame fixture → fps rational 正確；缺項 null 不 crash |
| F22 | Sidecar 合併（Sony XML/ARRI/RED/BRAW/DJI/360/iPhone Live；不改原檔） | 自研 | **GAP** | sidecar 併入 metadata；原檔 checksum 不變 |
| F23 | Proxy Pipeline（來源清單/編碼/container/TC/FPS/audio/色彩/Relink manifest） | FFmpeg | **GAP**（ffmpeg 已裝 `/opt/homebrew/bin/ffmpeg`，無 proxy 邏輯） | NLE relink manifest 首末格對得上；只讀 verified 源 |
| F24 | 剪輯 Proxy 預設（DNxHR LB / ProRes Proxy 依平台授權；feature probe） | FFmpeg | **GAP** | 編碼器 feature probe；無授權 codec → 明標 BLOCKED 不硬跑 |
| F25 | Web 預覽代理（H.264 MP4，可調分辨率/碼率/seek） | FFmpeg | **GAP** | 產生 web proxy；browser seek 驗收 |
| F26 | 色彩/LUT 流程（Proxy display LUT；Log/RAW 不 baked 到原片） | Silverstack 借鑑 | **GAP** | LUT 只套 proxy，原檔 checksum 不變 |
| F27 | Contact Sheet/縮圖（4-keyframe、exif orientation、可追溯 source TC） | offloader/FFmpeg | **GAP** | 縮圖 source TC 對得上；exif 旋轉正確 |

## D. Segmentation & AI（P1）

| ID | 需求 | 候選 | repo_now | test_spec |
|---|---|---|---|---|
| F28 | AI ASR/VAD（中文+混語、timecode segments、SRT/VTT） | whisper family | **GAP** | 語音 span 回 source TC；VAD speech/no-speech 區分 |
| F29 | Shot/Scene boundary（PySceneDetect cut list；長鏡頭 segment 設計預設） | PySceneDetect v0.7.2 | **GAP** | cut Precision/Recall 對人工 GT；長 take 不定長段≠標準 |
| F30 | 視覺標籤（JSON object/action/location/movement/composition/lighting + 置信度） | VLM provider | **GAP** | 標籤 schema + 置信度；不涉生物特徵（invariant 5） |
| F31 | 多模態索引（SQLite FTS5 + Qdrant；中文斷詞/BM25/model 版本命名） | 自研 + Qdrant | **PARTIAL**（v4 `in_memory_qdrant` 有 text_vec；無 FTS5 中文斷詞/新 collection） | 新 collection 不碰 v4；BM25 中文檢索 recall；重索引可重建 |
| F32 | 自然語言找鏡頭（query→clip/source TC/preview/evidence） | Hermes/Mnemosyne | **GAP** | Recall@K + false-positive 驗收；結果回 source TC |
| F33 | GOOD/NG/REVIEW（AI 可建議，正式 flag 需人工批准） | arkiv 行為研究（黑箱） | **GAP** | 人工 flag 不被 AI 重跑覆蓋；review history 存 |
| F34 | 標籤編輯與版本（人工標籤不可被重跑覆蓋；reviewer/reason/history） | MAM 自研 | **GAP** | AI 重跑 → 人工 tag 保留；衝突顯示 |
| F35 | 專案/拍攝日/機位（Project/ShootDay/Card/Reel/Clip/Segment 階層） | Silverstack/WrangleBot | **GAP** | 階層 ID 解耦；跨磁碟路徑穩定 |
| F36 | 非破壞 EDL/OTIO/FCPXML（FPS/TC/DF-NDF/source range/round-trip） | OTIO | **GAP** | EDL/OTIO 出→回 round-trip 首末格/TC 不變 |
| F37 | NLE adapter（Resolve/LSS/Kdenlive/Premiere；分級 import/marker/relink/export） | LSS/Resolve | **GAP** | 每平台分級 smoke；DIT 不寫 NLE timeline |
| F38 | MCP read-only tools（`search_media/get_asset/get_ingest_status/get_manifest/review_queue`） | Hermes Router | **PARTIAL**（naive `dit-offload/dit-metadata` 有 read-only `discover/verify/extract`，未分 read/write scope） | read-only 不需授權；write 需 scope |
| F39 | MCP guarded commands（`start_ingest/create_proxy/rerun_ai/propose_tags` 按節點批准與額度） | 自研 | **GAP** | 無 grant 的 write → deny + audit；額度超限拒絕 |
| F40 | 工作者連線與調度（CPU/M1/A770/Remote capability registry/health/lease/heartbeat） | 自研 | **GAP** | capability registry；A770 未連 → CPU fallback 明標 |
| F41 | 雲端 AI opt-in（預設 off/資料等級/用途預覽/授權費上限/outbound 稽核） | **ADR-DIT2-001** | **GAP**（`cloud.enabled=false`；未核准） | 無 ADR 核准 → 任何雲端呼叫 0；synthetic-only |

## E. Local A770 / Hard Probe（P1，HARDWARE_BLOCKED 以 deterministic 推進）

| ID | 需求 | 候選 | repo_now | test_spec |
|---|---|---|---|---|
| F42 | 本地 A770 驅動探測（Vulkan/QSV/OpenVINO/CPU fallback；逐碼型實測；不硬寫 fps 預期） | ffmpeg/llama.cpp | **GAP**（host 是 M1，`torch.xpu.is_available()=False`） | capability probe 回 device log；A770 無 → NOT_TESTED/BLOCKED，不填假成績 |

## F. 進階 / 可選（P2/O）

| ID | 需求 | 候選 | repo_now | test_spec |
|---|---|---|---|---|
| F43 | 多人與審片（RBAC/註釋/打點/review request） | iconik/axle.ai 對照 | **GAP** | 雙操作者不同身份確認/拒絕高風險；Event 記錄 |
| F44 | 360/魚眼檢索（reprojection recipe/eye map/coordinate 轉換寫 manifest） | arkiv 行為研究 | **GAP** | reprojection manifest 回 source coordinate |
| F45 | 智能 Selects（摘要片段清單；無自動刪片/不直接提交 timeline） | AI+審查 | **GAP** | Selects 僅建議；原片不刪 |
| F46 | 音訊對齊/多機位（wave/timecode/sync map/confidence/人工 approve） | LSS | **GAP** | sync map 回 TC；人工 approve |
| F47 | 素材重複偵測（byte-perfect vs perceptual hash；後者不可作刪原片依據） | hash+perceptual | **GAP** | byte-perfect 可判重複；visual-similar 不得自動刪 |
| F48 | Storage Policy（warm/cold/offline 分層/配額/pressure alert/restore locator） | NAS | **GAP** | 分層 restore locator 可回原片 |
| F49 | 拍攝現場模式（斷網/便攜 SSD/多卡/一鍵 PDF/HTML 報表） | Offload GUI | **PARTIAL**（naive 有 markdown 報表） | 斷網可完成 ingest+backup+報表 |
| F50 | 外網遠端檢視（Tailscale scoped auth；遠端只看 proxy/原片不公開；寫動作加 policy） | Tailscale/gateway | **GAP** | 遠端 read-only；寫動作 policy deny |
| F51 | Job 自動化規則（可宣告依賴 DAG/條件/節點重試/stage cache） | Hermes MCP | **GAP** | DAG 重試冪等；stage cache 命中的重放 |
| F52 | Open Project Export（OTIO/JSON/ASC MHL/CSV/SRT + schema 文件；禁專屬鎖定） | Mnemosyne/LSS | **GAP** | 各格式可匯出；schema 文件存在 |

---

## P0 驗收閉環（最小可交付安全切片）

依 SSOT Gate G1：**任何可能覆寫原片/健康備份或錯誤給出 SAFE 結論者不得勝出**。
P0 必達 11 項（F01–F11）+ 5 項（F12–F15）構成「實體卡資料進獨立 verified replicas + ASC MHL + durable queue」閉環。
**現有 naieve MCP 不得直接勝出**——它缺 F04/F06/F08/F09/F10/F11，P04 需以 clean-room 安全核心 + ProofCat/offloader 差分收斂。

## 下一切片掛鉤

- **P04**：以本 map 的 F04/F06/F09/F10/F11 為 clean-room 安全核心契約（`docs/engineering/spec/ingest-safety-contract.md`）。
- **P05**：以 F03/F35 建 `dit22` canonical ID / 資料模型（新 namespace，v4 DB 只讀）。
- **P07**：以 F04/F05/F09/F10 建故障注入 fixture（`tests/fixtures/dit22/`，synthetic，零真實素材）。

## 狀態統計（grounded，非宣稱）

- **DONE**：0（v4 既有 indexer/Qdrant 非 DIT 功能，不計入 52 項）
- **PARTIAL**：F21 / F31 / F38 / F49（naive 或部分覆蓋）
- **NAIVE**：F02 / F05（有邏輯但缺安全 invariant）
- **GAP**：其餘 43 項（P04–P19 依序推進）
- **HARDWARE_BLOCKED**：F42（A770 不在 host；以 capability probe + deterministic test 推進，成績填 NOT_TESTED/BLOCKED）

> 本 map 是「需求規格」，不是「已部署聲明」。任何 F 項升為 PASSED 須附本輪 fresh log/test/SHA（見 SSOT §7 Gate 禁止假設）。
