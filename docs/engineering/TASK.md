# TASK｜Mnemosyne DIT 2.2 自主研究與交接

- **Repo**：`juhjuhx/Mnemosyne-Hermes_second_brain_agent`
- **分支**：`research/dit22-multimodal-handoff-20261024`（worktree：`/Users/huang/Desktop/dit22-workspace/mnemosyne-dit22`）
- **目標**：依 SSOT（`docs/research/Mnemosyne_DIT_2_2_CONSOLIDATED_MASTER_2026-10-24.md`）與 Claude Code Prompt（`docs/research/Mnemosyne_DIT_2_2_CLAUDE_CODE_AUTONOMOUS_PROMPT_2026-10-24.md`）推進 P00–P19。
- **範圍**：研究、PoC、文件、synthetic 測試、Draft PR 交接。
- **驗收**：每切片有測試證據、獨立審查、commit SHA、ledger 記錄；所有 scoreboard 明確標 PASSED/FAILED/PARTIAL/NOT_TESTED/BLOCKED。
- **硬限制**（Non-negotiable，見 Prompt）：原片/卡片不可變動；雲端預設關閉且只許 synthetic fixture；不改 v4 Qdrant `text_vec(768)/image_vec(512)` 與 indexer 單 worker invariant；arkiv 不得作競品底座；不推 main、不自動 merge；第三方授權逐檔核對。
