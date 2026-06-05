# 架構 B 開源組件整合表

> Component-by-component integration matrix for Architecture B (M1 + workstation).
> Every dependency is pinned to a specific version, has a known license,
> and an integration note explaining how we use it.

---

## 1. Hardware

| Component | Spec | Notes |
|---|---|---|
| M1 Air | 8GB RAM, 256GB SSD, Metal | Reference; plan parameterizable |
| Workstation | 5800X, 48GB RAM, A770 16GB VRAM, Vulkan | Reference; plan parameterizable |
| RAID | 24TB ZFS RAID-Z2 | Shared data; mount on both machines |

## 2. Large Language Models

| Model | Version / Quant | Size | License | Where | Why |
|---|---|---|---|---|---|
| `unsloth/gemma-4-e2b-it-GGUF` | Q4_K_XL | 2.5GB | Apache 2.0 | M1 | Best 2B-class 2026 quality; fits 8GB |
| `Qwen/Qwen3.6-1.7B-GGUF` | Q4_K_M | 1.5GB | Apache 2.0 | M1 (backup) | Smaller; faster; fall-back if Gemma fails |
| `Ex0bit/Qwen3.6-27B-PRISM-PRO-DQ` | Q4_K_M | 13.7GB | Apache 2.0 | Workstation | Best 27B with MTP speculative decoding |
| `mudler/Carnice-Qwen3.6-MoE-35B-A3B-APEX-MTP-GGUF` | I-Compact | 17GB | Apache 2.0 | Workstation (backup) | Strongest 35B; fits if `--ctx-size 16384` |

## 3. LLM serving

| Software | Version | License | Where | Integration note |
|---|---|---|---|---|
| Ollama | v0.5.x | MIT | M1 | Serves Gemma 4 E2B + nomic via Metal. Listens on `127.0.0.1:11434`. |
| llama.cpp | b4567+ | MIT | Workstation | Serves Qwen 3.6 27B-PRISM-DQ via Vulkan. Listens on `127.0.0.1:8080`. |
| Vulkan SDK | 1.3.x | MIT / Apache 2.0 | Workstation | Required for llama.cpp Vulkan backend. |

### llama.cpp build flags

```bash
cmake -B build \
  -DGGML_VULKAN=ON \
  -DGGML_NATIVE=ON \
  -DGGML_OPENMP=ON \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 16
```

### llama.cpp server command

```bash
./build/bin/llama-server \
  --model ~/models/Qwen3.6-27B-PRISM-PRO-DQ.Q4_K_M.gguf \
  --speculative-model-draft auto \
  --draft-max 8 \
  --gpu-layers 99 \
  --ctx-size 32768 \
  --port 8080 \
  --host 127.0.0.1 \
  --parallel 4
```

## 4. Agent + memory

| Software | Version | License | Where | Integration note |
|---|---|---|---|---|
| Hermes Agent | v0.x | MIT | M1 | OpenAI-compatible API on `127.0.0.1:8642`. Loads skills from `src/hermes_skills/`. |
| Mnemosyne | v0.x | MIT | M1 | SQLite-only. Adapter via `hermes.memory.MnemosyneAdapter`. |
| MCP (protocol) | 2025-11-25 | (standard) | Both | Anthropic + OpenAI adopted. |
| agentskills.io (spec) | v1 | (standard) | M1 | Skill directory format. |

## 5. Vector store

| Software | Version | License | Where | Integration note |
|---|---|---|---|---|
| Qdrant | v1.16.x | Apache 2.0 | M1 (primary) + workstation (mirror) | Single-node. Named vectors `text_vec(768)+image_vec(512)`. |

### Qdrant collection config

```yaml
# config/second_brain.yaml
collections:
  second_brain:
    vectors:
      text_vec:
        size: 768
        distance: Cosine
      image_vec:
        size: 512
        distance: Cosine
    hnsw_config:
      m: 16
      ef_construct: 100
    quantization_config:
      scalar:
        type: int8
        quantile: 0.99
        always_ram: true
```

## 6. Embeddings

| Model | Size | License | Where | Notes |
|---|---|---|---|---|
| `nomic-embed-text` | 274MB | Apache 2.0 | M1 (Ollama) | Text embeddings, always-on. |
| `BAAI/bge-m3` | 2.2GB | MIT | Workstation | Long-text embeddings, on-demand. |
| `MobileCLIP-S0` (apple/mobileclip) | 100MB | MIT | M1 (ONNX + CoreML) | Image embeddings, always-on. |
| `google/siglip-base-patch16-512` | 200MB | Apache 2.0 | Workstation | Image embeddings, on-demand. |

## 7. Speech-to-text

| Model | Size | License | Where | Notes |
|---|---|---|---|---|
| `whisper.cpp tiny` | 75MB | MIT | M1 | Quick transcription, English-leaning. |
| `faster-whisper large-v3` | 1.5GB | MIT | Workstation | On-demand; better for Chinese. |

## 8. Video processing

| Software | Version | License | Where | Notes |
|---|---|---|---|---|
| PySceneDetect | 0.7 | BSD-3 | M1 | AdaptiveDetector F1=91.6%. |
| ffmpeg | 6.x+ | LGPL 2.1+ | Both | Frame extraction, audio extraction. |

## 9. Frontend

