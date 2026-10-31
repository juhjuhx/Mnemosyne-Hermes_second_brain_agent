# DIT 2.2 Source Ledger（P00/P01 凍結來源清單）

> 建立日期：2026-10-24（Asia/Taipei）｜建立者：Claude Code Agent（juhjuhx/Mnemosyne-Hermes_second_brain_agent `research/dit22-multimodal-handoff-20261024`）
> 方法：`gh api repos/<owner>/<repo>/commits/HEAD` 固定 SHA；`gh api repos/<owner>/<repo>` 讀取 default_branch / license / pushed_at。
> 信度標籤：**C**＝已直接讀取上游程式碼/授權檔；**D**＝僅讀取 repo 層授權/README 元資料；**I**＝工程判斷；**T**＝待實機驗證。

## 主體 Repo

| ID | 來源 | Pinned | 授權 | 狀態 |
|---|---|---|---|---|
| M01 | juhjuhx/Mnemosyne-Hermes_second_brain_agent `main` | `ddd79552fde8a1dbc25621dedb0ee8198e772ca6`（2026-06-10） | 程式 AGPL-3.0-or-later / 文件 CC BY-SA 4.0 | C。README 為 pre-implementation / v4 plan-freeze；44/105 檔案與 2026-06-05 frozen manifest 不同（授權變更等後續 commit 所致），`verify.py` exit 1。**本工作枝從 main HEAD 開出，不修改 frozen archive。** |
| M02 | juhjuhx/agent-skills `main`（Personal Tool Master V3） | `590be4cbd1305731270894b8a8644bf8af882719`（2026-10-22） | 見 repo | C。14 核心 skill 全部存在於 `origin/main`，本輪已逐一 `git cat-file` 驗證並計算 SHA-256（見 `dit22-skill-execution-ledger.jsonl` 的 `source_digest` 欄）。 |

## Skills / Harness 安裝稽核（P01 結論）

| 項目 | 證據 | 結論 |
|---|---|---|
| `using-superpowers`（juhjuhx canonical） | 本宿主 `~/.claude/skills/using-superpowers/SKILL.md` SHA-256 `fa0fa16abfaf1719…` 與 upstream `590be4c` 之 `using-superpowers/SKILL.md` **一致** | **已安裝、且與上游逐字同步**。本輪 Phase 起始實際以 `Skill(using-superpowers)` 載入並執行（ledger 有記錄）。 |
| Addy Osmani skills（`addyosmani/agent-skills`） | 宿主 marketplace 克隆 `~/.claude/plugins/marketplaces/addy-agent-skills`，git HEAD `13e43f2310224d5770a7fb0a8c24c02b73da69e9`（upstream `aeac41d` 之前版本），`LICENSE` = **MIT (c) 2025 Addy Osmani**；25 個 skill 以 `addyosmani-*` 前鏡安裝於 `~/.claude/skills/`；`commands/` 提供 `spec/plan/build/test/review/ship` 等 8 個 command | **已安裝（MIT 授權，可安全引用）**。命名空間注意：本宿主為 `addyosmani-<name>` 前鏡 skill，非 `/agent-skills:*` 插件命令；`installed_plugins.json` 只列出 `open-code-review`，addy 是以 marketplace 目錄 + 展開 skill 形式存在。 |
| Jesse Vincent Superpowers（`obra/superpowers`） | 上游 `2ce8aa15d05bd57213e6f746f953aafb7ded7a8b`，MIT；juhjuhx V3 之衍生來源 | 上游存在（D）。juhjuhx V3 已為其 fork 改良版，本輪以 V3 canonical 為準，不另裝 obra 原版。 |
| `agent-architecture-design` 等 293+ 私人 skills | `~/.claude/skills/` 目錄盤點 | 私人 Registry 內容**不可公開引用**；P00–P19 路由僅使用可公開驗證的 14 core + Addy 25。 |

## DIT Offload / 檔案保全候選

| ID | 來源 | Pinned | 授權（C/D） | 可重用判定 | 風險 |
|---|---|---|---|---|---|
| R06 | reynikman/proofcat（MIT，Rust+Tauri） | `29c06a251771bf94a0dd6453509c701d883a0628`（2026-08-20 最後推送） | MIT（D，repo 授權檔） | **候選核心 A**。`SAFE_TO_FORMAT` 安全狀態機、雙實體目的地、ASC MHL；作者 TEST_REPORT 僅屬作者自測（D） | 獨立故障注入未執行（T）；stars=0，維護活跃度低 |
| R08 | owenpkent/offloader（MIT，Python） | `e01a0eb034fd0056ae4a3385b187c70ba96d2a49`（2026-10-11） | MIT | **候選核心 B**。CLI/PySide6、`--verify full` 需顯式指定、PDF/CSV/MHL/HTML 報表、Python 整合優勢 | 歷史兩項資料安全缺陷已修復，**必須永久回歸測試**（source-only default ≠ full） |
| R10 | ascmitc/mhl-specification | `54b7eea3059f15bd7330b86d9e1e268eb2dcf039`（2023-05-24，**無授權檔**） | 標準文件 | 互通標準，直接引用 | 無 license 檔：規範文件本身作引用（非程式碼分發）風險低，但程式碼重用需先釐清 |
| R11 | ascmitc/mhl（參考工具） | `0fb61f1e4c7c1c3ff422449aa6f091ce0d3b7687` | MIT | 獨立 MHL 產生/驗證交叉比對 | — |
| R12 | vulture-s/arkiv | `2d9d86bbc758319f610acc7a3d6e7d9003c32b82`（2026-10-23） | **PolyForm Perimeter 1.0.1 + Additional Terms（C，已讀 LICENSE 頭部）** | **禁止 Fork 作競品底座**；僅黑箱/公開文件/互通 API 參考 | 競品限制；免費層 3 專案、Pro 付費；不得繞過 |
| R14 | AxelRothe/WrangleBot | `8961465105e2d36078006056138ed7770fb36f55`（2025-01-17） | LGPL-3.0（repo 授權檔）vs README GPL 說法 | **待法務釐清**；暫不納入程式碼庫，僅 UI 研究 | 授權矛盾；README 含 admin/admin 預設 |
| R15 | Hasoonab9749/offloadmaster | `9a330be6b60db3c33066fb670329a7674c5bb004`（2026-10-13） | **無授權檔** | 僅功能/UI 參考 | 無授權 = 程式碼不可複用 |

