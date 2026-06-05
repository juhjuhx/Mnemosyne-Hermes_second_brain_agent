# Phase 1 部署指南 — Service Deployment

> **Goal**: All services running and bound to 127.0.0.1; smoke tests pass.
> **Duration**: 2-3 days
> **Prerequisites**: Phase 0 complete

---

## 1.1 M1 services

### Ollama (LLM server for Gemma 4 E2B + nomic)

```bash
# Install
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull unsloth/gemma-4-e2b-it-GGUF:Q4_K_XL
ollama pull nomic-embed-text

# Customize with our Modelfile (see src/ollama/Modelfile.gemma4)
cd ~/mnemosyne/src/ollama
ollama create hermes-edge -f Modelfile.gemma4

# Smoke test
curl -s http://127.0.0.1:11434/api/tags | jq
# Should list "hermes-edge" and "nomic-embed-text"

curl -s http://127.0.0.1:11434/api/generate \
  -d '{"model":"hermes-edge","prompt":"hello"}' | jq
# Should return a response
```

**Auto-start with launchd**: copy `src/launchd/ai.brain.ollama.plist` to
`~/Library/LaunchAgents/`, then:

```bash
launchctl load ~/Library/LaunchAgents/ai.brain.ollama.plist
launchctl start ai.brain.ollama
```

### Qdrant (vector store)

```bash
# Install via Docker (simpler) or binary
docker run -d \
  --name qdrant \
  -p 127.0.0.1:6333:6333 \
  -v /Volumes/RAID/AISecondBrain/index/qdrant:/qdrant/storage \
  qdrant/qdrant:v1.16.0

# Smoke test
curl -s http://127.0.0.1:6333/ | jq
# Should return Qdrant info

# Create the collection with named vectors
curl -s -X PUT http://127.0.0.1:6333/collections/second_brain \
  -H "Content-Type: application/json" \
  -d @src/qdrant/create_collection.json
```

**Auto-start with launchd**: see `src/launchd/ai.brain.qdrant.plist`.

### Mnemosyne (memory layer)

```bash
# Install
source ~/ai-brain/venv/bin/activate
pip install mnemosyne

# Initialize
cd ~/ai-brain
mkdir -p hermes_config/mnemosyne
mnemosyne init --path hermes_config/mnemosyne/mnemosyne.db

# Verify
ls -la hermes_config/mnemosyne/
# Should show mnemosyne.db
```

### Hermes Agent

```bash
# Install
pip install hermes-agent

# Configure
mkdir -p ~/ai-brain/hermes_config
cp src/hermes_skills/* ~/ai-brain/hermes_config/skills/   # or symlink
cp src/hermes_config.yaml ~/ai-brain/hermes_config/config.yaml

# Edit config.yaml to point at:
#   - models.local: http://127.0.0.1:11434
#   - models.remote: http://station:8080/v1
#   - memory.backend: mnemosyne
#   - memory.mnemosyne.path: ~/ai-brain/hermes_config/mnemosyne/mnemosyne.db
#   - skills.dir: ~/ai-brain/hermes_config/skills/

# Start
hermes-agent --config ~/ai-brain/hermes_config/config.yaml --port 8642

# Smoke test
curl -s http://127.0.0.1:8642/v1/models | jq
# Should list "hermes-agent" and any configured remote models
```

**Auto-start with launchd**: `src/launchd/ai.brain.hermes.plist`.

### Open WebUI

```bash
# Install
pip install open-webui

# Configure to talk to Hermes
mkdir -p ~/ai-brain/open_webui
cat > ~/ai-brain/open_webui/config.yaml <<'EOF'
OPENAI_API_BASE_URLS=["http://127.0.0.1:8642/v1"]
DEFAULT_MODEL="hermes-agent"
ENABLE_SIGNUP=false
ENABLE_API_KEY=false
WEBUI_AUTH=false
EOF

# Start
OPEN_WEBUI_DATA_DIR=~/ai-brain/open_webui/data \
  open-webui serve --port 3000 --host 127.0.0.1

# Smoke test
# Open browser to http://127.0.0.1:3000 (or via Tailscale at http://m1:3000)
```

