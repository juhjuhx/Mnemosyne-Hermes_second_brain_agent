# Phase 4 評估與回饋指南 — Evaluation & Iteration

> **Goal**: 100-eval suite runs to completion; metrics in green; ralph-watchdog loop works.
> **Duration**: 1-2 days initial setup, then continuous
> **Prerequisites**: Phase 3 complete

---

## 4.1 The 100-entry evaluation set

See [`評估測試集_v2.md`](評估測試集_v2.md) for the full set. Categories:

| Category | # entries | What it tests |
|---|---:|---|
| Direct retrieval (text) | 20 | Qdrant text_vec recall |
| Direct retrieval (image) | 20 | Qdrant image_vec recall |
| Cross-modal | 10 | Text query → image result |
| Temporal | 10 | "Files from 2024" |
| Tag-based | 10 | "Photos tagged 'family'" |
| Conversational | 10 | Multi-turn with memory |
| Tool-use | 10 | Hermes picks the right tool |
| Edge cases | 10 | Long queries, special chars, etc. |

## 4.2 The 10 metrics

| # | Metric | Target | How to measure |
|---|---|---|---|
| 1 | MRR@10 | ≥ 0.85 | For each query, find rank of correct doc in top-10 |
| 2 | Recall@10 | ≥ 0.80 | Fraction of relevant docs in top-10 |
| 3 | nDCG@10 | ≥ 0.85 | Discounted cumulative gain |
| 4 | Faithfulness | ≥ 0.90 | LLM-as-judge: is answer grounded in retrieved docs? |
| 5 | Answer relevance | ≥ 0.90 | LLM-as-judge: does answer address query? |
| 6 | Tool-call accuracy | ≥ 0.95 | Did Hermes pick the right tool? |
| 7 | Latency P50 | ≤ 3s (M1 easy), ≤ 8s (workstation hard) | Time from query to first token |
| 8 | Latency P95 | ≤ 10s (M1), ≤ 20s (workstation) | Time from query to last token |
| 9 | Index throughput | ≥ 50/h | Files per hour (excluding already-indexed) |
| 10 | Cost | monitored | Tokens × electricity |

## 4.3 The eval runner

```python
# tests/eval_runner.py

import json
import time
from pathlib import Path

EVAL_SET = Path("tests/eval_v2_100.jsonl")
HERMES_URL = "http://127.0.0.1:8642/v1"

def load_eval_set():
    with open(EVAL_SET) as f:
        return [json.loads(line) for line in f]

def run_query(query: str) -> dict:
    start = time.time()
    r = requests.post(
        f"{HERMES_URL}/chat/completions",
        json={
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": query}],
        }
    )
    elapsed = time.time() - start
    return {"response": r.json(), "latency": elapsed}

def main():
    results = []
    for entry in load_eval_set():
        result = run_query(entry["query"])
        result["entry"] = entry
        results.append(result)

    # Compute metrics
    metrics = compute_metrics(results)
    print(json.dumps(metrics, indent=2))

    # Save raw results
    Path("tests/_results").mkdir(exist_ok=True)
    with open(f"tests/_results/{int(time.time())}.json", "w") as f:
        json.dump(results, f, indent=2)

    return metrics
```

## 4.4 The ralph-watchdog loop

`ralph-watchdog` is an eval-driven iteration loop. Pattern:

```
┌──────────────────┐
│ 1. Run eval      │
│    (100 queries) │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. Detect        │
│    regression    │  ← if MRR@10 < 0.80 OR faithfulness < 0.85
└────────┬─────────┘
         ▼ (if regression)
┌──────────────────┐
│ 3. Diagnose      │
│    (ralph)       │  ← Hermes itself + user inspects failed queries
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 4. Propose fix   │  ← e.g. "Switch chunking strategy"
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 5. Apply fix     │  ← human-approved change to config / skill
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 6. Re-run eval   │
└────────┬─────────┘
         ▼
      (back to 1)
```

### ralph-watchdog config

