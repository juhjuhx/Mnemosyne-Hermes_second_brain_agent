# AGENTS.md — Mnemosyne v4 (conceptual)

> **Project name**: **Mnemosyne** (a personal AI second brain)
>
> **Two entry points** — read both:
>
> 1. **[`/AGENTS.md`](../../../AGENTS.md)** — *operational*: exact commands,
>    CI state, gotchas, workflow. **Read this first** for any code change.
> 2. **This file** — *conceptual*: why v4, the 7 invariants, hardware, stack,
>    reading order, and project history.
>
> This file is the canonical entry point for **architectural context**.
> Keep it stable; it is the long-form complement to the root `AGENTS.md`.

---

## What this project is

A **privacy-first, local-only, dual-machine personal AI second brain** called
**Mnemosyne**, built on the Hermes Agent ecosystem. Runs entirely on
user-owned hardware. No cloud, no SaaS, no telemetry.

**Reference hardware**:

| Machine | Role | Spec |
|---|---|---|
| **M1 Air** | Perception / NAS / Edge Agent / Hermes host | 8GB RAM, 256GB SSD, Metal GPU, macOS 14+ |
| **Workstation** | Heavy inference | 5800X, 48GB RAM, A770 16GB, Linux (Fedora 41 / Ubuntu 24.04) |

---

## 7 unbreakable invariants (DO NOT VIOLATE)

These are the v3 invariants, confirmed for v4. If a future change appears to
break one, **stop and ask the user** before proceeding.

1. **Named Vectors in Qdrant** must remain `text_vec(768) + image_vec(512)`.
   Changing dimensionality requires re-indexing the entire archive.
2. **Single worker indexer** — no parallel ingestion. The queue is one
   consumer, one file at a time. Parallelism is OK at the *embedding* step
   (one file → 10 chunks → 10 embed calls in batch), NOT at the *file* step.
3. **Memory never forgotten** — original files are the source of truth.
   The Qdrant + Mnemosyne + SQLite index is a *derived view* and is rebuildable
   from the original files. If the index is wrong, fix the index; never
   delete or move the source.
