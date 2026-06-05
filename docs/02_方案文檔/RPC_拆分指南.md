# RPC 拆分指南 — llama.cpp Distributed Inference

> Distribute LLM inference across machines using llama.cpp's RPC backend.
> Useful for Phase 5 when you want to run models larger than the GPU's VRAM.

---

## 1. What is RPC

`llama.cpp`'s RPC backend lets you run a llama-server on one machine
(coordinator) and offload some layers to other machines (RPC servers).
The RPC servers use whatever accelerator they have (Metal, CUDA, Vulkan,
or just CPU).

## 2. When to use

- Want to run a 35B+ model on hardware that has only 16GB VRAM
- Have a second machine (e.g. M1) with spare RAM (unified memory)
- Can tolerate ~50ms latency overhead per query

## 3. Architecture

```
┌─────────────────────────────────┐         ┌──────────────────────────────────┐
│ M1 (RPC server)                 │         │ Workstation (coordinator)        │
│                                 │         │                                  │
│ • llama.cpp rpc-server          │         │ • llama.cpp llama-server         │
│ • Listens on :50052             │◄────────┤ • Listens on :8080               │
│ • Hosts layers 0-19             │  RPC   │ • Hosts layers 20-46             │
│ • Uses Metal + 8GB unified      │  mesh  │ • Uses Vulkan A770 16GB          │
│   (5-6GB to spare)              │  Tailscale│ • Caches KV in VRAM            │
└─────────────────────────────────┘         └──────────────────────────────────┘
```

For Qwen 3.6 27B (47 layers): offload 20 layers to M1, keep 27 on workstation.

## 4. Build llama.cpp with RPC

### On M1 (RPC server)

```bash
cd ~/ai-brain-station/llama.cpp  # or wherever you have the source
cmake -B build-rpc \
  -DGGML_METAL=ON \
  -DLLAMA_BUILD_RPC=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rpc --config Release -j 8
```

### On workstation (coordinator)

```bash
cd ~/ai-brain-station/llama.cpp
cmake -B build \
  -DGGML_VULKAN=ON \
  -DGGML_NATIVE=ON \
  -DGGML_OPENMP=ON \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 16
```

## 5. Start the RPC server on M1

```bash
# On M1
./build-rpc/bin/rpc-server -H 127.0.0.1 -p 50052
# Or with verbose logging
./build-rpc/bin/rpc-server -H 127.0.0.1 -p 50052 -v
```

Or via launchd (copy `src/launchd/ai.brain.rpcserver.plist` to `~/Library/LaunchAgents/`):

```bash
launchctl load ~/Library/LaunchAgents/ai.brain.rpcserver.plist
```

## 6. Start the coordinator on workstation

```bash
# On workstation
./build/bin/llama-server \
  --model ~/models/Qwen3.6-27B-PRISM-PRO-DQ.Q4_K_M.gguf \
  --rpc 100.x.x.x:50052 \
  --gpu-layers 27 \
  --ctx-size 32768 \
  --port 8080 \
  --host 127.0.0.1 \
  --parallel 2
```

The `--rpc` flag tells llama-server to fetch layers 0-19 from the RPC server
at `100.x.x.x:50052` (M1's Tailscale IP).

## 7. Verify

```bash
# From any machine on Tailscale
curl -s http://station:8080/v1/models | jq

# Make a test request
curl -s http://station:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-27B-PRISM-PRO-DQ","messages":[{"role":"user","content":"hi"}]}' | jq
```

## 8. Latency analysis

| Configuration | P50 latency | Notes |
|---|---:|---|
| 27B all on A770 (no RPC) | 1.2s | Baseline |
| 27B with 20 layers on M1 RPC | 1.7s | +50ms for 20 RPC round-trips |
| 27B with all 47 layers on M1 RPC | 2.5s | Too slow; A770 not used |
| 35B-A3B with 30 layers on M1 RPC | 2.3s | New model, +0.6s |

The sweet spot is "use workstation's GPU for the heavy half, offload the
lighter half to M1's CPU/RAM".

## 9. When RPC helps (decision matrix)

| If you want... | Then RPC helps? |
|---|---|
| 27B on 16GB VRAM | ❌ no need (fits) |
| 35B-A3B on 16GB VRAM | ✅ yes (RPC offload 20 layers) |
| 70B on 16GB VRAM | ⚠️ needed, but very slow |
| 27B with 64K context | ✅ yes (KV cache goes to M1's RAM) |
| Reduce M1 idle RAM | ❌ RPC server uses M1's RAM |

## 10. Common gotchas

| Problem | Fix |
|---|---|
| RPC server not found | Check Tailscale; check `tailscale ping m1` from workstation |
| llama-server crashes on start | Verify model file; check VRAM; check RPC server is up |
| High latency | Reduce number of layers offloaded; move to LAN instead of Tailscale |
| RPC server OOM | Reduce `--rpc-num-ops` (default 4) |
| Model weights not loading | Both machines need to see the same model file path; use NFS or rsync |

## 11. Future: KTransformers for MoE

For Qwen 3.6 35B-A3B (MoE), RPC alone is suboptimal. KTransformers
intelligently offloads only **inactive** experts to system RAM.

See [Phase 5 進階路線指南 §5.2](Phase_5_進階路線指南.md) for details.

---

## See also

- [Phase 5 進階路線指南 §5.1](Phase_5_進階路線指南.md)
- [v4 master plan §14](個人AI第二腦落地方案_v4.md)
- [llama.cpp RPC docs](https://github.com/ggerganov/llama.cpp/blob/master/tools/rpc/README.md)