| Software | Version | License | Where | Notes |
|---|---|---|---|---|
| Open WebUI | v0.6.x | MIT | M1 | Connects to Hermes's OpenAI API. PWA mode. |
| Hermes CLI | (bundled with Hermes Agent) | MIT | Both | Terminal access. |

## 10. Network

| Software | Version | License | Where | Notes |
|---|---|---|---|---|
| Tailscale | v1.6x+ | BSD-3 | Both | Mesh VPN. ACL JSON in `src/tailscale/`. |

## 11. Service management

| Component | Where | Config |
|---|---|---|
| launchd | M1 | 5 plists in `src/launchd/` |
| systemd | Workstation | 3 units in `src/systemd/` |

### launchd plists (M1)

| Plist | Service | Port |
|---|---|---|
| `ai.brain.ollama.plist` | Ollama | 11434 |
| `ai.brain.qdrant.plist` | Qdrant | 6333 |
| `ai.brain.indexer.plist` | Indexer | (no port) |
| `ai.brain.hermes.plist` | Hermes Agent | 8642 |
| `ai.brain.tailscaled.plist` | Tailscale | (Tailscale-managed) |

### systemd units (workstation)

| Unit | Service | Port |
|---|---|---|
| `ai-brain-llama-server.service` | llama-server | 8080 |
| `ai-brain-qdrant.service` | Qdrant mirror | 6333 |
| `ai-brain-tailscaled.service` | Tailscale | (Tailscale-managed) |

## 12. Storage layout

| Path (M1) | Path (workstation) | Purpose |
|---|---|---|
| `~/ai-brain/` | `~/ai-brain-station/` | Service home |
| `~/ai-brain/models/` | `~/ai-brain-station/models/` | GGUF models |
| `~/ai-brain/venv/` | `~/ai-brain-station/venv/` | Python venv |
| `~/ai-brain/hermes_config/` | — | Hermes config |
| `~/ai-brain/logs/` | `~/ai-brain-station/logs/` | Service logs |
| `~/ai-brain/snapshots/` | — | Qdrant + Mnemosyne snapshots |
| `/Volumes/RAID/AISecondBrain/` | `/mnt/raid/AISecondBrain/` | Shared data |

## 13. RAID layout

```
/Volumes/RAID/AISecondBrain/   (macOS) or /mnt/raid/AISecondBrain/   (Linux)
├── inbox/                     ← user drops files; indexer watches
├── private/                   ← personal notes
├── public/                    ← shareable content
├── shared/                    ← cross-device scratch
├── media/
│   ├── photos/
│   ├── videos/
│   └── audio/
├── _archive/                  ← moved-after-confirmation files
├── index/                     ← (optional) Qdrant storage on RAID
└── logs/                      ← cross-device log aggregation
```

## 14. Network ports summary

| Port | Service | Bound to | Tailscale ACL |
|---|---|---|---|
| 11434 | Ollama (M1) | 127.0.0.1 | station → m1:11434 allow |
| 8080 | llama-server (workstation) | 127.0.0.1 | m1 → station:8080 allow |
| 6333 | Qdrant (M1) + mirror (workstation) | 127.0.0.1 | m1 ↔ station:6333 allow |
| 8642 | Hermes Agent (M1) | 127.0.0.1 | phone → m1:8642 allow (if direct chat) |
| 3000 | Open WebUI (M1) | 127.0.0.1 | phone → m1:3000 allow |

## 15. Python dependencies (M1, in venv)

```
# requirements.txt (M1)
ollama==0.5.*
qdrant-client==1.16.*
mnemosyne==0.*  # or pip install git+...
mcp==1.*
hermes-agent==0.*
Pillow==10.*
openai-whisper==20240930
scenedetect==0.7.*
fastapi==0.115.*
uvicorn==0.32.*
```

## 16. Python dependencies (workstation, in venv)

```
# requirements.txt (workstation)
llama-cpp-python==0.3.*
qdrant-client==1.16.*
faster-whisper==1.*
flagembedding==1.*
transformers==4.*
torch==2.*
Pillow==10.*
```

## 17. License compatibility

| Our project | Code: MIT | Docs: CC BY-SA 4.0 |
|---|---|---|
| Hermes Agent | MIT ✅ | |
| Mnemosyne | MIT ✅ | |
| Qdrant | Apache 2.0 ✅ | |
| Ollama | MIT ✅ | |
| llama.cpp | MIT ✅ | |
| Gemma 4 | Apache 2.0 ✅ | |
| Qwen 3.6 | Apache 2.0 ✅ | |
| Open WebUI | MIT ✅ | |
| Tailscale | BSD-3 ✅ | |
| PySceneDetect | BSD-3 ✅ | |
| ffmpeg | LGPL 2.1+ ✅ | |
| whisper.cpp | MIT ✅ | |
| MobileCLIP | MIT ✅ | |
| nomic-embed | Apache 2.0 ✅ | |
| BGE-M3 | MIT ✅ | |
| siglip | Apache 2.0 ✅ | |
| MCP (protocol) | (standard) | |
| agentskills.io (spec) | (standard) | |

All dependencies are MIT / Apache 2.0 / BSD — fully compatible with our
MIT (code) and CC BY-SA 4.0 (docs) licenses.

---

## See also

- [v4 master plan §8](個人AI第二腦落地方案_v4.md)
- [Phase 1 部署指南](Phase_1_部署指南.md)
- [Hermes Agent 整合指南](Hermes_Agent_整合指南.md)
