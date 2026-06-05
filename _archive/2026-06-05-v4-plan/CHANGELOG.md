# Changelog — Archive 2026-06-05-v4-plan (Mnemosyne)

## v4.0.0-2026-06-05-plan — Mnemosyne v4 plan freeze

**Date**: 2026-06-05
**Status**: Plan complete, awaiting hardware deployment
**Files**: 105 (~508KB)

### What was new in v4 (vs v3)

- **Architecture B chosen** (dual-machine: M1 Air 8GB + workstation 5800X/48GB/A770)
  - v3 was M1-only; v4 splits perception/edge (M1) from heavy inference (workstation)
- **Hermes Agent replaces self-built FastAPI**
  - 162K★ MIT-licensed, native MCP, native Mnemosyne
  - v3 had a 600-line custom agent loop
- **Mnemosyne replaces custom memory layer**
  - 98.9% LongMem benchmark, SQLite-only (no Postgres dependency)
  - v3 had a 200-line custom in-memory store
- **Hermes skills standard (agentskills.io)**
  - 3 example skills shipped: qdrant-search, filesystem-search, video-slice
  - Each with SKILL.md + manifest.json + src/ + tests + README
- **Qdrant Named Vectors** (text_vec 768 + image_vec 512)
  - Preserved from v3; now with explicit invariant tests
- **llama.cpp + Vulkan** on workstation (A770 16GB)
  - Self-speculative decoding via MTP head (Ex0bit PRISM-DQ)
  - v3 used llama.cpp + CUDA, not Vulkan
- **Tailscale mesh** with tag-based ACLs
  - Replaces v3's bare LAN
- **MCP for all tool surfaces**
  - filesystem, Qdrant, tags, shell, video-slice, whisper
  - Replaces v3's ad-hoc REST endpoints
- **Open WebUI** as Web front-end
  - Replaces v3's no-UI default
- **8GB RAM budget** (M1) and **48GB RAM budget** (workstation) documented
- **GitHub-ready** structure (LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, etc.)

### What was preserved from v3 (DO NOT BREAK)

- **Single worker indexer** — parallel embedding, not parallel files
- **Named Vectors** — `text_vec(768) + image_vec(512)` per Qdrant point
- **Memory never forgotten** — original files preserved, index rebuildable
- **Never auto-move** — indexer suggests, never mutates source
- **No facial / voice emotion monitoring**
- **Local-first** — 100% on hardware, no cloud fallback
- **PySceneDetect 0.7 AdaptiveDetector** with 10s cap (v3, F1=91.6%)

### What was deprecated

- ❌ v3's self-built agent loop (`src/agent/`)
- ❌ v3's in-memory store
- ❌ v3's "single machine" assumption
- ❌ v3's Cloudflare-edge hybrid architecture
- ❌ v3's LlamaIndex dependency (replaced by Hermes + Mnemosyne)

### Open questions (carried forward)

See `docs/01_對話與調研紀錄/2026-06-05_開放問題Q01-Q08.md`:

- Q01: Does M1 need to run Hermes locally, or only consume it remotely?
- Q02: Snippet-only embedding vs full-chunk?
- Q03: Tailscale (managed) vs Headscale (self-hosted)?
- Q04: 27B dense vs 35B-A3B MoE as workstation primary?
- Q05: MTP speculative decoding on or off?
- Q06: Q3 vs Q4 quant for the backup LLM?
- Q07: Backup topology — what goes to OneDrive?
- Q08: 100 vs 1000 entries in the eval set?

### Deployment plan (for the next 6-8 weeks)

| Week | Phase | Deliverable |
|---|---|---|
| 1 | Phase 0 | Machines set up, Tailscale mesh live |
| 1-2 | Phase 1 | Ollama + Qdrant + llama.cpp deployed |
| 2-3 | Phase 2 | Indexer pipeline running on M1 |
| 3-4 | Phase 3 | Hermes Agent + 3 skills integrated |
| 4-6 | Phase 4 | Eval set baseline (MRR@10 ≥ 0.6) |
| 6-8 | Phase 5 | Advanced: better embeddings, more skills |

### Risks accepted at this snapshot

- **R07** (backup failure) — Medium; mitigation in Phase 2
- **R13** (8GB RAM headroom) — Low; ~1GB headroom on M1
- **R18** (Qwen3.6 license check pending) — Low; will check before Phase 1
- All other risks: see `docs/02_方案文檔/風險登錄表.md`

### See also

- [`../CHANGELOG.md`](../CHANGELOG.md) — the canonical changelog
- [`../docs/00_index.md`](../docs/00_index.md) — master index
- [`manifest.json`](manifest.json) — SHA-256 of all files at this snapshot
- [`verify.py`](verify.py) — check current repo against this snapshot
- [`README.md`](README.md) — archive overview
