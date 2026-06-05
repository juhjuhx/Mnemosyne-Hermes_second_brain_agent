# 個人 AI 第二腦落地方案 v4

> **Project name**: **Mnemosyne** (μνημοσύνη, the Greek goddess of memory)
> **Version**: 4.0
> **Date**: 2026-06-05
> **Status**: Pre-implementation (reference hardware offline)
> **Audience**: Implementer (you, in 1-6 weeks), future AI agents, contributors

---

## Table of contents

1. [Goals & non-goals](#1-goals--non-goals)
2. [Constraints](#2-constraints)
3. [Decisions (TL;DR)](#3-decisions-tldr)
4. [Reference hardware](#4-reference-hardware)
5. [Directory structure](#5-directory-structure)
6. [Architecture B — dual-machine topology](#6-architecture-b--dual-machine-topology)
7. [Stack at a glance](#7-stack-at-a-glance)
8. [Component integration matrix](#8-component-integration-matrix)
9. [Phase 0 — bootstrap](#9-phase-0--bootstrap)
10. [Phase 1 — service deployment](#10-phase-1--service-deployment)
11. [Phase 2 — indexing pipeline](#11-phase-2--indexing-pipeline)
12. [Phase 3 — Hermes integration](#12-phase-3--hermes-integration)
13. [Phase 4 — evaluation & iteration](#13-phase-4--evaluation--iteration)
14. [Phase 5 — advanced (optional)](#14-phase-5--advanced-optional)
15. [RAM & VRAM budgets](#15-ram--vram-budgets)
16. [Network topology (Tailscale)](#16-network-topology-tailscale)
17. [Backup & recovery](#17-backup--recovery)
18. [Evaluation system (10 metrics)](#18-evaluation-system-10-metrics)
19. [Risk register (20 risks)](#19-risk-register-20-risks)
20. [Skill library (3 example skills)](#20-skill-library-3-example-skills)
21. [Open questions Q01-Q08](#21-open-questions-q01-q08)
22. [Glossary](#22-glossary)
23. [Exit plan](#23-exit-plan)
24. [Output organization (GitHub-ready)](#24-output-organization-github-ready)
25. [Backup & versioning (folder level)](#25-backup--versioning-folder-level)
26. [Research log discipline](#26-research-log-discipline)
27. [6-8 week timeline](#27-6-8-week-timeline)

---

## 1. Goals & non-goals

### Goals

1. **Build a "second brain"** — a system that can answer questions about the
   user's personal media archive (text, images, video, audio) using natural
   language.
2. **Privacy by construction** — 100% local, no cloud, no telemetry. Every
   byte stays on user hardware.
3. **Dual-machine split** — small Mac (M1) handles perception, NAS duties,
   and edge agent; workstation handles heavy LLM inference.
4. **Maintainable** — replaces v3's ~5000-line self-built FastAPI agent with
   the Hermes Agent ecosystem (MCP-native, community-maintained).
5. **Rebuildable** — original files are the source of truth. The index is a
   derived view; it can be regenerated from scratch.
6. **Observable** — every component emits structured logs to a unified
   journal. The user can answer "what did the system do last week?" in
   <5 minutes.

### Non-goals

1. **Multi-user** — single-user system. No ACLs, no per-user isolation.
2. **Multi-tenant** — no SaaS, no shared infrastructure.
3. **Cloud fallback** — no OpenAI/Anthropic/Google APIs. Local-only.
4. **Facial recognition / voice emotion monitoring** — explicit non-goal.
5. **Mobile-first** — phone access is via Open WebUI PWA, not a native app.
6. **24/7 uptime** — M1 sleeps. Workstation sleeps. Both wake on demand.
7. **Real-time** — indexing is batch (on file-add), not streaming.

---

## 2. Constraints

### Hard

- **M1 has 8GB RAM** — peak total service stack must be ≤ 7.5GB.
- **M1 has 256GB SSD** — system + models + index = ~80GB; rest is data.
- **Workstation has 48GB RAM + A770 16GB VRAM** — 27B Q4 fits in VRAM.
- **Both machines on the same LAN**, with Tailscale as overlay mesh.
- **No cloud** — no API keys, no telemetry, no remote debugging.
- **Single worker indexer** — no parallel file ingestion.
- **All services bound to 127.0.0.1** — Tailscale ACL gates who can reach.

### Soft

- Reference hardware may evolve (M1 → M2 Pro 16GB → M3 Max 64GB).
- Workstation GPU may evolve (A770 16GB → RX 7900 24GB → dual-GPU).
- Models may be swapped (27B → 35B-A3B; Gemma 4 E2B → Phi-4 mini).
- Skills may be added/removed.

### Inherited from v3 (read-only reference)

- Named Vectors `text_vec(768) + image_vec(512)` — DO NOT CHANGE.
- 10s video cap — DO NOT CHANGE.
- Single worker queue — DO NOT CHANGE.
- "Memory never forgotten" — DO NOT CHANGE.
- "Never auto-move files" — DO NOT CHANGE.

---

## 3. Decisions (TL;DR)

| Decision | Choice | Alternative considered | Why |
|---|---|---|---|
| Architecture | **B (dual-machine)** | A (M1 alone) | Heavy LLM quality, privacy, future scalability |
| M1 LLM | **Gemma 4 E2B Q4_K_XL** | Qwen 3.6 1.7B, Phi-4 mini | Best 2B-class 2026 quality; fits 8GB |
| Workstation LLM | **Qwen 3.6 27B-PRISM-DQ Q4** | 14B, 35B-A3B, 32B | Fits A770 16GB; MTP speculative decoding |
| Agent framework | **Hermes Agent** | v3 self-built FastAPI | MCP-native, community, agentskills.io |
| Memory backend | **Mnemosyne** | v3 self-built SQLite layer | BEAM/LongMem benchmarks; SQLite-only |
| Vector store | **Qdrant single-node** | Milvus, Weaviate, Chroma | Named vectors, atomic snapshots, no extra deps |
| Skill spec | **agentskills.io** | Custom JSON | Standardized, Anthropic + Hermes native |
| Tool protocol | **MCP** | Custom JSON | Industry standard, OpenAI adopted |
| Frontend | **Open WebUI** | LibreChat, Chatbot UI | 5-min Hermes integration; PWA |
| Network | **Tailscale** | ZeroTier, Nebula, direct WireGuard | Best UX, free for personal |
| Service management | **launchd (M1) / systemd (Linux)** | Docker, supervisord | Native to each OS |
| Embeddings (M1) | **nomic-embed-text** | bge-small, MiniLM | Fast, good quality |
| Vision (M1) | **MobileCLIP S0** | CLIP ViT-B/32 | Smallest CLIP with good quality |
| ASR (M1) | **whisper.cpp tiny** | whisper base, faster-whisper | Fits 8GB |
| Video slicing | **PySceneDetect 0.7 AdaptiveDetector** | TransnetV2, AutoShot | Best F1 (91.6%), 2026 release |

---

## 4. Reference hardware

### M1 Air (8GB / 256GB)

| Component | Spec |
|---|---|
| Model | MacBook Air (M1, 2020) |
| CPU | 8-core (4 perf + 4 eff) |
| GPU | 7-core Apple GPU (Metal) |
| RAM | 8GB unified |
| SSD | 256GB (system + models + index, ~80GB used) |
| OS | macOS 14.x (Sonoma) or 15.x (Sequoia) |
| Network | Wi-Fi 6 (Tailscale mesh) |
| Power | 30W USB-C, 15-20W typical |
| Noise | Fanless |

### Workstation (5800X + 48GB + A770)

| Component | Spec |
|---|---|
| CPU | AMD Ryzen 7 5800X (8C/16T) |
| GPU | Intel Arc A770 16GB (Vulkan) |
| RAM | 48GB DDR4-3600 |
| Storage | 1TB NVMe (system) + 24TB RAID (data) |
| OS | Fedora 41 Workstation / Ubuntu 24.04 LTS |
| Network | 2.5GbE + Wi-Fi 6 |
| Power | 650W PSU, 80-150W typical |
| Noise | Tower with case fans |

### RAID volume (shared data)

| Component | Spec |
|---|---|
| Capacity | 24TB usable (ZFS RAID-Z2) |
| Mount point | `/Volumes/RAID/AISecondBrain/` (macOS) / `/mnt/raid/AISecondBrain/` (Linux) |
| Layout | `inbox/`, `private/`, `public/`, `shared/`, `media/`, `_archive/`, `index/`, `logs/` |

---

## 5. Directory structure

> **Note**: This is the v4 GitHub-ready structure. The original
> `D:\666\第二大腦\` directory contains the v3 plan + reference material
> (read-only). All new artifacts go into `D:\666\第二大腦\Hermes_second_brain_agent_AIIinONE\`.

### Top-level

```
Hermes_second_brain_agent_AIIinONE/   ← THIS repo
├── README.md
├── LICENSE                            (MIT, code)
├── LICENSE-DOCS                       (CC BY-SA 4.0, docs)
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── .gitignore
│
├── docs/
│   ├── 00_index.md
│   ├── 01_對話與調研紀錄/               ← research logs
│   ├── 02_方案文檔/                    ← plans, guides
│   ├── 03_架構圖_SVG/                  ← diagrams
│   ├── 06_備份與同步/
│   └── 07_更新日誌/
│
├── src/
│   ├── hermes_skills/                 ← 3 example skills
│   ├── launchd/                       ← macOS plists
│   ├── systemd/                       ← Linux service units
│   ├── scripts/                       ← Python + bash glue
│   ├── tailscale/                     ← ACLs
│   ├── ollama/                        ← Modelfiles
│   └── llama_cpp/                     ← build flags, RPC config
│
├── tests/                             ← pytest + 100-entry eval set
├── examples/                          ← example configs
├── .github/                           ← CI + issue templates
└── _archive/                          ← versioned snapshots
```

### M1 (post-install, on the actual machine)

```
~/ai-brain/
├── venv/                              ← Python 3.11 venv
├── models/                            ← GGUF models
│   ├── gemma-4-e2b-it.Q4_K_XL.gguf
│   ├── nomic-embed-text/
│   └── mobileclip/
├── scripts/                           ← symlink → repo src/scripts/
├── eval/                              ← symlink → repo tests/
├── launchd/                           ← symlink → repo src/launchd/
├── hermes_config/                     ← Hermes config + skill registry
├── logs/                              ← service logs
└── snapshots/                         ← Qdrant + Mnemosyne snapshots
```

### Workstation (post-install)

```
~/ai-brain-station/
├── venv/
├── llama.cpp/                         ← build dir
├── models/
│   ├── Qwen3.6-27B-PRISM-PRO-DQ.Q4_K_M.gguf
│   ├── bge-m3/
│   └── faster-whisper-large-v3/
├── scripts/                           ← symlink → repo src/scripts/
├── systemd/                           ← symlink → repo src/systemd/
└── logs/
```

### RAID (shared data)

```
/Volumes/RAID/AISecondBrain/   (macOS) or /mnt/raid/AISecondBrain/   (Linux)
├── inbox/                     ← user drops files here; indexer watches
├── private/                   ← personal notes, journals
├── public/                    ← shareable content
├── shared/                    ← cross-device scratch
├── media/
│   ├── photos/
│   ├── videos/
│   └── audio/
├── _archive/                  ← moved-after-confirmation files
├── index/                     ← Qdrant storage (if on RAID) OR symlink
└── logs/                      ← cross-device log aggregation
```

---

## 6. Architecture B — dual-machine topology

```
┌─────────────────────────────────┐         ┌──────────────────────────────────┐
│ M1 Air (8GB)                    │         │ Workstation (48GB + A770 16GB)  │
│                                 │         │                                  │
│  ┌──────────────────────────┐  │         │  ┌────────────────────────────┐  │
│  │ macOS                    │  │         │  │ Fedora 41 / Ubuntu 24.04   │  │
│  └──────────────────────────┘  │         │  └────────────────────────────┘  │
│  ┌──────────────────────────┐  │  HTTP   │  ┌────────────────────────────┐  │
│  │ Ollama :11434            │◄─┼─────────┼──┤ llama-server :8080         │  │
│  │ (Gemma 4 E2B Q4_K_XL)   │  │  Tailscale│  │ (Qwen 3.6 27B-PRISM-DQ)   │  │
│  └──────────────────────────┘  │  mesh   │  └────────────────────────────┘  │
│  ┌──────────────────────────┐  │         │  ┌────────────────────────────┐  │
│  │ Qdrant :6333             │◄─┼─────────┼──┤ Qdrant mirror :6333        │  │
│  │ (named vectors)          │  │         │  │ (read-only)                │  │
│  └──────────────────────────┘  │         │  └────────────────────────────┘  │
│  ┌──────────────────────────┐  │         │  ┌────────────────────────────┐  │
│  │ Mnemosyne                │  │         │  │ (none — M1 hosts)          │  │
│  │ (SQLite only)            │  │         │  │                            │  │
│  └──────────────────────────┘  │         │  └────────────────────────────┘  │
│  ┌──────────────────────────┐  │         │  ┌────────────────────────────┐  │
│  │ Hermes Agent :8642       │  │         │  │ (faster-whisper large-v3   │  │
│  │ (CLI + API)              │  │         │  │  on-demand)                │  │
│  └──────────────────────────┘  │         │  └────────────────────────────┘  │
│  ┌──────────────────────────┐  │         │  ┌────────────────────────────┐  │
│  │ Open WebUI :3000         │  │         │  │ (BGE-M3 embeddings         │  │
│  │ (chat UI)                │  │         │  │  on-demand)                │  │
│  └──────────────────────────┘  │         │  └────────────────────────────┘  │
│  ┌──────────────────────────┐  │         │                                  │
│  │ Indexer worker (1)       │  │         │  ┌────────────────────────────┐  │
│  │ watches inbox/           │  │         │  │ (no indexer — M1 is source)│  │
│  └──────────────────────────┘  │         │  └────────────────────────────┘  │
│           127.0.0.1 only        │         │           127.0.0.1 only        │
│           Tailscale ACL         │         │           Tailscale ACL         │
└─────────────────────────────────┘         └──────────────────────────────────┘
```

### Request flow (typical user query)

```
User → Open WebUI (browser, Tailscale)
  └─→ Hermes Agent (M1, :8642)
       ├─→ Mnemosyne.retrieve(query)         ← SQLite + Qdrant
       ├─→ Ollama (M1, Gemma 4 E2B)          ← if "easy" task
       │     └─→ response
       └─→ llama-server (workstation, Qwen 3.6 27B)  ← if "hard" task
             └─→ response
       └─→ Mnemosyne.record(conversation)    ← write to SQLite + Qdrant
```

### File ingestion flow

```
User → drops file in /Volumes/RAID/AISecondBrain/inbox/
  └─→ Indexer worker (M1, single-threaded)
       ├─→ ffprobe → detect type, duration, codec
       ├─→ chunking (text: by paragraph; video: PySceneDetect ≤10s; audio: 30s)
       ├─→ embedding (M1 nomic; workstation BGE-M3 for long text)
       ├─→ Qdrant.upsert(point, vectors=text_vec+image_vec, payload)
       └─→ SQLite (files.db) record (file_id, path, hash, mtime)
       └─→ user → "✅ indexed: <filepath> (N chunks)"
```

---

## 7. Stack at a glance

> **For pinned versions, see [`架構B_開源組件整合表.md`](架構B_開源組件整合表.md).**

| Layer | M1 | Workstation |
|---|---|---|
| OS | macOS 14+ | Fedora 41 / Ubuntu 24.04 |
| LLM server | Ollama v0.5.x | llama.cpp b4567+ |
| Main LLM | Gemma 4 E2B Q4_K_XL | Qwen 3.6 27B-PRISM-DQ Q4 |
| Backup LLM | Qwen 3.6 1.7B | Qwen 3.6 35B-A3B APEX I-Compact |
| Agent | Hermes Agent v0.x | (connects to M1) |
| Memory | Mnemosyne v0.x (SQLite) | (reads from M1) |
| Vector store | Qdrant v1.16 | (mirrors from M1) |
| Text embed (always-on) | nomic-embed-text | (calls M1) |
| Text embed (on-demand) | — | BAAI/bge-m3 |
| Image embed | MobileCLIP S0 | siglip-base-512 (on-demand) |
| ASR (always-on) | whisper.cpp tiny | (calls M1) |
| ASR (on-demand) | — | faster-whisper large-v3 |
| Video slicing | PySceneDetect 0.7 | (M1) |
| Frontend | Open WebUI v0.6.x | (browser to M1) |
| Service mgmt | launchd | systemd |
| Network | Tailscale | Tailscale |

---

## 8. Component integration matrix

> Full table with version pins, license, and integration notes:
> [`架構B_開源組件整合表.md`](架構B_開源組件整合表.md)

---

## 9. Phase 0 — bootstrap

> **Goal**: Both machines have Tailscale + Python + Git + Docker (optional) installed and can talk to each other.

**Duration**: 1 day (when hardware is available)

**Deliverables**:
- Tailscale installed on both machines, both nodes visible
- Magic DNS resolves `m1` and `station`
- `ping m1` from workstation and vice versa
- Python 3.11 venv created on both
- `git clone` of this repo on both
- RAID volume mounted on both

**Detailed checklist**: [`Phase_0_啟動手冊.md`](Phase_0_啟動手冊.md)

---

## 10. Phase 1 — service deployment

> **Goal**: All services running and bound to 127.0.0.1; smoke tests pass.

**Duration**: 2-3 days

**Deliverables**:
- Ollama + Gemma 4 E2B running on M1 (`curl localhost:11434/api/tags` lists it)
- llama.cpp + Qwen 3.6 27B-PRISM-DQ running on workstation
- Qdrant single-node running on M1, named vectors configured
- Mnemosyne adapter initialized on M1
- All services auto-start on boot (launchd / systemd)
- All services survive reboot

**Detailed guide**: [`Phase_1_部署指南.md`](Phase_1_部署指南.md)

---

## 11. Phase 2 — indexing pipeline

> **Goal**: A file dropped in `inbox/` is processed end-to-end and appears in Qdrant.

**Duration**: 3-4 days

**Deliverables**:
- File watcher (FSEvents on macOS, inotify on Linux) on M1
- Single worker queue (no parallel ingestion)
- Chunking strategies for text, image, video, audio
- Embedding calls (nomic for text, MobileCLIP for images)
- Qdrant upsert with named vectors
- SQLite (files.db) metadata record
- "✅ indexed" reply to user via Hermes

**Detailed guide**: [`Phase_2_索引流水線指南.md`](Phase_2_索引流水線指南.md)

---

## 12. Phase 3 — Hermes integration

> **Goal**: User can chat via Open WebUI; queries are answered with proper tool use; 3 example skills are loadable.

**Duration**: 5-7 days

**Deliverables**:
- Hermes Agent running on M1 (default per Q01)
- 3 example skills installed and tested:
  - `qdrant-search` (vector retrieval)
  - `filesystem-search` (filename + metadata search)
  - `video-slice` (PySceneDetect wrapper)
- Open WebUI connected to Hermes's OpenAI-compatible API
- PWA mode enabled
- All MCP servers smoke-tested

**Detailed guide**: [`Phase_3_Hermes整合指南.md`](Phase_3_Hermes整合指南.md)
**Skill library**: [`Hermes_Skill_範本庫.md`](Hermes_Skill_範本庫.md)

---

## 13. Phase 4 — evaluation & iteration

> **Goal**: 100-eval suite runs to completion; metrics in green; ralph-watchdog loop works.

**Duration**: Ongoing (1-2 days initial setup, then continuous)

**Deliverables**:
- 100-entry eval set with ground truth: [`評估測試集_v2.md`](評估測試集_v2.md)
- 10-metric evaluation system: [`Phase_4_評估與回饋指南.md`](Phase_4_評估與回饋指南.md)
- ralph-watchdog loop (eval → detect regression → fix → re-eval)
- Monthly re-eval cadence

---

## 14. Phase 5 — advanced (optional)

> **Goal**: Push the system beyond the v4 baseline.

**Duration**: Month 2+ (after v4 stable)

**Optional upgrades**:
- **llama.cpp RPC split**: offload some layers to M1, keep most on workstation
- **KTransformers**: MoE-layer offload for the 35B-A3B
- **Graphiti**: Knowledge-graph layer on top of Mnemosyne
- **Litestream**: streaming replication for Mnemosyne SQLite
- **Headscale**: self-hosted Tailscale control for zero-cloud

**Detailed guide**: [`Phase_5_進階路線指南.md`](Phase_5_進階路線指南.md)

---

## 15. RAM & VRAM budgets

### M1 (8GB total) — peak load

| Process | RAM | Notes |
|---|---:|---|
| macOS | 2,500 MB | wired + active |
| Ollama (Gemma 4 E2B Q4_K_XL) | 2,500 MB | resident |
| nomic-embed-text (in Ollama) | 300 MB | resident |
| Hermes Agent | 500 MB | |
| Qdrant | 50 MB | small collection |
| Mnemosyne (SQLite) | 20 MB | |
| Indexer (on-demand) | 500 MB | only during ingest |
| Open WebUI | 200 MB | |
| Whisper tiny (on-demand) | 400 MB | only when transcribing |
| **Peak total** | **~6,970 MB** | |
| **Headroom** | **~1,030 MB** | |

### Workstation (48GB total) — peak load

| Process | RAM | VRAM | Notes |
|---|---:|---:|---|
| Fedora 41 / Ubuntu 24.04 | 4,000 MB | — | desktop + system |
| llama-server (27B Q4 in A770) | 500 MB | 13,700 MB | MTP head bundled |
| KV cache | — | 2,300 MB | ctx-size 32768 |
| faster-whisper large-v3 (on-demand) | 3,000 MB | — | only when transcribing |
| BGE-M3 (on-demand) | 2,000 MB | — | only when embedding long text |
| siglip-base-512 (on-demand) | 500 MB | — | only when embedding images |
| Qdrant mirror | 1,000 MB | — | |
| **Peak total** | **~11,000 MB** | **~16,000 MB** | |
| **Headroom** | **~37,000 MB** | **~0 MB** | (full VRAM, intentional) |

---

## 16. Network topology (Tailscale)

```
Tailscale mesh
├── m1         100.x.x.x   (Mac, Tailscale IP)
├── station    100.y.y.y   (Linux workstation, Tailscale IP)
└── phone      100.z.z.z   (iOS / Android, optional)

Magic DNS:
  m1.tail-xxxx.ts.net → 100.x.x.x
  station.tail-xxxx.ts.net → 100.y.y.y

ACLs (Tailscale JSON in src/tailscale/):
  - m1 → station: allow :8080 (llama-server), :6333 (Qdrant)
  - station → m1: allow :11434 (Ollama), :8642 (Hermes), :6333 (Qdrant)
  - phone → m1: allow :3000 (Open WebUI)
  - all → all: deny
```

**Full ACL config**: [`Tailscale_私網設定指南.md`](Tailscale_私網設定指南.md)

---

## 17. Backup & recovery

> **Strategy**: every night, snapshot Qdrant + Mnemosyne SQLite to RAID;
> weekly, mirror to second drive; monthly, archive to offline cold storage.

```
Nightly (cron 03:00):
  1. Qdrant.create_snapshot("second_brain")
  2. sqlite3 mnemosyne.db ".backup .../2026-06-05.db"
  3. Verify: load snapshot into test container
  4. Tar + zstd to /mnt/raid/_backups/2026-06-05/

Weekly (Sunday 04:00):
  1. rsync /mnt/raid/_backups/ to /mnt/backup-drive/_backups/

Monthly (1st of month):
  1. Copy to offline USB drive (manual step, monthly reminder)
  2. Verify offline restore (drill)
```

**Detailed playbook**: [`06_備份與同步/同步策略.md`](../06_備份與同步/同步策略.md)

---

## 18. Evaluation system (10 metrics)

> **Full spec**: [`Phase_4_評估與回饋指南.md`](Phase_4_評估與回饋指南.md)

| # | Metric | What it measures | Target |
|---|---|---|---|
| 1 | MRR@10 | Mean Reciprocal Rank of correct doc in top-10 | ≥ 0.85 |
| 2 | Recall@10 | Fraction of relevant docs in top-10 | ≥ 0.80 |
| 3 | nDCG@10 | Normalized Discounted Cumulative Gain | ≥ 0.85 |
| 4 | Faithfulness | LLM answer grounded in retrieved docs | ≥ 0.90 |
| 5 | Answer relevance | Answer addresses user query | ≥ 0.90 |
| 6 | Tool-call accuracy | Hermes picks the right tool | ≥ 0.95 |
| 7 | Latency P50 | End-to-end query time | ≤ 3s (M1 easy), ≤ 8s (workstation hard) |
| 8 | Latency P95 | Tail latency | ≤ 10s (M1), ≤ 20s (workstation) |
| 9 | Index throughput | Files indexed per hour | ≥ 50/h |
| 10 | Cost | LLM tokens × electricity | (monitored, no target) |

---

## 19. Risk register (20 risks)

> **Full table with owners and status**: [`風險登錄表.md`](風險登錄表.md)
> **Research-time notes**: [`../01_對話與調研紀錄/2026-06-05_風險登錄.md`](../01_對話與調研紀錄/2026-06-05_風險登錄.md)

| # | Risk | P × I |
|---|---|---|
| R01 | M1 RAM exceeds 7.5GB during indexing | M × H |
| R02 | Workstation VRAM exhausts during 27B inference | L × H |
| R03 | Ollama on M1 hangs after sleep/wake | M × M |
| R04 | llama-server on A770 OOM-killed by system | L × H |
| R05 | Qdrant snapshot fails silently | L × M |
| R06 | Hermes Agent skill registry lost on restart | M × M |
| R07 | Mnemosyne SQLite grows unbounded | M × M |
| R08 | Tailscale mesh drops mid-session | L × M |
| R09 | Tailscale ACL misconfig exposes port publicly | L × H |
| R10 | MobileCLIP fails on non-square images | M × L |
| R11 | Whisper tiny mis-transcribes Chinese audio | M × M |
| R12 | Indexer falls behind (>100 files/day backlog) | M × M |
| R13 | Eval set has ground-truth errors | M × H |
| R14 | 27B PRISM-DQ MTP head degrades quality on Chinese | M × M |
| R15 | 35B-A3B APEX doesn't fit 16GB VRAM | M × M |
| R16 | Open WebUI PWA breaks after macOS update | L × L |
| R17 | Mac Tailscale IP changes after Wi-Fi roam | L × L |
| R18 | Hermes hallucinating tool args | M × M |
| R19 | ralph-watchdog loop infinite | L × H |
| R20 | Backup RAID drive fails | L × H |

---

## 20. Skill library (3 example skills)

> **Full templates**: [`Hermes_Skill_範本庫.md`](Hermes_Skill_範本庫.md) + `src/hermes_skills/`

| Skill | Purpose | MCP tools |
|---|---|---|
| `qdrant-search` | Vector search over Qdrant | `search`, `get`, `list_collections` |
| `filesystem-search` | Find files by name, date, tag | `find`, `stat`, `tag` |
| `video-slice` | Split video into ≤10s segments | `slice`, `keyframes`, `transcribe` |

Each skill follows the `agentskills.io` spec:
- `SKILL.md` — frontmatter + instructions
- `manifest.json` — MCP server config
- `tests.py` — pytest
- `README.md` — quick example

---

## 21. Open questions Q01-Q08

> **Full notes**: [`../01_對話與調研紀錄/2026-06-05_開放問題Q01-Q08.md`](../01_對話與調研紀錄/2026-06-05_開放問題Q01-Q08.md)

| Q | Summary | Default | Resolve in |
|---|---|---|---|
| Q01 | Does M1 run Hermes or just connect? | M1 runs | Phase 3 |
| Q02 | Snippet vs full-text from `mcp-filesystem`? | Auto by size | Phase 3 |
| Q03 | Tailscale vs Headscale? | Tailscale hosted | Phase 0 |
| Q04 | Swap 27B PRISM for 35B-A3B? | Benchmark first | Phase 4 |
| Q05 | Does MTP head help or hurt? | Always-on | Phase 4 |
| Q06 | Smaller quant for Gemma 4 E2B? | Q4_K_XL | Phase 4 |
| Q07 | Mnemosyne backup topology? | Single nightly snapshot | Phase 5 |
| Q08 | Eval set size: 100 vs 1000? | 100 | Phase 4 |

---

## 22. Glossary

| Term | Meaning |
|---|---|
| **Second brain** | A personal knowledge system that augments human memory. See [`個人AI第二腦完整方法論.md`](../../個人AI第二腦完整方法論.md) for the theoretical foundation. |
| **Hermes Agent** | The agent runtime (NousResearch/hermes-agent) that replaces v3's self-built FastAPI agent. |
| **Mnemosyne** | The memory layer (AxDSan/mnemosyne) that replaces v3's self-built memory. |
| **MCP** | Model Context Protocol — Anthropic's tool protocol. Standardized. |
| **agentskills.io** | Skill directory format. Frontmatter + body + manifest. |
| **Named vectors** | Qdrant feature: a single point can have multiple named vector fields. We use `text_vec(768)` + `image_vec(512)`. |
| **PRISM-DQ** | A quant format by Ex0bit that bundles a draft head (MTP) for self-speculative decoding. |
| **MTP head** | Multi-Token Prediction head. Used for self-speculative decoding. |
| **AdaptiveDetector** | PySceneDetect's best scene detector (F1=91.6%). |
| **ralph-watchdog** | An eval-driven iteration loop. Runs eval, detects regression, fixes, re-runs. |
| **Tailscale** | WireGuard-based mesh VPN. Provides encrypted private networking. |
| **v3 invariant** | A property from v3 that must not be broken in v4. See AGENTS.md for the list. |

---

## 23. Exit plan

If the project is abandoned or fails:

1. **Stop services** — `launchctl unload` (M1) + `systemctl stop` (workstation).
2. **Take final snapshot** — Qdrant + Mnemosyne to `_archive/exit-YYYY-MM-DD/`.
3. **Export eval set + metrics** — `tests/eval_v2_100.md` + last 3 months of metrics.
4. **Tag the repo** — `git tag v4-final`.
5. **Document lessons learned** — add to `docs/07_更新日誌/EXIT_NOTES.md`.
6. **Archive data** — RAID snapshot to offline USB.

Re-entry is possible at any point by re-running Phase 0-1.

---

## 24. Output organization (GitHub-ready)

> **All artifacts** (this plan, sub-plans, code, diagrams, tests) live in
> `D:\666\第二大腦\Hermes_second_brain_agent_AIIinONE\`. The original
> `D:\666\第二大腦\` is **read-only reference material** from v1-v3.

### Folder ↔ phase mapping

| Folder | Phase | Purpose |
|---|---|---|
| `docs/01_對話與調研紀錄/` | (pre-Phase 0) | Research logs |
| `docs/02_方案文檔/` | All | This file + 11 sub-docs |
| `docs/03_架構圖_SVG/` | All | 8-10 SVG diagrams |
| `src/hermes_skills/` | Phase 3 | 3 example skills |
| `src/launchd/`, `src/systemd/` | Phase 1 | Service units |
| `src/scripts/` | Phase 1-4 | Glue code |
| `tests/` | Phase 4 | Eval set + pytest |
| `docs/06_備份與同步/` | Phase 1+ | Backup strategy |
| `examples/` | Phase 0-3 | Working examples |
| `.github/` | (CI) | Issue templates, workflows |
| `_archive/` | (always) | Versioned snapshots |

---

## 25. Backup & versioning (folder level)

> **Strategy**: every file write triggers a `_archive/YYYY-MM-DD-HHMM/`
> snapshot. Every phase completion triggers a full mirror to
> `D:\666\第二大腦\_archive\Hermes_second_brain_agent_AIIinONE\`.
> Optional OneDrive sync (opt-in via `06_備份與同步/sync_onedrive.sh`).

### Snapshot script

```bash
# scripts/snapshot.sh
TS=$(date +%Y-%m-%d-%H%M)
SOURCE="${1:?usage: $0 <source_dir>}"
DEST="${2:-_archive/$TS}"
mkdir -p "$DEST"
rsync -a --delete "$SOURCE/" "$DEST/"
echo "[$TS] snapshot → $DEST"
```

### Mirror to RAID

```bash
# 06_備份與同步/sync_raid.sh
TS=$(date +%Y-%m-%d)
rsync -a --delete \
  "D:/666/第二大腦/Hermes_second_brain_agent_AIIinONE/" \
  "/mnt/d/666/第二大腦/_archive/Hermes_second_brain_agent_AIIinONE/$TS/"
echo "[$TS] mirrored to RAID"
```

### CHANGELOG discipline

Every meaningful change goes to `CHANGELOG.md` under `[Unreleased]`:

```markdown
## [Unreleased]

### Added
- 2026-06-05: Initial v4 plan (this document)
- 2026-06-05: 3 example skills (filesystem, qdrant, video-slice)
- 2026-06-05: 100-entry eval set

### Changed
- 2026-06-05: Replaced v3 self-built FastAPI with Hermes Agent

### Fixed
- (none)

### Deprecated
- 2026-06-05: v3 `AI第二腦實作指南.md` is now read-only reference
```

---

## 26. Research log discipline

> **Rule**: every web search, every "why did we pick this", every v3 → v4
> decision must be recorded in `docs/01_對話與調研紀錄/`.

### Format

Each research note is a single markdown file with this structure:

```markdown
# YYYY-MM-DD <topic>

## Question
<the question that triggered the research>

## Hypothesis
<initial assumption>

## Web searches
- query 1 → result, source, confidence
- query 2 → ...

## Codebase check
- file 1, line N → ...
- file 2 → ...

## Decision
<what was chosen + why>

## Invariants checked
- [ ] Named Vectors preserved
- [ ] Single worker preserved
- [ ] ...

## Cross-references
- [other doc]
```

This is enforced by hand-crafted SVG conventions in `CONTRIBUTING.md`
plus the agent guidance in `/AGENTS.md`. The 11 SVGs in
`docs/03_架構圖_SVG/` are hand-edited (the `baoyu-diagram` skill was
loaded but not used).

---

## 27. 6-8 week timeline

> **Assumes** both machines available, user has 1-2h/day to commit.

| Week | Phase | Goal | Key milestone |
|---|---|---|---|
| 1 | Phase 0 | Bootstrap | Tailscale up; both machines reachable; repo cloned |
| 2 | Phase 1 | Service deployment | All services running and bound to 127.0.0.1 |
| 3 | Phase 1-2 | Indexing pipeline | 10 test files indexed end-to-end |
| 4 | Phase 2-3 | Hermes integration | First chat reply from Open WebUI |
| 5 | Phase 3 | Skills | All 3 example skills loadable + smoke-tested |
| 6 | Phase 4 | Eval | 100-eval suite runs; metrics captured |
| 7 | Phase 4 | Iteration | First regression caught by ralph-watchdog |
| 8 | Phase 5+ | Advanced (optional) | llama.cpp RPC split evaluated |

---

*End of v4 master plan.*

See [`00_index.md`](../00_index.md) for navigation. See
[`../01_對話與調研紀錄/`](../01_對話與調研紀錄/) for the "why" behind every decision.