4. **Never auto-move files** — the system **suggests** file moves ("This looks
   like a 'private' file, move it?") but never moves anything without
   explicit user approval.
5. **No facial / voice emotion monitoring** — biometric identification is
   out of scope by design. Speech-to-text is fine. Emotion inference is not.
6. **Local-first AI only** — no cloud LLM, no cloud embedding, no cloud STT.
   Network traffic is limited to Tailscale mesh + LAN.
7. **8GB RAM is a hard limit on M1** — the entire M1 service stack
   (macOS + Ollama/Gemma + Hermes + Qdrant + Indexer) must fit in 7.5GB peak.

---

## Stack at a glance

| Layer | M1 | Workstation |
|---|---|---|
| **OS** | macOS 14+ | Linux (Fedora 41 / Ubuntu 24.04) |
| **LLM server** | Ollama (Metal) | llama.cpp (Vulkan) |
| **Main LLM** | `unsloth/gemma-4-e2b-it-GGUF` Q4_K_XL | `Ex0bit/Qwen3.6-27B-PRISM-PRO-DQ` Q4 |
| **Backup LLM** | `Qwen 3.6 1.7B GGUF` | `mudler/Carnice-Qwen3.6-MoE-35B-A3B-APEX-MTP-GGUF` I-Compact |
| **Agent** | Hermes Agent (NousResearch) | (workstation connects to M1's Hermes) |
| **Memory** | Mnemosyne (SQLite) + Qdrant | (workstation mirrors Qdrant) |
| **Embeddings** | nomic-embed-text | BAAI/bge-m3 (on-demand) |
| **Vision** | MobileCLIP S0 (ONNX + CoreML) | siglip-base-512 (on-demand) |
| **ASR** | whisper.cpp tiny | faster-whisper large-v3 (on-demand) |
| **Frontend** | Open WebUI | (browser accesses M1's Open WebUI) |
| **Network** | Tailscale | Tailscale |
| **Service mgmt** | launchd | systemd |

---

## Repository layout (where to find what)

```
D:\666\第二大腦\Hermes_second_brain_agent_AIIinONE\
├── README.md                                          ← landing page
├── LICENSE, LICENSE-DOCS, CHANGELOG.md, CONTRIBUTING.md
├── docs/
│   ├── 00_index.md                                    ← master index
│   ├── 01_對話與調研紀錄/                              ← research logs (READ FIRST)
│   ├── 02_方案文檔/                                    ← this folder
│   ├── 03_架構圖_SVG/                                  ← diagrams
│   ├── 06_備份與同步/
│   └── 07_更新日誌/
├── src/
│   ├── hermes_skills/                                 ← 3 example skills
│   ├── launchd/                                       ← M1 services
│   ├── systemd/                                       ← workstation services
│   ├── scripts/                                       ← Python + bash glue
│   ├── tailscale/                                     ← ACL configs
│   ├── ollama/                                        ← Modelfiles
│   └── llama_cpp/                                     ← build flags + RPC config
├── tests/
├── examples/
├── .github/
└── _archive/
```

---

## Reading order (recommended for new AI agents / contributors)

1. **This file** (`AGENTS.md`)
2. **Why v4** — `docs/01_對話與調研紀錄/2026-06-05_調研思考鏈.md`
3. **Master plan** — `docs/02_方案文檔/個人AI第二腦落地方案_v4.md`
4. **Day 1** — `docs/02_方案文檔/Phase_0_啟動手冊.md`
5. **Diagrams** — `docs/03_架構圖_SVG/00_雙機拓樸圖.svg`
6. **v3 history** — `D:\666\第二大腦\個人AI第二腦落地方案_v3.md` (read-only, 9 known errors)
7. **Methodology** — `D:\666\第二大腦\個人AI第二腦完整方法論.md` (read-only)

---

## How to work on this project

### If you are an AI agent

1. Read the 7 invariants above. If your task seems to violate one, **stop**.
2. Read the master plan §1-3 (Goals, Constraints, Decisions) before doing anything.
3. For code: edit files under `src/` and `tests/`. Run `pytest tests/` before claiming done.
4. For docs: edit files under `docs/`. Cross-reference with `docs/01_對話與調研紀錄/` for context.
5. For diagrams: edit SVG files under `docs/03_架構圖_SVG/` directly.
   The 11 diagrams are **hand-crafted** (the `baoyu-diagram` skill was
   loaded but not used); do not invoke the skill to "regenerate" them.
6. For state changes (resolved Q, new risk, etc.): update `CHANGELOG.md`.
7. When in doubt: ask the user. The cost of a clarifying question << cost of breaking an invariant.

### If you are a human contributor

See `CONTRIBUTING.md` for:
- Code style (ruff + mypy)
- Commit message convention (Conventional Commits)
- PR template (must check all 5 invariants)
- License (**AGPL-3.0** for code, CC BY-SA 4.0 for docs)

### If you are future-me

Welcome back. Read the CHANGELOG to see what changed since you left. The 7
invariants are unchanged. The hardware is unchanged. Most likely you are
returning to **Phase 4 (eval & iteration)** or **Phase 5 (advanced)**.

---

## Open questions (Q01-Q08)

See `docs/01_對話與調研紀錄/2026-06-05_開放問題Q01-Q08.md` for the full list.
Each question has a default and a phase in which it should be resolved.

---

## Known v3 errors

The v3 plan (`D:\666\第二大腦\個人AI第二腦落地方案_v3.md`) is **read-only
reference**. The v3 implementation guide (`AI第二腦實作指南.md`) has
**9 known errors** documented in `個人AI第二腦完整方法論.md`. Do not copy
v3 code without diffing against these notes first.

---

## Communication language

All user-facing text is **Traditional Chinese (繁體中文)**.
All code, identifiers, comments, and CLI strings are **English**.
Documentation is bilingual (Chinese for prose, English for technical terms).

---

## License reminder

- Code: **AGPL-3.0** — see [`LICENSE`](../../LICENSE) (FSF AGPL v3 text)
- Docs: CC BY-SA 4.0 — see [`LICENSE-DOCS`](../../LICENSE-DOCS)
- Third-party: see `架構B_開源組件整合表.md` for upstream licenses
- AGPL-3.0 implication: if Mnemosyne is ever offered as a network
  service, Section 13 requires offering Corresponding Source to all
  users interacting with it remotely. This is intentional.

> If a `manifest.json` in a skill still shows `"license": "MIT"`, that
> is a stale v4-freeze value. The root `LICENSE` is authoritative.

---

*"Memory never forgotten. The original file is the source of truth; the index is a derived view."*
