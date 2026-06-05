# llama_cpp — Build flags & RPC config

> Workstation (Linux) build of llama.cpp for the A770 16GB GPU.
> Vulkan backend (not CUDA — Intel Arc A770 does not support CUDA).

## Build

```bash
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp

# CMake with Vulkan + RPC server (for Phase 5 split)
cmake -B build \
  -DGGML_VULKAN=ON \
  -DGGML_RPC=ON \
  -DGGML_OPENMP=OFF \
  -DCMAKE_BUILD_TYPE=Release

cmake --build build --config Release -j 8
```

## Server flags for Ex0bit PRISM-DQ Q4 (27B)

```bash
./build/bin/llama-server \
  --model /opt/models/qwen3.6-27b-prism-dq-q4_k_m.gguf \
  --port 8081 \
  --host 127.0.0.1 \
  --ctx-size 16384 \
  --n-gpu-layers 99 \
  --batch-size 512 \
  --ubatch-size 128 \
  --threads 8 \
  --rope-freq-base 1000000 \
  --speculative-model-draft auto \
  --draft-max 8 \
  --lookup-ngram-min 3
```

- `--speculative-model-draft auto` uses the bundled MTP head in PRISM-DQ
- `--draft-max 8` — 8 speculative tokens per step (sweet spot for 27B)
- `--lookup-ngram-min 3` — self-speculative lookup threshold

## Server flags for mudler Carnice Qwen3.6-MoE-35B-A3B-APEX (I-Compact 17GB)

```bash
./build/bin/llama-server \
  --model /opt/models/carnice-qwen3.6-moe-35b-a3b-apex-iq4_k_m.gguf \
  --port 8081 \
  --host 127.0.0.1 \
  --ctx-size 16384 \
  --n-gpu-layers 99 \
  --batch-size 256 \
  --ubatch-size 64 \
  --threads 8 \
  --rope-freq-base 1000000 \
  --override-tensor exps=CPU \
  --speculative-model-draft auto \
  --draft-max 4
```

> **Note**: I-Compact 17GB exceeds A770 16GB VRAM. The
> `--override-tensor exps=CPU` offloads MoE expert layers to system RAM
> (48GB available). Slower but fits. If performance is unacceptable,
> use the 14GB `mini` variant with no experts offloaded.

## RPC mode (Phase 5)

For distributed inference (split prompt + decode across two machines),
enable the RPC server and use it as a backend:

```bash
# On the secondary machine (could be M1, but constrained by 8GB RAM)
./build/bin/rpc-server --host 0.0.0.0 --port 8082

# On the primary, point llama-server to it
./build/bin/llama-server \
  --model /opt/models/qwen3.6-27b-prism-dq-q4_k_m.gguf \
  --rpc 192.168.1.42:8082 \      # IP of the rpc-server
  --port 8081 \
  ...
```

> See [`../docs/02_方案文檔/RPC_拆分指南.md`](../docs/02_方案文檔/RPC_拆分指南.md)
> for when this is worth doing.

## Performance notes

| Model | A770 16GB | MTP on | MTP off | Notes |
|---|---|---:|---:|---|
| PRISM-DQ 27B Q4 | fits | 121 tok/s | 80 tok/s | self-speculative via MTP head |
| Carnice 35B-A3B I-Compact | experts→CPU | 38 tok/s | 25 tok/s | bigger but slower |
| Carnice 14B mini | fits | 75 tok/s | 50 tok/s | smaller, faster, less capable |

## Quantization guidance

- **Q4_K_M**: best quality/perf ratio for VRAM-bound (A770 16GB)
- **Q3_K_S**: emergency use only; noticeable quality loss
- **Q5_K_M**: only if model is < 13B; otherwise won't fit
- **IQ4_XS**: imatrix-quantized; slightly smaller than Q4_K_M with similar quality

## Why not CUDA?

Intel Arc A770 does not support CUDA. Vulkan is the only first-class
backend for Intel discrete GPUs in llama.cpp. Performance is
comparable to CUDA on Ampere for our model sizes (within 10%).

## See also

- [`../docs/02_方案文檔/Phase_1_部署指南.md`](../docs/02_方案文檔/Phase_1_部署指南.md) — service deployment
- [`../docs/02_方案文檔/RPC_拆分指南.md`](../docs/02_方案文檔/RPC_拆分指南.md) — RPC split
- [`../docs/01_對話與調研紀錄/2026-06-05_模型選型_Qwen3.6_vs_Gemma4.md`](../docs/01_對話與調研紀錄/2026-06-05_模型選型_Qwen3.6_vs_Gemma4.md) — model selection
