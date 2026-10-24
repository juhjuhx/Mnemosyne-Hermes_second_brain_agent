# EVIDENCE｜DIT 2.2 第一輪（P00–P02）

## 執行環境
- Host：macOS（darwin 24.6），Python 3.14.5（system）；venv `/Users/huang/Desktop/dit22-workspace/mnemosyne-venv`
- Git worktree：`/Users/huang/Desktop/dit22-workspace/mnemosyne-dit22`，branch `research/dit22-multimodal-handoff-20261024` @ `ddd79552fde8a1dbc25621dedb0ee8198e772ca6`

## 命令與結果（可重跑）

| # | 命令 | 結果 |
|---|---|---|
| 1 | `git clone --no-checkout` + `git log -1` | main HEAD `ddd7955`（與 SSOT 基線 `ddd79552fde8a1dbc25621dedb0ee8198e772ca6` 完全一致） |
| 2 | `git ls-remote --heads origin 'research/*'` | 無同名分支 → collision-safe 建 `research/dit22-multimodal-handoff-20261024` |
| 3 | `git worktree add -b research/dit22-multimodal-handoff-20261024 …/mnemosyne-dit22` | 成功；`git status` clean（僅新增未追蹤 docs/） |
| 4 | `python3 -m pytest tests/ -q`（system 3.14） | **39 failed / 31 passed**——根因：system python 缺 `qdrant_client`、`watchdog`（未 `pip install -e .`），**非程式回歸** |
| 5 | `python3 -m venv …/mnemosyne-venv && pip install -e ./mnemosyne-dit22 && pip install pytest` | 成功 |
| 6 | `…/mnemosyne-venv/bin/python -m pytest tests/ -q`（worktree） | **70 passed, 5 warnings, exit 0**（初輪）；新增 `tests/fixtures/dit22/` 3 測試後全量重跑 → **73 passed, 4 warnings, exit 0**（本 commit 實際值，獨立 subagent 已重跑確認） |
| 7 | `python3 _archive/2026-06-05-v4-plan/verify.py .`（兩棵 worktree） | **exit 1：61 OK / 44 CHANGED / 0 MISSING**——44 個 CHANGED 檔案最後修改皆 2026-06-05 freeze 後 commit（授權 MIT→AGPL 等），main 自身即不合 manifest；本分支未改 manifest（ADR-DIT2-005） |
| 8 | `gh api repos/<o>/<r>/{commits/HEAD,license,…}` ×19 | 全數成功；pin SHA 與授權記入 `dit22-source-ledger.md` |
| 9 | `git show origin/main:<skill>/SKILL.md | shasum -a 256` ×14 | 14 canonical skills digest 全數取得（`~/.claude/skills/using-superpowers` 與 upstream `590be4c` 逐字一致） |
| 10 | 宿主安裝盤點（`~/.claude/skills/`、`~/.claude/plugins/`） | Addy 25 skills 以 `addyosmani-*` 前鏡安裝；marketplace 克隆 HEAD `13e43f2`；LICENSE = MIT ©2025 Addy Osmani；`commands/` 含 spec/plan/build/test/review/ship 等 8 項 |

## 獨立審查
- Subagent（`claude`）獨立複核：授權結論（arkiv PolyForm、WeMM Apache-2、WrangleBot LGPL、sift-video GPL、無授權檔清單）、pin SHA 表、worktree 狀態、venv 測試、secret 掃描 → 結果已併入本輪（見 STATE.md「獨立 subagent 複核」）。

## 安全與授權狀態
- 雲端 API 呼叫：**0**（Gemini 未啟用，無費用、無外傳）
- 真實素材/相機卡/NAS：**未接觸**（本輪全部 synthetic/文件/上游元資料）
- 第三方授權：arkiv＝C 類（競品限制，僅黑箱參考）；無授權檔來源＝C 類不入 `src/`；GPL（sift-video）＝B 類需分目錄
- v4 七項 invariant：**全數維持**（未改 Qdrant schema、未動 indexer、未開雲端、未自動搬移檔案）

## P03 獨立重驗與校訂（2026-10-24，本輪新執行）

| # | 命令 | 結果 |
|---|---|---|
| P03-1 | `…/mnemosyne-venv/bin/python -m pytest tests/ -q`（獨立重跑） | **73 passed, 0 failed, exit 0**（證實 P00–P02 證據） |
| P03-2 | `gh pr view 1 … --json headRefOid` vs `git rev-parse HEAD` | 皆 `bbd6ff71439fd9920998eed1d8f9696128ab5851`，Draft PR #1 真實存在且與 local 同步 |
| P03-3 | `ls -d ~/.claude/skills/addyosmani-* \| wc -l` + `ls …/addy-agent-skills/skills \| wc -l` | **24 / 24**（修正先前記錄「25」；25 為上游 README 宣稱，本 marketplace 克隆 `13e43f2` 實裝 24） |
| P03-4 | `python3 -c "import torch; …xpu.is_available()"`（host M1） | `torch 2.13.0`，**xpu avail False** → F42/A770 標 HARDWARE_BLOCKED，不填 GPU 成績 |
| P03-5 | 讀 `src/hermes_skills/dit-offload/dit_metadata_server.py` | 定位 naive 安全缺口（collision=改名、無 source guard/MHL/fingerprint/狀態機）→ 寫入 `spec/F01-F52-requirements-map.md` repo_now 欄 |

**記錄校訂**：Addy Osmani 宿主實裝數 = **24**（先前 P00–P02 記「25」，以上游 README 為準；本輪改以檔案證據為準，兩處 ledger 已同步修正）。
