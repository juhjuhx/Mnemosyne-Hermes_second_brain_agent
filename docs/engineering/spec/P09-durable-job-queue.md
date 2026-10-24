# P09 — Durable Job Control（F17，TDD 垂直切片）

**產出**：2026-10-24　**方法**：writing-plans 先定契約 → TDD → 獨立審查
**範圍**：純 stdlib SQLite、獨立 `dit22` namespace（新檔案 `dit22_jobs.db`）；**絕不開啟/寫入** v4 `files.db`、不改 `indexer.py` 任何行為（SSOT P09 驗收條款）。

## 1. 資料模型（F17 欄位全數落地）

`DurableJobQueue(db_path)`，job 列：

| 欄位 | 語意 |
|---|---|
| `job_id` | 唯一 job 識別（uuid） |
| `idempotency_key` | 同 key 重入 queue＝冪等 no-op（回同一 job_id） |
| `input_manifest` | 輸入快照指紋（dict rel→sha256 的 JSON）；resume 前須重驗，漂移即拒 |
| `state` | `PENDING`／`LEASED`／`PAUSED`／`DONE`／`FAILED` |
| `priority` | 同優先級 FIFO；較高優先級先出 |
| `attempt` | 每次 lease 成功 +1 |
| `lease_token`／`lease_expires_at` | lease 租約；過期可被其他 worker 重新取得 |
| `checkpoint` | JSON 進度快照（interrupt-safe resume 依據） |
| `reversible` | 預設 `True`；`False`＝**不可逆輸入**：失敗後**絕不自動重試**，須顯式人工授權 |

## 2. 契約（可測試行為）

1. **冪等**：同 `idempotency_key` 二次 enqueue → 同 job_id、不新增列。
2. **Lease 排他**：同一 job 同時只容一個**未過期** lease；未過期的他人 lease → `LeaseHeldError`；過期 lease → 可被新 worker 接管（attempt+1）。
3. **Checkpoint 冪等重入**：pause 後 resume 保留 checkpoint；同 worker 重 lease 自己持有效 lease＝no-op 不增 attempt。
4. **Input manifest 漂移**：resume/complete 時重驗 manifest，不符 → 回 `FAILED`（絕不繼續跑）。
5. **不可逆輸入**：`reversible=False` 的 job 進入 `FAILED` 後，`retry()` 拒絕（`IrreversibleRetryError`）；唯一出路＝人工建新 job（新 key）。
6. **多 worker 安全**：併發 lease 由 SQLite 序列化＋lease 列驗證保證不重入；本切片只保證單一 DB 檔案語意，不引入 daemon（ADR-DIT2-003 佇列並行仍 PROPOSED 待核准）。
7. **v4 隔離**：module 只建/寫自己傳入的 `db_path`；測試斷言 v4 `files.db` 路徑不存在也不被開啟。

## 3. 測試分層

- `@behavior_tested`：實調 `DurableJobQueue` 斷言上述 1–5、7。
- v4 隔離：行為測試中注入 fake v4 路徑，斷言 queue 對其零接觸。

**驗收**：12 測試全綠；全量回歸無 regress；多 worker 不違反舊 indexer＝queue 完全不含 indexer 邏輯（零耦合，靜態 import 審查可證）。