## 多模態 / 檢索 / 媒體

| ID | 來源 | Pinned | 授權 | 判定 | 風險 |
|---|---|---|---|---|---|
| R16 | Breakthrough/PySceneDetect v0.7.2 | `faa3d974709aa15dcf6bb3340df918360e338b92` | BSD-3-Clause | 可直接依賴（cut 偵測） | 長鏡頭/VFR 需人工 GT 對照 |
| R17 | soCzech/TransNetV2 | `85cef72af9a916bdfd7cc94a670c9cdfbf12d1ed`（2023-12-04） | MIT | 神經切鏡對照 | 上游長期未更新 |
| R22 | Tencent/WeMM-Embedding | `e8175bbff1071b580b3a6df8ec2c106e8383a361`（2026-09-20） | Apache-2.0（C，LICENSE 首行確認 Tencent Apache 授權文字） | 實驗性 provider `wemm_xpu`；權重另固定 HF `tencent/WeMM-Embedding-2B` revision | A770 XPU 未實測；建議 transformers==5.2.0；不含音訊 |
| R24 | ssrajadh/sentrysearch | `3694dd0cb27cc57920b2b816996ce5a22662e45c` | Apache-2.0（C，LICENSE 檔全文已讀取確認） | 時間窗/查詢結構借鑑 | 固定 30s+5s 窗 ≠ 語義分割 |
| R25 | QwenLM/Qwen3-VL-Embedding | `393e2978d27852b0d0230d6994f37f9c15bed73c` | Apache-2.0 | 對照組 | 權重授權須逐項再核 |
| R28 | open-edge-platform/edge-ai-libraries | `cc2ac98fb0d3de12e5b12db37ce8fea34aa4d75a`（2026-10-24 推送） | Apache-2.0（repo 層；元件逐路徑需核） | Intel OpenVINO baseline 首選 | WeMM 不在官方支援模型列表 |
| R31 | gabmichels/gemini-multimodal-search | `3b7d18d6eff8affbef6621de754d44a8971ed18b`（2026-03-16） | **無授權檔**（README 曾稱 MIT，未於 repo 確認） | 僅 API 用法參考 | 授權未證實 → 不進程式碼庫 |
| R30 | sourav4243/sift-video | `6d11676e2d60f1d999b5a859b60ccbc8a70636f9` | **GPL-3.0** | 多模態 timestamp 設計參考 | GPL 與 AGPL Mnemosyne 分發需審（皆自由軟體，但 GPL 元件進 AGPL 產品需 LICENSE 標記保留） |
| R33 | obra/superpowers | `2ce8aa15d05bd57213e6f746f953aafb7ded7a8b` | MIT | V3 上游 | 不直接安裝 |
| R39 | AcademySoftwareFoundation/OpenTimelineIO | `eee67fdcdce388696e39f4176d89a61ee9fdc790` | Apache-2.0 | NLE 互通 | — |

## 雲端 API（僅 synthetic + 明示核准後使用）

| ID | 來源 | 狀態 | 判定 |
|---|---|---|---|
| R20/R21 | Google Gemini Embedding 2（`ai.google.dev/gemini-api/docs/embeddings`） | 官方 GA；文字 8192 tokens、影片 ≤120s/≤32 frames、**影片不含音軌**、音訊 ≤180s、PDF ≤6 頁；128–3072d | 雲端選配；**無本機權重**，A770 量化路徑不存在；本輪**未呼叫任何 Gemini API**（零費用、零外傳）。v4 local-only invariant 下需 ADR（見 `dit22-architecture-decisions.md`）。 |

## 商用對照（只引用公開文件，不取閉源碼）

Silverstack（Pomfort）、KOCARD、axle.ai、iconik、Blackmagic Proxy Generator：僅公開網站/更新日誌作為**行為與工序對照**，無程式碼複用，無授權風險。B 站影片（R34–R36）為教學參考，**不是安全證據**。

## 未固定/待補

- HF 權重 `tencent/WeMM-Embedding-2B`：本輪未下載（A770 未接）；P15 啟動時須固定 `revision` SHA 並記錄 size/dtype。
- `ascmitc/mhl-specification` 無授權檔：若 P06/P07 需複用其範例程式碼，先補授權釐清（I：ASC 標準引用本身不受限，程式碼才受）。
- 實體 NAS / SD 卡 / A770 主機均不在本機：所有硬體相關項目標 `T`（HARDWARE_BLOCKED，改以 deterministic fixtures 推進，見 STATE.md）。
