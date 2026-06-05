# Phase 3 Hermes 整合指南 — Hermes Integration

> **Goal**: User can chat via Open WebUI; queries are answered with proper tool use; 3 example skills are loadable.
> **Duration**: 5-7 days
> **Prerequisites**: Phase 1 + Phase 2 complete

---

## 3.1 Install Hermes Agent on M1

```bash
# Activate venv
source ~/ai-brain/venv/bin/activate

# Install
pip install hermes-agent

# Verify
hermes --version
```

## 3.2 Configure Hermes

```yaml
# ~/ai-brain/hermes_config/config.yaml

agent:
  name: "personal-second-brain"
  description: "M1 edge agent for Personal AI Second Brain"

models:
  local:
    name: "gemma-edge"
    base_url: "http://127.0.0.1:11434/v1"
    api_key: "ollama"
    model_name: "hermes-edge"  # from Modelfile.gemma4

  remote:
    name: "qwen-heavy"
    base_url: "http://station:8080/v1"  # Tailscale Magic DNS
    api_key: "not-used"
    model_name: "Qwen3.6-27B-PRISM-PRO-DQ"

  routing:
    # Simple heuristic: short queries → local; long/complex → remote
    strategy: "complexity"
    complexity_threshold: 200  # chars; queries above this go to remote

memory:
  backend: mnemosyne
  mnemosyne:
    db_path: ~/ai-brain/hermes_config/mnemosyne/mnemosyne.db
    embedding_model: "nomic-embed-text"
    recency_weight: 0.3

skills:
  dir: ~/ai-brain/hermes_config/skills/
  auto_reload: true
  log_loads: true

api_server:
  host: 127.0.0.1
  port: 8642
  openai_compatible: true
  cors_origins: ["http://127.0.0.1:3000"]

logging:
  level: INFO
  file: ~/ai-brain/logs/hermes.log
  structured: true  # JSON logs
```

## 3.3 Install the 3 example skills

```bash
# Symlink the repo's skills directory
ln -sf ~/mnemosyne/src/hermes_skills/* ~/ai-brain/hermes_config/skills/

# Verify
ls ~/ai-brain/hermes_config/skills/
# Should show:
#   qdrant-search/
#   filesystem-search/
#   video-slice/
```

See [`Hermes_Skill_範本庫.md`](Hermes_Skill_範本庫.md) for the full templates.

## 3.4 Test the skills

```bash
# Restart Hermes to load the skills
launchctl kickstart -k gui/$(id -u)/ai.brain.hermes

# Wait 5s
sleep 5

# List loaded skills
curl -s http://127.0.0.1:8642/v1/skills | jq
# Should show the 3 skills

# Test qdrant-search
curl -s -X POST http://127.0.0.1:8642/v1/skills/qdrant-search/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool": "search", "args": {"query": "test", "top_k": 3}}' | jq
# Should return 3 points (or empty if no data yet)
```

## 3.5 Open WebUI integration

See [`Open_WebUI_整合指南.md`](Open_WebUI_整合指南.md) for the full guide.

Quick version:

1. Open `http://127.0.0.1:3000` (or via Tailscale)
2. Admin → Settings → Connections → OpenAI API
3. URL: `http://127.0.0.1:8642/v1`
4. Key: any string
5. Save
6. Refresh model list — should see "hermes-agent" + "gemma-edge" + "qwen-heavy"

## 3.6 First chat test

In Open WebUI, ask: `What files did you index today?`

Expected flow:
1. Open WebUI → Hermes Agent
2. Hermes uses `qdrant-search` skill
3. Hermes uses `filesystem-search` skill
4. Hermes returns a list
5. Mnemosyne records the conversation
6. Open WebUI displays the response

## 3.7 MCP server smoke test

```bash
# Qdrant MCP server
python src/mcp_servers/qdrant_server.py --test
# Should return OK

# Filesystem MCP server
python src/mcp_servers/filesystem_server.py --test
# Should return OK

# Video slice MCP server
python src/mcp_servers/video_slice_server.py --test
# Should return OK
```

## 3.8 Sub-agent demo (optional)

Hermes supports sub-agents for parallel tasks. Test:

```bash
curl -s -X POST http://127.0.0.1:8642/v1/sub-agents/run \
  -H "Content-Type: application/json" \
  -d '{
    "name": "research-assistant",
    "task": "Find all photos from 2024 that contain people",
    "max_iterations": 10
  }' | jq
```

Should return a structured answer.

## 3.9 Common gotchas

| Problem | Fix |
|---|---|
| Hermes can't connect to Ollama | Check `models.local.base_url`; test with `curl http://127.0.0.1:11434/v1/models` |
| Hermes can't reach workstation | Check Tailscale ACL allows m1 → station:8080 |
| Skills not loading | Check `skills.dir` is absolute path; check `SKILL.md` frontmatter |
| Open WebUI shows no models | Restart Open WebUI; check `OPENAI_API_BASE_URLS` env var |
| Hermes OOM | Reduce `ctx_size` in config; unload unused models |
| MCP server timeouts | Increase `--mcp-timeout 30`; check resource usage |

---

## Next phase

→ [`Phase_4_評估與回饋指南.md`](Phase_4_評估與回饋指南.md) — Evaluation
