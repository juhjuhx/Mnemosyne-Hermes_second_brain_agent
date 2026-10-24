# DIT 2.2 Architecture Decision Records（提出中，未核准）

> 狀態：全部 **PROPOSED**（v4 七項 invariant 未被修改）。依 AGENTS.md 規則，任何打破 invariant 的變更在 ADR 核准前**不得實作**。本文件只提出方案與安全預設，不啟用雲端、不改 Qdrant schema。

## ADR-DIT2-001｜雲端 opt-in 與 v4 local-only invariant（6 號 invariant）

- **狀態**：PROPOSED（待核准）。**未核准前行為 = v4 不變：`cloud.enabled=false`，零外傳。**
- **衝突**：DIT 2.1/2.2 需要 Gemini Embedding 2 雲端選配；v4 invariant 6 禁止 cloud LLM/embedding/STT。
- **提案**：新增 `cloud` 策略層，預設 `local_only`；`cloud_allow_metadata / cloud_allow_redacted_frames / cloud_allow_media` 三級 opt-in 皆需**項目級 + 批次級**雙重核准、費用上限、資料最小化（不傳原片/縮圖以外）、outbound audit log。敏感標記素材（客戶、私密、可識別人）一徑拒絕。
- **安全預設（本分支正在遵守）**：Gemini 僅於 synthetic/license-cleared fixture 且使用者明示核准後才可呼叫；本輪迄今 **0 次雲端呼叫、0 費用**。
- **被否方案**：無聲啟用雲端（違反 v4）；完全不允許雲端（阻斷需求，但預設行為等同此案直到核准）。

## ADR-DIT2-002｜向量 profile 隔離（1 號 invariant：`text_vec(768)+image_vec(512)`）

- **狀態**：PROPOSED。舊 collection **不動**。
- **提案**：新模型一律寫入新 collection（例 `dit22_wemm2b_mrl512_v1`、`dit22_siglip_openvino_v1`、`dit22_gemini2_768_v1`），每 collection 綁 `embedding_profile_id = model+revision+processor+normalize+dtype+MRL dim+sample policy`。跨模型只用 **rank fusion（RRF）**，絕不跨模型 cosine。MRL 降維後須重新 L2 normalize。
- **被否方案**：直接改 `image_vec(512)` 維度或把 WeMM 向量寫入舊 named vector（違反 invariant 1，且 512d 同維 ≠ 同空間）。

## ADR-DIT2-003｜佇列並行與舊 indexer 單 worker（2 號 invariant）

- **狀態**：PROPOSED。舊 `src/scripts/indexer.py` 的 `workers==1` invariant **維持不碰**。
- **提案**：DIT 新 pipeline（media probe / offload / proxy / embedding）使用**獨立 durable queue**（冪等 job、lease、checkpoint），與 v4 檔案 indexer 不同系統；多 worker 僅於新 queue 內、且以 resource budget 限制。v4 原 `in_memory_qdrant`/`indexer` 行為與測試全數保留（本輪 70 測試全通過即證據）。
- **被否方案**：直接改 indexer worker 數（破壞 invariant 2 與其測試 `test_config_rejects_workers_greater_than_one`）。

## ADR-DIT2-004｜DIT 安全狀態機與 fail-closed

- **狀態**：PROPOSED。
- **提案**：`DISCOVERED→STABLE→PREFLIGHT_OK→COPYING→COPY_COMPLETE→DESTINATION_READBACK→HASH_VERIFIED→ASC_MHL_PERSISTED→REPLICA_POLICY_PASS→VERIFIED_AND_BACKED_UP`；任何 gate 缺即 fail-closed。`SAFE_TO_FORMAT` 只作為**受權操作員的建議顯示**，系統永不自動格式化/刪除。Mirror/RAID1 永不計為獨立備份；unknown 實體身份一律 `BLOCKED`。
- **測試守衛**：人工審核狀態（GOOD/NG/REVIEW）不得被 AI 重跑覆蓋；未 verified 素材不排 proxy/AI job。

## ADR-DIT2-005｜frozen archive verify.py 現況紀錄

- **事實**：`_archive/2026-06-05-v4-plan/verify.py .` 在本輪**兩棵 worktree 皆 exit 1（61 OK / 44 CHANGED / 0 MISSING）**——CHANGED 檔案最後修改均在 2026-06-05（v4 授權由 MIT 改 AGPL 等 freeze 後 commit），即 **main 自身已不符合 2026-06-05 manifest**，非本分支造成。
- **決策**：依 AGENTS.md「frozen manifest 不得原地修改、只可新增下一版 snapshot」，本分支**不更新** 2026-06-05 manifest，改在此 ADR 記錄現況；下一版 archive snapshot 建檔時再凍結。
