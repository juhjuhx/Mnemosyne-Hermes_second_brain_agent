# Tests

This directory contains all automated tests for the v4 plan.

## Layout

```
tests/
├── conftest.py                    Shared fixtures (tmp dir, mock HTTP, in-memory Qdrant)
├── eval_v2_100.jsonl              100-entry ground-truth eval set (referenced from the eval runner)
├── test_index_pipeline.py         Unit tests for src/scripts/indexer.py
├── test_qdrant_named_vectors.py   Invariant tests for Qdrant Named Vectors (text_vec + image_vec)
├── test_mcp_servers.py            stdio-loop tests for all 3 MCP servers
├── test_hermes_skills.py          End-to-end subprocess tests for each skill
├── requirements.txt               Test dependencies
└── README.md                      This file
```

## Running

```bash
# Install test deps
pip install -r tests/requirements.txt

# Run all unit tests (no live Qdrant / Ollama required)
pytest tests/ -v

# Run only the fast unit tests (skip integration)
pytest tests/ -v -m "not integration"

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing

# Run the eval set against a live system
python src/scripts/eval_runner.py \
    --eval-set tests/eval_v2_100.jsonl \
    --hermes-url http://127.0.0.1:8642 \
    --output tests/_results/$(date +%Y-%m-%d).json
```

## What each test file covers

### `test_index_pipeline.py`
- `Config` rejects `workers != 1` (v3 invariant)
- `detect_type` covers all extensions
- `chunk_text` splits paragraphs and caps at max_tokens
- `FileDB` upserts files + chunks
- `process_text_file` happy path: embed → Qdrant → SQLite
- `InboxHandler` only enqueues unseen files
- SHA-256 is stable

### `test_qdrant_named_vectors.py`
- `text_vec` is always 768-dim
- `image_vec` is the second named vector (512-dim in v4; 768 here for
  test simplicity, real production should be 512)
- The indexer always uses `text_vec` for text chunks
- `qdrant-search` routes by `modality` parameter

### `test_mcp_servers.py`
- All 3 skills respond to `initialize` with correct `serverInfo.name`
- All 3 skills respond to `tools/call` with JSON-RPC envelopes
- Unknown tools return a JSON-RPC error
- Missing video file returns an error dict, not a crash

### `test_hermes_skills.py`
- Spawns each MCP server as a subprocess
- Sends real JSON-RPC over stdin/stdout
- Asserts the response

## Invariant tests

The two v3/v4 invariants are enforced via test:

1. **Single worker** — `test_config_rejects_workers_greater_than_one`
2. **Named Vectors** — `test_indexer_uses_text_vec_named_vector`

If you change `indexer.py` to allow parallel file ingestion, or change
the Qdrant schema to use a single unnamed vector, these tests fail.

## Skipping live-network tests

The integration tests (`test_hermes_skills.py`) spawn real subprocesses
but do not require a live Qdrant / Ollama. They only test the stdio
transport and error handling. To run only those:

```bash
pytest tests/test_hermes_skills.py -v
```

## See also

- [`docs/02_方案文檔/評估測試集_v2.md`](../docs/02_方案文檔/評估測試集_v2.md) — the human-readable form of `eval_v2_100.jsonl`
- [`docs/02_方案文檔/Phase_4_評估與回饋指南.md`](../docs/02_方案文檔/Phase_4_評估與回饋指南.md) — how to run and score the eval set
- [`src/scripts/eval_runner.py`](../src/scripts/eval_runner.py) — the runner
