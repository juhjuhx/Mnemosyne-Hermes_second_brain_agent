# Mnemosyne

> **Local-first AI Memory & Media Workbench（本地優先的 AI 記憶與媒體工作台）。** 一部私有第二大腦，在你的硬體上索引你的筆記、相片、影片與音訊；外加實驗性的 DIT 2.2 媒體子系統，把已驗證的素材轉成可恢復、租約封鎖的 proxy 管線。Developer Preview（RC-1）。

![Hero](docs/assets/rc1/mnemosyne-hero.svg)

| | |
|---|---|
| **狀態** | **Developer Preview（RC-1）**——核心安全管線已於本機實測＋獨立審查；Windows pilot 已立規格、尚未執行 |
| **授權** | 程式碼：[AGPL-3.0-or-later](LICENSE) ・ 文件與圖檔：[CC BY-SA 4.0](LICENSE-DOCS) ・ 第三方元件各保留原授權 |
| **驅動** | [Hermes Agent](https://github.com/NousResearch/hermes-agent) ・ Qdrant ・ Ollama/llama.cpp ・ FFmpeg ・ MCP |

---

## 1. Mnemosyne 是什麼？

**Mnemosyne**（μνημοσύνη，「記憶」）是一套本地優先的個人 AI 系統。一切運算都在你擁有的硬體上：你的文件、媒體與模型不離開你的區域網路，且無遙測。系統取自希臘記憶女神之名，也取自其所建構的長期記憶後端——第二大腦**本身就是一套記憶系統**。

它有兩條互相關連的產品線：

## 2. 兩條產品線

### Track A — 第二大腦 v4（私有文件與媒體索引）

- 私有索引筆記、相片、影片、音訊與 PDF。
- 本地 LLM：[Ollama](https://ollama.com)（Metal）或 [llama.cpp](https://github.com/ggerganov/llama.cpp)（Vulkan）。
- [Qdrant](https://qdrant.tech) 具名向量（`text_vec(768)` + `image_vec(512)`）——是可重建的索引視圖，**不是**真相源。
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) 搭配 [MCP](https://modelcontextprotocol.io) 工具契約與可擴充 skills（repo 內含 3 個範例 skill）。
- 資料擁有權在地：原檔絕不搬移、絕不修改；indexer 只做「建議」。

> **Track A 現況（誠實分層）**：v4 計畫已凍結、有 105 檔 SHA-256 存證快照；indexer／不變量／MCP skills 已 commit 並通過 CI。當時兩台參考機器離線，**實體服務整合仍屬硬體待辦**。精確分層見[實作狀態證據矩陣](docs/05_implementation-status-matrix.md)。

### Track B — Mnemosyne DIT 2.2（媒體子系統）

一個 DIT（Digital Imaging Technician）風格的影像搬移核心，是**專案內的媒體子系統**，不是取代 Track A：

- **來源與副本目錄**：內容定址資產、副本記錄、read-back 證據。
- **可驗證媒體來源**：來源准入閘（fail-closed）＋ **SourcePin**（內容 SHA256 在編碼前與編碼後雙重重哈希；漂移即丟棄，絕不發布）。
- **耐用 job queue**：SQLite、租約封鎖（lease fencing）、帶指數退避的重試預算。
- **FFprobe  metadata**：唯讀探測 FPS（含非整數／VFR）、時碼、HDR/Log、音軌配置；無法驗證時降級為 `unknown`，不猜。
- **CPU proxy 產生**：H.264 browser/editor 配置，staging → 驗證 → receipt → rename 的原子發布。
- **可恢復的發布**：唯讀恢復調整器——只有完整 generation、雜湊相符的產物、且有效 receipt 三者齊備才判 `PUBLISHED`。
- **場景偵測**：content-diff（CPU）＋固定間隔，記憶體有硬上限。
- **防護層**：memory guard、路徑隔離（symlink/traversal）、容量預留、Windows 安全檔名。

> **Track B 現況（誠實分層）**：P11.1/P12/P12.1/P12.2 在研究分支上 **LOCAL TESTED / REVIEWED**——330 測試全綠、獨立審查完成、**尚未 commit**。Windows CPU Pilot 為 **SPECIFICATION ONLY**；UNC/SMB、A770 GPU、真實相機媒體家族為 **HARDWARE BLOCKED / UNVERIFIED**。見[狀態矩陣](docs/05_implementation-status-matrix.md)。

## 3. 它解決什麼問題？

- **擁有權**——搜尋與處理你的媒體不用上雲；無 SaaS、無遙測。
- **管線信任**——衍生 proxy 只有在「產物＋雜湊＋receipt」三者一致時才是 `PUBLISHED`；來源中途變動絕不會偽裝成可信輸出。
- **可恢復性**——崩潰殘留（zombie staging、孤兒 receipt、過期 worker）以唯讀方式分類並附上安全處置，絕不自動刪除。
- **可重現性**——全部測試以產生的合成媒體為基礎；證據包內無真實素材、無個人絕對路徑。

## 4. 適合誰？

- 想要私有、可稽核媒體工作流的創作者與剪輯師。
- 在自己硬體上建構 local-first AI 的開發者（Hermes + MCP 可擴充）。
- DIT 專業者——要的是來源、證據與可恢復的 job，而不是速度。

## 5. 目前能力（按證據分層）

| 能力 | 分層 |
|---|---|
| v4 計畫存檔，105/105 SHA-256 驗證 | COMMITTED |
| indexer 核心＋7 不變量、具名向量測試 | COMMITTED / CI VERIFIED |
| 3 個 MCP skills（qdrant / filesystem / video-slice） | COMMITTED / CI VERIFIED |
| DIT 2.2 准入、封鎖、proxy、恢復、P12.2 閘 | LOCAL TESTED / REVIEWED（330 測試，未 commit 的研究分支） |
| 雙機實體部署（M1 + 工作站） | HARDWARE PENDING |
| Windows CPU Pilot（A770 工作站） | SPECIFICATION ONLY |
| GPU 加速（QSV/OpenVINO） | HARDWARE BLOCKED |
| 真實相機媒體家族（Sony BRAW/XAVC 等） | UNVERIFIED（僅合成 fixture） |
| 互動式開發者 TUI | NOT IMPLEMENTED（僅設計概念＋已標註的 mockup） |

完整明細：[實作狀態證據矩陣](docs/05_implementation-status-matrix.md)。

## 6. 架構總覽

![Architecture](docs/assets/rc1/architecture-overview.svg)

- **Track A**：文件/媒體 → 分塊 → 向量 → Qdrant 具名向量 → 本地 LLM → Hermes MCP。
- **Track B**：准入 → SourcePin → 耐用 queue → 容量閘 → CPU 編碼 → 重驗 → 原子發布 → 唯讀調整。
- **共用不變量**：原檔絕不修改；索引可重建；閘 fail-closed；預設全在地。

媒體管線細節：[安全流程圖](docs/assets/rc1/media-pipeline-safety.svg) ・ [DIT 2.2 開發者快速上手](docs/dit22-quickstart.md)。

## 7. 五分鐘合成開發者 demo

不需要相機卡、NAS、Windows、GPU 或雲端 token——全用產生的媒體與隔離暫存資料集，純 CPU。此 runner 1:1 對應已測試的公開 API（沒有捏造指令）：

```bash
# Python 3.10–3.12；PATH 需有 ffmpeg + ffprobe
pip install -e .            # 安裝 dev 依賴（pyproject）
python examples/dit22_synthetic_demo.py
```

八步：來源 probe → CPU proxy → receipt 驗證 → 受控安全失敗 → 唯讀恢復判定 → editor proxy 驗證 → CPU 場景偵測 → Windows 安全檔名＋容量閘。機器可讀證據（無絕對主機路徑、無憑證）寫入 `demo_evidence_bundle.json`。

Demo 屬 **MODULE-LEVEL**：分開行使已測試 API；尚無單一支管的端到端 CLI（屬下一開發階段）。

## 8. 系統需求與支援平台

| 需求 | 規格 |
|---|---|
| Python | 3.10 – 3.12（建議 venv） |
| 媒體工具 | PATH 上的 `ffmpeg` + `ffprobe`（CPU 基準；不需 GPU） |
| 作業系統 | macOS（Apple Silicon / Intel）與 Linux 有測試覆蓋；**Windows 屬規格階段**（CPU Pilot 待授權） |
| Track A 服務 | Qdrant、Ollama 或 llama.cpp、Hermes Agent——見[階段指南](docs/02_方案文檔/Phase_0_啟動手冊.md) |
| 記憶體 | 場景偵測有影格上限（P12.1）；長片 4K 尚未驗證 |

## 9. 安全原則與許可邊界

1. **原檔是真相**：索引是衍生、可重建視圖；絕不自動搬移、絕不自動刪除。
2. **fail-closed 閘**：准入、pin 驗證、租約封鎖、容量、路徑隔離——模稜兩可即拒決。
3. **預設無雲端**：全在地、100% 在你自己的硬體上；架構**日後可**加入明確 opt-in 的雲端 provider，但本 release 沒有設定、也沒有呼叫任何雲端 API——那是獨立、公開宣布的決策，不是隱性行為。
4. **誠實狀態**：硬體阻塞項明標；合成測試絕不報告為實機 PASS。
5. **15% 剩餘空間僅為諮詢性**：低空間時停止「新」proxy/embedding 任務；絕不自動刪除原片、音樂或備份。

## 10. 開發者 TUI（設計，已明確標註）

互動式開發者 TUI **尚未存在**——下圖為由靜態 fixture 資料產出的 **CONCEPT MOCKUP**，絕不冒充已出貨功能。本 release 唯一的終端機截圖是合成 demo 的真實執行輸出（可重現）：`python examples/dit22_synthetic_demo.py`。

設計系統（6 畫面、合成資料）：[TUI 設計與 mockup 指南](docs/dit22-tui-design.md) ・ [mockup 圖檔](docs/assets/rc1/tui-dashboard-concept.svg)

### 視覺身分

克制的工程視覺系統（深灰石墨／午夜藍底、冷藍＝記憶與索引、暖琥珀＝相機媒體與 DIT 處理、細網線＋媒體時間軸校驗記號）。可編輯 SVG 源＋PNG 導出（`rsvg-convert`）在 [`docs/assets/rc1/`](docs/assets/rc1/)：

| 資產 | 源檔（可編輯） | 導出 PNG | 用途 |
|---|---|---|---|
| Hero 橫幅 | [mnemosyne-hero.svg](docs/assets/rc1/mnemosyne-hero.svg) | mnemosyne-hero.png | README 首頁（1280×320） |
| Social preview | [social-preview.svg](docs/assets/rc1/social-preview.svg) | social-preview.png | GitHub 倉庫 social-preview 設定（1280×640、<1MB）——經 **repo Settings → Social preview** 手動上傳（見下）；上傳前仍顯示預設倉庫卡片 |
| 專案圖示 | [mnemosyne-icon.svg](docs/assets/rc1/mnemosyne-icon.svg) | mnemosyne-icon.png | 方形 mark（1280×1280，可縮放） |
| 架構總覽 | [architecture-overview.svg](docs/assets/rc1/architecture-overview.svg) | architecture-overview.png | 兩軌＋共用安全核心 |
| TUI dashboard 概念 | [tui-dashboard-concept.svg](docs/assets/rc1/tui-dashboard-concept.svg) | tui-dashboard-concept.png | **CONCEPT MOCKUP**（圖內含 DESIGN PREVIEW 水印） |
| 媒體管線／安全流程 | [media-pipeline-safety.svg](docs/assets/rc1/media-pipeline-safety.svg) | media-pipeline-safety.png | fail-closed 管線、誠實分層 |

> 除 demo 真實執行截圖（REAL EXECUTION）外，**沒有任何資產是運作中軟體的截圖**；皆未呈現偽造操作狀態、benchmark 或真實素材。PNG 目視簽核標 **VISUAL_QA_PENDING**（製備時自動視覺審查不可用）；SVG 源為可編輯真相、渲染具決定性。

## 11. 文件索引

- [`docs/00_index.md`](docs/00_index.md) — v4 計畫工件主目錄。
- [實作狀態與證據矩陣](docs/05_implementation-status-matrix.md) — 每個元件的誠實分層。
- [DIT 2.2 開發者快速上手](docs/dit22-quickstart.md) — Track B，從 clone 到第一支 proxy。
- [TUI 設計與 mockups（DESIGN PREVIEW）](docs/dit22-tui-design.md)。
- [DIT 2.2 工程紀錄](docs/engineering/P11.1-safety-integration-review.md) ・ [P4 整合契約審計](docs/engineering/P4-integration-contract-audit.md)。
- [Windows CPU Pilot 規格](docs/engineering/spec/Windows-CPU-pilot-A770.md) ・ [Windows 工作站普查規格](docs/engineering/spec/Windows-workstation-census.md)。
- 疑難排解與恢復：[還原演練](docs/06_備份與同步/還原演練.md) ＋ Track B 唯讀恢復調整器。
- [CONTRIBUTING](CONTRIBUTING.md) ・ [SECURITY](SECURITY.md) ・ [CODE OF CONDUCT](CODE_OF_CONDUCT.md)。

## 12. 路線圖與現有限制

- **Windows CPU Pilot**（A770 工作站，設計上純 CPU）——規格完成，等執行授權。
- Track B 安全層 commit（C1/C2/C3 原子切片）——已準備，等授權。
- GPU/QSV/OpenVINO 驗證——硬體阻塞，以普查驅動。
- P13 語義分割——本 release 未啟動。
- 堅固限制：UNC/SMB 持久性、斷電恢復、真實相機媒體家族，在取得實體證據前皆不出現於「已支援」清單。

## 13. 授權與致謝

- **程式碼**：[AGPL-3.0-or-later](LICENSE)。**文件/圖檔/評估集**：[CC BY-SA 4.0](LICENSE-DOCS)。
- **第三方元件各保留原授權**——Hermes Agent（MIT）、Qdrant（Apache-2.0）、Ollama、llama.cpp（MIT）、Open WebUI、Tailscale、PySceneDetect 與 Mnemosyne 記憶後端都是獨立交件、各依自己的條款；見[元件整合表](docs/02_方案文檔/架構B_開源組件整合表.md)。
- 感謝 [Nous Research](https://nousresearch.com)（Hermes Agent）、[Qdrant](https://qdrant.tech) 與讓 local-first AI 成為可能的開源維護者。

---

*「記憶永不遺忘。原檔是真相；索引是衍生視圖。」——Track B 加一句：發布產物只有在「產物＋雜湊＋receipt」三者一致時才值得信任。*
