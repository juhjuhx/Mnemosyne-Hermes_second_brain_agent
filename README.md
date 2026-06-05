# Mnemosyne

> **A local-first, privacy-preserving personal AI second brain.** Indexes your notes, photos, videos, and audio into a private, semantically searchable archive on your own hardware. No cloud, no telemetry, no surveillance.

[![Status](https://img.shields.io/badge/status-pre--implementation-yellow)]()
[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![License: CC BY-SA 4.0](https://img.shields.io/badge/docs-CC%20BY--SA%204.0-lightgrey.svg)](LICENSE-DOCS)
[![Privacy: 100% Local](https://img.shields.io/badge/privacy-100%25%20local-success)]()
[![Powered by Hermes Agent](https://img.shields.io/badge/powered%20by-Hermes%20Agent-blueviolet)](https://github.com/NousResearch/hermes-agent)
[![v4 plan](https://img.shields.io/badge/v4%20plan-frozen-blue)]()

---

## What is Mnemosyne?

**Mnemosyne** (μνημοσύνη) is a personal AI second brain that runs **entirely on your own hardware**. It turns the digital artifacts you already have — notes, photos, videos, audio recordings, PDFs, screenshots — into a single, semantically-aware, locally-indexed archive that you (and your AI assistant) can query in natural language.

> No cloud. No SaaS. No data ever leaves your LAN.

It is named after the **Greek goddess of memory**, mother of the nine Muses — and also after the long-term memory backend the system is built on, so "Powered by Mnemosyne" forms a deliberate recursion: **the second brain *is* a memory system**.

### Why this name

- **μνημοσύνη (mnēmosýnē)** = "memory" in ancient Greek
- The goddess Mnemosyne was the mother of the Muses — the source of all inspiration and knowledge
- The project's memory backend is also called Mnemosyne, so the name has built-in continuity
- Short, distinctive; live fork at `github.com/juhjuhx/Mnemosyne-Hermes_second_brain_agent`

---

## Reference hardware

The plan is **parameterized for any similar "small Mac + workstation" pair**. The reference design:

| Machine | Role | Spec |
|---|---|---|
| M1 Air | Perception / NAS / Edge Agent | macOS, 8GB RAM, Metal GPU |
| Workstation | Heavy Inference | Linux, 5800X + 48GB RAM + A770 16GB VRAM, Vulkan |

---

## Stack (all MIT, all local)

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — autonomous agent runtime
- [Ollama](https://ollama.com) (M1, Metal) + [llama.cpp](https://github.com/ggerganov/llama.cpp) (workstation, Vulkan)
- **Gemma 4 E2B** (M1) + **Qwen 3.6 27B-PRISM-DQ** (workstation, with MTP speculative decoding)
- [Mnemosyne](https://github.com/AxDSan/mnemosyne) — long-term memory
- [Qdrant](https://qdrant.tech) — vector store (named vectors: `text_vec(768)` + `image_vec(512)`)
- [Open WebUI](https://github.com/open-webui/open-webui) — chat frontend
- [Tailscale](https://tailscale.com) — private mesh between machines
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) — video slicing (F1 = 91.6%)
- [MCP](https://modelcontextprotocol.io) (Model Context Protocol) — tool/server bus
- 3 example skills ship out of the box: `filesystem-search`, `qdrant-search`, `video-slice`

---

## Three invariants

Mnemosyne will not compromise on these:

1. **Memory never forgotten** — your original files are never modified; the indexer only *suggests* moves.
2. **Local-first** — every byte of compute and storage is on hardware you own.
3. **No surveillance** — no facial recognition, no voice emotion monitoring, no auto-mutation of your archive.

> These three constraints are enforced in code: the indexer rejects `workers > 1`, all services bind to `127.0.0.1`, and the SQLite `suggested_move` field is *advisory only*.

---

## Repository layout

```
mnemosyne/                       (a.k.a. ~/mnemosyne/ when cloned)
├── README.md                    ← you are here
├── LICENSE                      ← MIT for code
├── LICENSE-DOCS                 ← CC BY-SA 4.0 for documentation
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── .gitignore
│
├── docs/
│   ├── 00_index.md              ← master index of every artifact
│   ├── 01_對話與調研紀錄/        ← session logs, research notes (8 files)
│   ├── 02_方案文檔/              ← plans, integration guides, manuals (16 files)
│   ├── 03_架構圖_SVG/            ← 11 hand-crafted SVG architecture diagrams
│   ├── 06_備份與同步/            ← backup & sync strategy + 4 scripts
│   └── 07_更新日誌/              ← phase-end summaries (reserved for use post-deployment)
│
├── src/                         ← all runnable code
│   ├── hermes_skills/           ← 3 example skills (SKILL.md + manifest + src + tests)
│   ├── launchd/                 ← 6 macOS service plists
│   ├── systemd/                 ← 3 Linux service units
│   ├── scripts/                 ← 8 Python + bash glue scripts
│   ├── tailscale/               ← ACL JSON
│   ├── ollama/                  ← Modelfiles
│   └── llama_cpp/               ← build flags & RPC config
│
├── tests/                       ← pytest suites + 100-entry eval set
├── examples/                    ← sample configs (hermes, indexer)
├── .github/                     ← issue/PR templates + CI workflows
└── _archive/                    ← SHA-256-verified snapshots (2026-06-05)
```

---

## Quick start

> The reference hardware (M1 Air + Linux workstation) was offline during v4 planning, so the repo is **complete on paper** and ready to **run as soon as you have both machines in hand**.

1. **Read [`docs/00_index.md`](docs/00_index.md)** — full table of contents.
2. **Read [`docs/02_方案文檔/Phase_0_啟動手冊.md`](docs/02_方案文檔/Phase_0_啟動手冊.md)** — the 1-day bootstrap checklist.
3. **Skim [`docs/02_方案文檔/個人AI第二腦落地方案_v4.md`](docs/02_方案文檔/個人AI第二腦落地方案_v4.md)** — the master plan (27 sections).
4. **Adapt & execute** — every path/port/hostname is parameterized.

---

## v4 design pillars (TL;DR)

1. **Dual-machine split** — M1 = perception/NAS/edge agent; workstation = heavy LLM inference.
2. **Hermes Agent replaces v3's self-built FastAPI agent** — community-supported, MCP-native, skill-driven.
3. **Mnemosyne replaces v3's self-built memory layer** — SQLite-only, BEAM-friendly, 98.9% on LongMem.
4. **Named vectors preserved** — `text_vec(768) + image_vec(512)` in Qdrant (v3 invariant).
5. **Single worker indexer** — v3 invariant, no parallel ingestion.
6. **Memory never forgotten** — original files preserved, index is rebuildable.
7. **Privacy by construction** — `127.0.0.1`-bound services, Tailscale mesh, no cloud, no telemetry.

---

## Status of every component

| Component | Plan | Code | Tested | Notes |
|---|:---:|:---:|:---:|---|
| Tailscale mesh | ✅ | ✅ | ⏳ | Awaiting hardware |
| Ollama on M1 (Metal) | ✅ | ✅ | ⏳ | Awaiting M1 |
| llama.cpp on A770 (Vulkan) | ✅ | ✅ | ⏳ | Awaiting workstation |
| Qdrant single-node | ✅ | ✅ | ⏳ | |
| Mnemosyne integration | ✅ | ✅ | ⏳ | |
| Hermes Agent setup | ✅ | ✅ | ⏳ | |
| Open WebUI link | ✅ | ✅ | ⏳ | |
| 100-entry eval suite | ✅ | ✅ | ⏳ | |
| Skill templates | ✅ | ✅ | ⏳ | 3 example skills included |

Legend: ✅ done · ⏳ pending hardware

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The plan is parameterizable; PRs to add new hardware profiles (e.g. M2/M3, RX 7900, multi-GPU) are very welcome.

**Code**: MIT — see [`LICENSE`](LICENSE)
**Docs**: CC BY-SA 4.0 — see [`LICENSE-DOCS`](LICENSE-DOCS)

---

## License

- All **code** under [`LICENSE`](LICENSE) (MIT)
- All **documentation, diagrams, and eval sets** under [`LICENSE-DOCS`](LICENSE-DOCS) (CC BY-SA 4.0)
- Third-party components retain their own licenses — see the [Component Integration Matrix](docs/02_方案文檔/架構B_開源組件整合表.md).

---

## Acknowledgments

- [Nous Research](https://nousresearch.com) — Hermes Agent, Hermes API
- [AxDSan](https://github.com/AxDSan) — Mnemosyne (the memory backend Mnemosyne is named after)
- [Qdrant](https://qdrant.tech) — vector store
- [Ollama](https://ollama.com) — local LLM serving
- [ggerganov](https://github.com/ggerganov) — llama.cpp
- [Anthropic](https://anthropic.com) — MCP + agentskills.io
- [Open WebUI](https://github.com/open-webui/open-webui) — chat UI
- All the open-source maintainers who make local-first AI possible.

---

*"Memory never forgotten. The original file is the source of truth; the index is a derived view."*
