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

## 4. P09.1 addendum — lease fencing（2026-10-24）

P09's `lease()` is CAS-armed, but the lease-protected state updates
(`update_checkpoint` / `pause` / `fail` / `complete`) are still
read-check-write: they only compare the worker *name*, never the
`lease_token`. Two exploitable shapes:

- **stale token**: a worker whose lease was taken over (crash → expiry →
  re-lease) still believes it holds the job and writes checkpoint /
  completes with its old token;
- **same worker name, two incarnations**: a restarted worker re-leases
  under the *same name*; the old process (or a stale connection) can
  overwrite the new incarnation's state, because the check is
  name-based and name is not a fencing token.

## Contract

Every lease-protected state update becomes a **single conditional UPDATE**
whose WHERE clause re-checks the full fence at write time:

```
WHERE job_id = ?
  AND state = 'LEASED'
  AND lease_token = ?      -- the exact token the caller holds
  AND lease_worker = ?     -- name consistency (diagnostics)
  AND lease_expires_at IS NOT NULL
  AND lease_expires_at > ? -- still unexpired at write time (now)
```

`rowcount = 0` ⇒ **fail-closed**: raise `LeaseFencedError`. Never silent,
never a partial success, never a re-read retry loop (the caller must
re-lease to act again).

- API: `update_checkpoint(job_id, worker, checkpoint, token)`,
  `pause(job_id, worker, token)`, `fail(job_id, worker, token, reason)`,
  `complete(job_id, worker, actual_manifest, token)` — the token is
  mandatory; the P09 PENDING/PAUSED retry path is unchanged.
- `complete()` drift path is fenced the same way: only the current holder
  may mark the job FAILED for manifest drift.

## External side-effect fencing (required to evaluate, not silently assume)

DB-level CAS protects **queue state only**. A worker that writes external
artifacts (files to a target dir, staged proxies, NAS uploads) between
lease and complete has a hole: it can crash *after* writing external files
but *before* the DB commit, or have its lease stolen and keep writing.
The P09.1 answer for this project:

- **Do NOT** treat the DB CAS as a complete guard for external writes.
- External writes must be fenced by the *destination's* own atomic
  contract: P08's `StagedArchive` already does this (staging dir →
  verify → LAST-WRITE receipt; no receipt = not committed). P11 proxy
  publishing MUST reuse that shape: a proxy file only counts once its
  receipt matches, and the receipt records the `job_id` + `lease_token`
  so a stolen-lease writer's artifacts are detectable and discardable.
- Workers SHOULD record their `lease_token` in any external "in-progress"
  marker they write (e.g. the staging dir name or an `<out>.intent.json`
  sidecar), so recovery can attribute pre-commit artifacts to a dead
  lease and clean them without touching the target.

Scope: this is a DB-layer hardening of P09 + a documented evaluation of
the external boundary. It does **not** open multi-worker deployment
(ADR-DIT2-003 remains PROPOSED).

## P09.1 test matrix (all `@behavior_tested`)

| # | scenario | expectation |
|---|---|---|
| 1 | expired lease taken over by w2; w1's stale token does checkpoint/pause/fail | all raise `LeaseFencedError`; w2's state untouched |
| 2 | same worker NAME re-leases after its own expiry (restart); old token writes | old token rejected, new token accepted, `attempt`=2 |
| 3 | two `DurableJobQueue` handles on one file; q1 stale token after q2 takeover | q1 fail-closed, q2 intact |
| 4 | complete() after expiry by the old holder | `LeaseFencedError`, job stays LEASED to w2 |
| 5 | complete() drift with a *valid* token | regression: `False` + FAILED |
| 6 | checkpoint/pause/fail with a valid token | happy paths unchanged (regression) |

