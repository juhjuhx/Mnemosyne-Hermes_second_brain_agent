# Phase 5 進階路線指南 — Advanced (Optional)

> **Goal**: Push the system beyond the v4 baseline.
> **Duration**: Month 2+ (after v4 stable)
> **Status**: Optional. Don't do these until v4 is rock solid.

---

## 5.1 llama.cpp RPC split (distributed inference)

**Problem**: Qwen 3.6 27B Q4 = 13.7GB. A770 16GB has 2.3GB to spare. If we
want a 35B or 70B model, we need to offload some layers to a second GPU
or to system RAM.

**Solution**: llama.cpp RPC server runs on the offload target, accepts
layer requests from the main llama-server.

### Architecture

```
M1 (RPC server, port 50052)
  └─→ hosts some layers (e.g. 0-19 of 47)
       uses Metal + 8GB unified RAM

Workstation (main llama-server, port 8080)
  └─→ hosts the rest (20-46)
       uses Vulkan A770 16GB
```

### Setup

```bash
# On M1: build llama.cpp with RPC
cd ~/ai-brain-station/llama.cpp
cmake -B build-rpc -DGGML_METAL=ON -DLLAMA_BUILD_RPC=ON
cmake --build build-rpc --config Release -j 8

# Start RPC server
./build-rpc/bin/rpc-server -H 127.0.0.1 -p 50052

# On workstation: tell llama-server to use the RPC backend
./build/bin/llama-server \
  --model ~/models/Qwen3.6-70B-PRISM-PRO-DQ.Q4_K_M.gguf \
  --rpc 127.0.0.1:50052 \  # m1.tail-xxxx.ts.net
  --gpu-layers 30 \
  --ctx-size 32768 \
  --port 8080 \
  --host 127.0.0.1
```

### Latency cost

- 1ms LAN latency × N RPC round-trips
- For Qwen 3.6 27B with 20 layers offloaded: ~20ms per token
- Acceptable for most queries

### When to use

- Want to run 35B-A3B APEX or larger
- Workstation GPU is the bottleneck
- Have ~50ms latency budget to spare

## 5.2 KTransformers (MoE-layer offload)

**Problem**: Qwen 3.6 35B-A3B (MoE) has 35B total params but only 3B active
per token. Most layers are experts that aren't always used.

**Solution**: KTransformers keeps active layers in VRAM, offloads inactive
experts to system RAM or NVMe.

### Setup (complex; see KTransformers repo)

```bash
# Workstation
pip install ktransformers

# Config
cat > ktransformers.yaml <<'EOF'
model: ~/models/Carnice-Qwen3.6-MoE-35B-A3B-APEX-MTP-GGUF-I-Compact.gguf
backend: vulkan
active_layers_in_vram: 28
inactive_experts_offload: cpu
cpu_memory_budget_gb: 32
EOF

# Run
ktransformers serve --config ktransformers.yaml
```

### When to use

- Want 35B-A3B quality but only have 16GB VRAM
- Latency can be ~1.5x slower than 27B PRISM

## 5.3 Graphiti (knowledge graph)

**Problem**: Mnemosyne is a memory *layer*, not a knowledge graph. The user
might want explicit "this person works at that company" relationships.

**Solution**: Add Graphiti as a secondary index, populated by Mnemosyne.

### Architecture

```
Hermes → Mnemosyne.record(event)
            ├─→ SQLite (working + episodic)
            ├─→ Qdrant (semantic vectors)
            └─→ Graphiti (entities + relationships)
```

### Setup

```bash
pip install graphiti-core
# Configure to use a separate Neo4j container (or FalkorDB for embedded mode)
```

### When to use

- User has many "person X works at company Y" facts
- Wants to answer "tell me about everyone I met last month" with structured data

## 5.4 Litestream (SQLite replication)

**Problem**: Mnemosyne SQLite is one file. If the disk dies, all memory is lost.

**Solution**: Litestream streams SQLite WAL changes to S3-compatible storage
(local NAS, Backblaze B2, etc.) every few seconds.

### Setup

```bash
# Workstation (where Mnemosyne lives)
brew install litestream   # or: pip install litestream

# Config
cat > /etc/litestream.yml <<'EOF'
dbs:
  - path: ~/ai-brain/hermes_config/mnemosyne/mnemosyne.db
    replicas:
      - url: file:///mnt/raid/_backups/mnemosyne-litestream
        retention: 720h
EOF

# Run
litestream replicate -config /etc/litestream.yml
```

### When to use

- User wants < 24h data loss window
- Has a second machine (e.g. workstation can host the replica)
- Willing to accept ~5s extra write latency

## 5.5 Headscale (self-hosted Tailscale)

**Problem**: Tailscale's hosted control plane is technically a cloud dependency.

**Solution**: Run Headscale on the workstation, replace Tailscale with
open-source Tailscale client + Headscale control.

### When to use

- User has strong "no cloud at all" preference
- Willing to spend 2-4 hours on setup
- Willing to manage a Headscale container

## 5.6 Multi-machine federation (advanced)

**Problem**: User has 3+ machines (M1 + workstation + NAS + old MacBook).

**Solution**: Each machine can host a Qdrant shard. Hermes routes to the
right shard based on file metadata.

### When to use

- Total data > 10M points
- Latency to a single Qdrant is too high
- Want to retire old MacBook as a "warm" archive

## 5.7 Eval set expansion (100 → 1000)

**Problem**: 100 queries gives statistical power ~±5%. 1000 gives ~±1.5%.

**Solution**: 4x the annotation effort. Use crowd workers or dedicated
annotation sessions.

### When to use

- Initial 100-eval shows marginal results (e.g. 0.83 vs 0.80 target)
- Need finer-grained regression detection

## 5.8 Active learning loop

**Problem**: Indexer uses static embedding models. Could improve by learning
from user feedback.

**Solution**: When user marks a result as "good" or "bad", feed to a
fine-tuning pipeline (LoRA) on the embedding model.

### When to use

- Have ≥ 1000 user feedback events
- Willing to invest in fine-tuning infrastructure
- Eval shows the base model is a bottleneck (not the indexer pipeline)

---

## Decision matrix: should I do Phase 5?

| If you want... | Then do... |
|---|---|
| 70B-class quality | §5.1 (RPC) + §5.2 (KTransformers) |
| Better cross-document reasoning | §5.3 (Graphiti) |
| < 24h data loss | §5.4 (Litestream) |
| Zero cloud | §5.5 (Headscale) |
| Multi-NAS scale | §5.6 (Federation) |
| Better eval precision | §5.7 (1000 eval) |
| Personalized embeddings | §5.8 (Active learning) |

**Recommendation**: Don't do any of these until v4 has been running stable
for at least 1 month and you've collected 100+ hours of usage data.

---

## See also

- [v4 master plan §14](個人AI第二腦落地方案_v4.md)
- [RPC 拆分指南](RPC_拆分指南.md) — detailed RPC setup
- [Tailscale 私網設定指南](Tailscale_私網設定指南.md) — Headscale alternative
