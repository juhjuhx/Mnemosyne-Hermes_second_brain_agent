# Open WebUI 整合指南

> Connect Open WebUI to Hermes Agent so the user has a polished chat UI on top of the local AI stack.

---

## 1. Install Open WebUI on M1

```bash
# In the ai-brain venv
source ~/ai-brain/venv/bin/activate
pip install open-webui

# Verify
open-webui --version
```

## 2. Configure Open WebUI

### Environment variables

```bash
# ~/.ai-brain/open_webui.env
OPENAI_API_BASE_URLS=["http://127.0.0.1:8642/v1"]
OPENAI_API_KEYS=["hermes-not-validated"]   # Hermes doesn't check the key
DEFAULT_MODEL="hermes-agent"
ENABLE_SIGNUP=false
ENABLE_API_KEY=false
ENABLE_WEB_SEARCH=false
ENABLE_IMAGE_GENERATION=false
ENABLE_CODE_INTERPRETER=true
DEFAULT_USER_ROLE=admin
WEBUI_AUTH=false   # Single-user; on Tailscale = OK
DATA_DIR=~/ai-brain/open_webui/data
```

### Persist the config

```bash
# Move to a place that survives reboots
mkdir -p ~/ai-brain/open_webui
cat > ~/ai-brain/open_webui/config.env <<'EOF'
OPENAI_API_BASE_URLS=["http://127.0.0.1:8642/v1"]
# ... etc
EOF
```

## 3. Start Open WebUI

```bash
# Source the env
set -a; source ~/ai-brain/open_webui/config.env; set +a

# Start
open-webui serve --port 3000 --host 127.0.0.1
```

## 4. Auto-start with launchd

Copy `src/launchd/ai.brain.openwebui.plist` to `~/Library/LaunchAgents/`:

```bash
cp src/launchd/ai.brain.openwebui.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/ai.brain.openwebui.plist
```

(Plist template is in `src/launchd/`; fill in the actual env values.)

## 5. Access from a browser

### On M1 itself
```bash
open http://127.0.0.1:3000
```

### From any device on Tailscale
```
http://m1.tail-xxxx.ts.net:3000
```

(Replace `tail-xxxx.ts.net` with your actual tailnet name. Visible in
`tailscale status`.)

### From a phone (iOS / Android)
1. Install Tailscale app
2. Sign in to your tailnet
3. Open browser to `http://m1:3000`
4. (Optional) "Add to Home Screen" for PWA mode

## 6. Connect to Hermes Agent

The first time you open Open WebUI, it should auto-detect the OpenAI-compatible
endpoint at `http://127.0.0.1:8642/v1`.

If not:
1. Click your profile → Settings → Connections
2. Click "Add Connection" → "OpenAI API"
3. URL: `http://127.0.0.1:8642/v1`
4. Key: any string (Hermes doesn't validate)
5. Click "Save"
6. Click the refresh icon next to the model dropdown

You should see:
- `hermes-agent` (the Hermes orchestrator)
- `gemma-edge` (local Ollama)
- `qwen-heavy` (workstation's Qwen 3.6 27B)

## 7. First conversation

Ask: `What files did you index today?`

Expected flow:
1. Open WebUI → Hermes Agent (via OpenAI API)
2. Hermes uses `qdrant-search` skill
3. Hermes uses `filesystem-search` skill
4. Hermes returns a list
5. Mnemosyne records the conversation
6. Open WebUI displays the response

## 8. Configure for mobile (PWA)

In Open WebUI:
1. Click your profile → Settings → Interface
2. Enable "PWA Mode"
3. Save
4. On your phone, open the URL, then "Add to Home Screen"

The PWA caches the chat history and config; works offline for cached
conversations.

## 9. Common gotchas

| Problem | Fix |
|---|---|
| Models not showing | Check `OPENAI_API_BASE_URLS` env var; restart Open WebUI |
| Chat is slow | Check Hermes Agent logs; check Ollama/llama-server are up |
| Auth loops | Set `WEBUI_AUTH=false` (single-user) or set proper `WEBUI_SECRET_KEY` |
| Mobile PWA breaks | Clear browser cache; re-add to home screen |
| Hermes tool calls fail | Check MCP servers are up; check `skills.dir` in Hermes config |
| High CPU on M1 | Lower `ENABLE_CODE_INTERPRETER` (sandboxed Python is heavy) |

---

## See also

- [Hermes Agent 整合指南](../Hermes_Agent_整合指南.md)
- [Phase 3 Hermes 整合指南](../Phase_3_Hermes整合指南.md) — full setup
- [Tailscale 私網設定指南](../Tailscale_私網設定指南.md) — access from phone