**Auto-start with launchd**: `src/launchd/ai.brain.openwebui.plist`.

### Indexer (placeholder; full code in Phase 2)

```bash
# Install
mkdir -p ~/ai-brain/scripts
ln -sf ~/mnemosyne/src/scripts/* ~/ai-brain/scripts/

# Create config
cat > ~/ai-brain/indexer_config.yaml <<'EOF'
inbox: /Volumes/RAID/AISecondBrain/inbox/
archive: /Volumes/RAID/AISecondBrain/_archive/
qdrant_url: http://127.0.0.1:6333
ollama_url: http://127.0.0.1:11434
collection: second_brain
workers: 1  # DO NOT INCREASE — v3 invariant
EOF

# Phase 1: just start the watcher (no full pipeline yet)
cd ~/ai-brain
source venv/bin/activate
python scripts/indexer.py --config indexer_config.yaml --dry-run
# Should watch inbox/ and log new files (but not process them yet)
```

## 1.2 Workstation services

### llama-server (Qwen 3.6 27B-PRISM-DQ)

```bash
# Build llama.cpp
cd ~/ai-brain-station/llama.cpp
git clone https://github.com/ggerganov/llama.cpp.git .
cmake -B build \
  -DGGML_VULKAN=ON \
  -DGGML_NATIVE=ON \
  -DGGML_OPENMP=ON \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 16

# Download model (you provide the .gguf file)
mkdir -p ~/ai-brain-station/models
# Place Ex0bit/Qwen3.6-27B-PRISM-PRO-DQ.Q4_K_M.gguf in models/

# Create systemd unit
sudo cp ~/mnemosyne/src/systemd/ai-brain-llama-server.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-brain-llama-server

# Smoke test
curl -s http://127.0.0.1:8080/v1/models | jq
# Should list "Qwen3.6-27B-PRISM-PRO-DQ"

curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-27B-PRISM-PRO-DQ","messages":[{"role":"user","content":"hello"}]}' | jq
# Should return a response
```

### Qdrant mirror (read-only)

```bash
# Same as M1 but with --read-only flag
docker run -d \
  --name qdrant-mirror \
  -p 127.0.0.1:6333:6333 \
  -v /mnt/raid/AISecondBrain/index/qdrant:/qdrant/storage:ro \
  qdrant/qdrant:v1.16.0
```

(For v4, the mirror is read-only. Phase 5 may add bi-directional sync.)

### Tailscale

Already configured in Phase 0.

## 1.3 Smoke test suite

Run all smoke tests:

```bash
# M1
cd ~/ai-brain
source venv/bin/activate
pytest tests/test_smoke_phase1.py -v
# Tests:
#   - Ollama responds
#   - Qdrant responds
#   - Mnemosyne DB exists
#   - Hermes Agent responds
#   - Open WebUI responds
#   - llama-server (via Tailscale) responds
```

Expected: all tests pass.

## 1.4 Day 3 wrap-up

At the end of Phase 1, you should have:

- [ ] All M1 services running and bound to 127.0.0.1
- [ ] All workstation services running and bound to 127.0.0.1
- [ ] All services auto-start on boot (launchd / systemd)
- [ ] All services survive reboot
- [ ] Tailscale ACLs in place
- [ ] Smoke test suite passes
- [ ] At least one round-trip Hermes → Ollama → Hermes works

## 1.5 Common gotchas

| Problem | Fix |
|---|---|
| Ollama hangs after sleep | `launchctl kickstart -k gui/$(id -u)/ai.brain.ollama` |
| Qdrant OOM on first start | Reduce `hnsw_config.ef_construct` to 64 |
| llama-server OOM on first request | Lower `--ctx-size` from 32768 to 16384 |
| Vulkan ICD not found | `vulkaninfo` should list A770; if not, reinstall `mesa-vulkan-drivers` |
| Hermes can't find skills | Check `skills.dir` in config.yaml is an absolute path |

---

## Next phase

→ [`Phase_2_索引流水線指南.md`](Phase_2_索引流水線指南.md) — Indexing pipeline
