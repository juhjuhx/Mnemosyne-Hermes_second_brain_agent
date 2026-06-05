# Hermes Agent 整合指南

> Install and configure Hermes Agent as the orchestrator of the Personal AI Second Brain.
> Hermes replaces v3's self-built FastAPI agent.

---

## 1. What is Hermes Agent

`NousResearch/hermes-agent` is a multi-model agent runtime that:

- Accepts any OpenAI-compatible model API (Ollama, llama.cpp, vLLM, etc.)
- Implements the MCP (Model Context Protocol) for tool use
- Loads skills from `agentskills.io`-format directories
- Has built-in memory plugin (Mnemosyne adapter available)
- Supports sub-agents (parallel task delegation)
- Ships a CLI (`hermes-cli`) and an OpenAI-compatible API server

## 2. Install on M1

```bash
# In the ai-brain venv
source ~/ai-brain/venv/bin/activate

# Install
pip install hermes-agent

# Verify
hermes --version
```

## 3. Configure

Create `~/ai-brain/hermes_config/`:

```bash
mkdir -p ~/ai-brain/hermes_config/{skills,logs}
```

### config.yaml

```yaml
# ~/ai-brain/hermes_config/config.yaml

agent:
  name: "personal-second-brain"
  description: "M1 edge agent for Personal AI Second Brain"
  version: "4.0"

models:
  # Always-on local model (M1)
  local:
    name: "gemma-edge"
    base_url: "http://127.0.0.1:11434/v1"
    api_key: "ollama"
    model_name: "hermes-edge"  # from Modelfile.gemma4
    context_length: 8192
    cost_per_million_tokens: 0.0  # local = free

  # Heavy remote model (workstation)
  remote:
    name: "qwen-heavy"
    base_url: "http://station:8080/v1"  # Tailscale Magic DNS
    api_key: "not-used"
    model_name: "Qwen3.6-27B-PRISM-PRO-DQ"
    context_length: 32768
    cost_per_million_tokens: 0.0  # local = free

  # Routing: pick local for "easy" tasks, remote for "hard" tasks
  routing:
    strategy: "complexity"
    complexity_threshold_chars: 200
    always_route_remote_for: ["research", "analysis", "summarization"]

memory:
  backend: mnemosyne
  mnemosyne:
    db_path: ~/ai-brain/hermes_config/mnemosyne/mnemosyne.db
    embedding_model: "nomic-embed-text"
    recency_weight: 0.3
    max_context_memories: 20
    auto_record: true

skills:
  dir: ~/ai-brain/hermes_config/skills/
  auto_reload: true
  log_loads: true
  trust_local_skills: true

api_server:
  host: 127.0.0.1
  port: 8642
  openai_compatible: true
  cors_origins: ["http://127.0.0.1:3000"]

logging:
  level: INFO
  file: ~/ai-brain/logs/hermes.log
  structured: true
  max_size_mb: 100
  backup_count: 10

plugins:
  # ralph-watchdog integration
  watchdog:
    enabled: true
    config: ~/ai-brain/hermes_config/ralph_watchdog.yaml
```

### Initialize Mnemosyne

```bash
# Mnemosyne adapter requires an empty SQLite
mkdir -p ~/ai-brain/hermes_config/mnemosyne
mnemosyne init --path ~/ai-brain/hermes_config/mnemosyne/mnemosyne.db
```

## 4. Install skills

```bash
# Symlink the repo's skills
ln -sf ~/mnemosyne/src/hermes_skills/* ~/ai-brain/hermes_config/skills/

# Verify
ls ~/ai-brain/hermes_config/skills/
# Should show: qdrant-search/ filesystem-search/ video-slice/
```

## 5. Start Hermes Agent

### Manual start (for testing)

```bash
source ~/ai-brain/venv/bin/activate
hermes-agent --config ~/ai-brain/hermes_config/config.yaml
```

### Auto-start with launchd

```bash
# Copy plist
cp src/launchd/ai.brain.hermes.plist ~/Library/LaunchAgents/

# Load
launchctl load ~/Library/LaunchAgents/ai.brain.hermes.plist

# Verify
launchctl list | grep hermes
```

## 6. Verify

```bash
# Test 1: list models
curl -s http://127.0.0.1:8642/v1/models | jq
# Should list: gemma-edge, qwen-heavy

# Test 2: simple chat
curl -s http://127.0.0.1:8642/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-edge",
    "messages": [{"role": "user", "content": "Say hello in Chinese"}]
  }' | jq

# Test 3: list skills
curl -s http://127.0.0.1:8642/v1/skills | jq
# Should list: qdrant-search, filesystem-search, video-slice

# Test 4: invoke a skill
curl -s -X POST http://127.0.0.1:8642/v1/skills/qdrant-search/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool": "search", "args": {"query": "test", "top_k": 3}}' | jq
```

## 7. Hook into Open WebUI

Open WebUI connects to Hermes via the OpenAI-compatible API. See
[`Open_WebUI_整合指南.md`](Open_WebUI_整合指南.md).

## 8. Memory: how Mnemosyne works

```
User: "What did I write about Hermes?"
  │
  ▼
Hermes.retrieve_context(query="Hermes")
  │
  ├─→ Mnemosyne.retrieve(query, top_k=20)
  │    ├─→ SQLite LIKE/FTS5 (recent conversations)
  │    ├─→ Qdrant search (semantic match)
  │    └─→ Re-rank with time-decay
  │         └─→ Top 20 memories
  │
  └─→ Inject memories into prompt as context
       └─→ Send to LLM (gemma-edge or qwen-heavy)
            └─→ Response
  │
  ▼
Hermes.record(conversation)
  │
  └─→ Mnemosyne.record(event_type="conversation", payload=...)
       ├─→ SQLite (working + episodic tables)
       └─→ Qdrant (semantic vector)
```

## 9. ralph-watchdog integration

See [`Phase_4_評估與回饋指南.md`](Phase_4_評估與回饋指南.md) for the full
eval-driven iteration loop. Hermes ships with a watchdog plugin that
auto-runs eval on config changes and alerts on regression.

## 10. Common gotchas

| Problem | Fix |
|---|---|
| Hermes can't connect to Ollama | Check `models.local.base_url`; test with `curl http://127.0.0.1:11434/v1/models` |
| Hermes can't reach workstation | Check Tailscale ACL allows m1 → station:8080 |
| Skills not loading | Check `skills.dir` is absolute path; check `SKILL.md` frontmatter |
| Mnemosyne not recording | Check `db_path` exists; check `auto_record: true` in config |
| Memory context too long | Reduce `max_context_memories`; lower `recency_weight` |
| Hermes OOM | Reduce `ctx_size`; unload unused models |

## 11. Useful CLI commands

```bash
# Show config
hermes config show

# List loaded skills
hermes skills list

# Test a skill
hermes skills test qdrant-search

# Show memory stats
hermes memory stats

# Manually record a memory
hermes memory add "Today I set up Hermes Agent"

# Show conversation history
hermes history list

# Show watchdog state
hermes watchdog status
```

---

## See also

- [v4 master plan §3, §7, §12](../個人AI第二腦落地方案_v4.md)
- [Hermes_Skill_範本庫](../Hermes_Skill_範本庫.md) — 3 example skills
- [Phase_3_Hermes整合指南](../Phase_3_Hermes整合指南.md) — full setup
- [Open_WebUI_整合指南](../Open_WebUI_整合指南.md) — UI integration
