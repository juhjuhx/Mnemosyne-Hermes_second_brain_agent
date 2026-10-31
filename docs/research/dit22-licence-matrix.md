# DIT 2.2 License Matrix（P02 授權矩陣）

> 產生日期 2026-10-24。判定三類：**A 可採用**（授權相容、可進自研工程）／**B 待法務**（有授權但需釐清或逐檔核對）／**C 不可採用**（無授權、競品限制、或僅黑箱參考）。
> 主體授權：Mnemosyne 程式 = **AGPL-3.0-or-later**，文件 = **CC BY-SA 4.0**。

| 來源 | 授權 | 類別 | 理由 |
|---|---|---|---|
| proofcat (reynikman) | MIT | **A** | MIT 可併入 AGPL 產品，保留 NOTICE/License 檔 |
| offloader (owenpkent) | MIT | **A** | 同上；`--verify full` 與 data-safety 回歸測試為採用前置 |
| ascmitc/mhl（工具） | MIT | **A** | 交叉驗證 MHL 產生/比對 |
| ascmitc/mhl-specification | 無授權檔（2023-05-24 停更） | **B** | 標準引用不受限；範例程式碼複用前須補授權釐清 |
| PySceneDetect | BSD-3-Clause | **A** | 直接依賴合法；長鏡頭/VFR 需人工 GT |
| TransNetV2 | MIT | **A** | 上游 2023-12 後未更新，版本固定使用 |
| WeMM-Embedding（code） | Apache-2.0（Tencent，C 級確認） | **A**（實驗性） | 相容 AGPL；`trust_remote_code` 模型程式須先審查 |
| WeMM-Embedding-2B（weights） | Apache-2.0（HF 模型卡） | **A**（實驗性） | 本輪未下載；P15 固定 revision |
| Qwen3-VL-Embedding | Apache-2.0（repo 層） | **B** | 權重授權須逐項核對 HF 模型卡 |
| edge-ai-libraries（Intel） | Apache-2.0（repo 層） | **B** | 元件逐路徑 LICENSE 需核 |
| sentrysearch | Apache-2.0 | **A**（借鑑） | 固定窗結構借鑑；不進 runtime |
| OpenTimelineIO | Apache-2.0 | **A** | NLE 互通標準 |
| SIFT-Video | GPL-3.0 | **B** | GPL 與 AGPL 皆自由軟體，但元件需獨立目錄 + LICENSE/NOTICE 保留，不得靜默混入 |
| WrangleBot | LGPL-3.0 vs README GPL | **B** | 授權矛盾未釐清前不進程式碼庫 |
| OffloadMaster | 無授權檔 | **C** | 僅 UI 參考 |
| gemini-multimodal-search | 無授權檔（README 稱 MIT 未證實） | **C** | 僅 API 用法參考 |
| arkiv | **PolyForm Perimeter 1.0.1 + Additional Terms**（C 級確認 LICENSE 頭部） | **C（競品限制）** | 禁止 fork 作競品底座；僅公開文件/黑箱行為/互通 API 參考；不得繞過免費層限制 |
| Silverstack / KOCARD / axle.ai / iconik / Blackmagic | 專有 | **C（黑箱）** | 只看公開文件；不解密、不反編譯、不 bypass Pro |
| Gemini Embedding 2（API） | Google 商用 API 條款 | **B（雲端 opt-in）** | 需 ADR + 項目級核准；本輪零呼叫 |
| addyosmani/agent-skills | MIT (c) 2025 Addy Osmani（C 級確認 marketplace LICENSE 首行） | **A（harness 側）** | 已安裝於宿主 `~/.claude/skills/addyosmani-*`；僅影響 Agent 工作流，不進 Mnemosyne 程式碼，授權無風險 |
| obra/superpowers → juhjuhx V3 | MIT / repo 授權 | **A（harness 側）** | V3 canonical 已同步上游 digest |

**分發規則（適用於本分支所有後續 commit）**：複用之第三方程式碼保留其 LICENSE/NOTICE 於原路徑；GPL/LGPL 元件與 AGPL 主體分開目錄；無授權來源一律不進 `src/`。