```yaml
# ~/ai-brain/ralph_watchdog.yaml

thresholds:
  mrr_at_10: 0.80
  recall_at_10: 0.75
  ndcg_at_10: 0.80
  faithfulness: 0.85
  tool_accuracy: 0.90

actions:
  on_regression:
    - log_to: ~/ai-brain/logs/regressions.log
    - notify: "hermes:regression-detected"
    - auto_pause: true  # don't auto-apply fixes

max_iterations: 5
backoff: exponential  # 1h, 4h, 16h, 64h, 256h
```

## 4.5 Eval cadence

| Cadence | Who | What |
|---|---|---|
| After every config change | Auto (CI) | 10-query smoke test |
| Weekly | Auto (cron) | Full 100-query suite |
| After model swap | Manual | Full 100-query suite + report |
| After skill change | Manual | 10-query smoke + 5 relevant queries |
| Monthly | Manual | Full 100 + inter-annotator agreement check |

## 4.6 Inter-annotator agreement (for eval ground truth)

The 100-eval ground truth is annotated by the user (or 2 people). To check
quality:

1. Re-annotate 20% of the queries 2 weeks later
2. Compute Cohen's kappa
3. Target: κ ≥ 0.85

If κ < 0.85, the eval set has ambiguous queries — re-annotate.

## 4.7 LLM-as-judge for faithfulness / relevance

For metrics 4-5, we use a separate LLM as judge:

```python
JUDGE_PROMPT = """You are an impartial judge.

Query: {query}
Retrieved docs: {docs}
Answer: {answer}

Score the answer on two axes:
1. Faithfulness (0-1): Is every claim in the answer supported by the retrieved docs?
2. Relevance (0-1): Does the answer address the user's query?

Respond with JSON: {"faithfulness": X, "relevance": Y}
"""
```

The judge model is `gemma-edge` (M1) for fast iteration. For final
benchmarking, use `qwen-heavy` (workstation).

## 4.8 Eval report format

```markdown
# Eval Report — YYYY-MM-DD

## Summary

| Metric | Current | Previous | Delta | Target | Pass? |
|---|---:|---:|---:|---:|:---:|
| MRR@10 | 0.87 | 0.85 | +0.02 | 0.80 | ✅ |
| Recall@10 | 0.82 | 0.81 | +0.01 | 0.75 | ✅ |
| nDCG@10 | 0.86 | 0.85 | +0.01 | 0.80 | ✅ |
| Faithfulness | 0.91 | 0.92 | -0.01 | 0.85 | ✅ |
| Relevance | 0.93 | 0.92 | +0.01 | 0.90 | ✅ |
| Tool accuracy | 0.97 | 0.96 | +0.01 | 0.90 | ✅ |
| Latency P50 | 2.4s | 2.6s | -0.2s | 3.0s | ✅ |
| Latency P95 | 8.7s | 9.1s | -0.4s | 10.0s | ✅ |
| Throughput | 62/h | 58/h | +4/h | 50/h | ✅ |

## Regressions (if any)

None.

## Failed queries

- Q17: "Photos from last summer at the beach" → returned 5 generic beach photos, missed the specific one (file: 2024-07-15_da-an.jpg)
  - Diagnosis: Tag 'da-an' not in image_vec payload
  - Fix: Add `tag` field to payload, re-index

## Action items

- [ ] Add `tag` to image_vec payload
- [ ] Re-index 2024-07-15_da-an.jpg with tag
- [ ] Re-run Q17 in next eval
```

## 4.9 Common gotchas

| Problem | Fix |
|---|---|
| Eval takes >1h | Reduce from 100 to 10; or run in parallel on workstation |
| LLM-as-judge is biased | Use a different model as judge (e.g. Gemini Pro via Qwen) |
| Latency P95 spikes | Check if Ollama is being unloaded (sleep mode) |
| ralph loop infinite | Check `max_iterations`; cap at 5 |
| Throughput regresses | Check disk I/O; check if Qdrant is rebuilding HNSW |

---

## Next phase

→ [`Phase_5_進階路線指南.md`](Phase_5_進階路線指南.md) — Advanced (optional)
