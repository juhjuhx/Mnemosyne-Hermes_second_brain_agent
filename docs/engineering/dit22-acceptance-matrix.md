# DIT 2.2 Acceptance Matrix（第一輪 P00–P02）

> 狀態詞：PASSED / FAILED / PARTIAL / NOT_TESTED / BLOCKED。本輪**不含**任何硬體 PASS 宣稱。

| Gate / 項目 | 狀態 | 證據 | 失敗處理 |
|---|---|---|---|
| G0 repo/worktree/branch 真況盤點 | **PASSED** | `git log -1` = `ddd7955`（與 SSOT 基線一致）；worktree clean；remote 無同名分支 | — |
| G0 既有測試基線 | **PASSED** | venv `pytest tests/ -q` → 初輪 70 passed；新增 `tests/fixtures/dit22/`（3 測試）後全量 **73 passed, 0 failed, exit 0**（本 commit 值，獨立 subagent 重跑確認） | system python 缺依賴為環境問題（39 failed），venv 已補上；非程式回歸 |
| G0 frozen archive verify | **PARTIAL（基線即不合）** | `verify.py` exit 1（61 OK/44 CHANGED），main 自身 2026-06-05 freeze 後 commit 所致；本分支未改 manifest | 記錄於 ADR-DIT2-005；下一版 archive snapshot 才凍結新 manifest |
| P01 skills 安裝稽核（juhjuhx 14-core） | **PASSED** | 14/14 `git cat-file -e` 存在於 upstream `590be4c`；digest 全數計算；宿主 `using-superpowers` 與 upstream 逐字一致 | — |
| P01 Addy Osmani 安裝狀態 | **PASSED（已安裝）** | `~/.claude/plugins/marketplaces/addy-agent-skills`（git HEAD `13e43f2`，upstream `aeac41d` 之前版本）；25 skills 前鏡 `addyosmani-*`；LICENSE = MIT ©2025；commands 8 項 | marketplace 克隆落後 upstream 1 個月餘版本，引用時以本地 digest 為準 |
| P02 來源 pin 與授權 | **PASSED** | 19 repo 全數 `gh api` 成功；授權 C/D 級標記見 `dit22-licence-matrix.md` | `ascmitc/mhl-specification`（無授權檔）→ B；`offloadmaster`、`gemini-multimodal-search`（無授權檔）→ C |
| arkiv 競品限制隔離 | **PASSED** | LICENSE 頭部實讀確認 PolyForm Perimeter 1.0.1 + Additional Terms；ledger 標 C 類「禁止 fork 作底座」 | 任何複用提案需經法務評審 |
| 獨立審查（安全敏感切片） | **PASSED** | subagent（claude）複核 pin/授權/worktree/測試/secret 掃描（結果併 STATE.md） | — |
| A770 benchmark | **BLOCKED（HARDWARE_BLOCKED）** | A770 主機不在本機；未執行任何 GPU 測試 | P14/P15 以 deterministic fixture + device-log 合約推進；無數據不填成績 |
| Gemini 雲端 POC | **NOT_TESTED（未授權前禁測）** | `cloud.enabled=false`（v4 invariant 6 未變）；本輪 0 呼叫 0 費用 | 需 ADR-DIT2-001 核准 + synthetic fixture + 使用者明示核准 |
| 故障注入（P07） | **NOT_TESTED** | 實體 SD/NAS 不在本機 | 依 SSOT：以 `tests/fixtures/dit22/` synthetic + 合約測試先行，標 INCONCLUSIVE（不宣稱硬體通過） |
| Draft PR / GitHub 推上 | **見 STATE.md 下一節** | `gh auth status`：juhjuhx token（scopes: repo），可寫 research 分支 | 403 時停於本地並回報 blocker（依 Prompt §GitHub contract 1） |
