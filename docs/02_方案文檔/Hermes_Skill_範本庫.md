# Hermes Skill 範本庫 — 3 Example Skills

> Three working skill templates following the [agentskills.io](https://agentskills.io) spec.
> Each is in `src/hermes_skills/<name>/` and is loadable by Hermes Agent.

---

## Skill 1: `qdrant-search`

**Purpose**: Search Qdrant vector store for documents similar to a natural language query.

### SKILL.md

```markdown
---
name: qdrant-search
description: Search the personal second brain's Qdrant vector store for documents similar to a natural language query. Use this when the user asks "find me documents about X", "what's in my archive about Y", or any semantic search question.
---

# qdrant-search skill

This skill exposes a `search` tool that returns the top-K documents most similar
to a natural language query, using both text and image embeddings.

## When to use

- User asks a semantic search question
- User wants to recall something they previously indexed
- User asks "show me photos of X" or "find me notes about Y"

## When NOT to use

- User wants exact-match filename lookup (use `filesystem-search` instead)
- User wants a SQL query (use `sqlite-query` instead)
- User wants to operate on a single file (use `filesystem-read` instead)

## Tools

### `search`

Search for similar documents.

**Input**:
```json
{
  "query": "natural language query",
  "top_k": 10,
  "modality": "text|image|both",
  "filter": {"tag": "family"}  // optional
}
```

**Output**:
```json
{
  "results": [
    {
      "file_id": "2024-07-15_dog-beach.jpg",
      "score": 0.92,
      "modality": "image",
      "preview": "...",
      "path": "/Volumes/RAID/AISecondBrain/media/photos/2024-07-15_dog-beach.jpg"
    }
  ]
}
```

## Examples

- "Find me photos of my dog at the beach" → calls search(query="dog at beach", modality="image", top_k=5)
- "What did I write about climate change?" → calls search(query="climate change", modality="text", top_k=5)
```

### manifest.json

```json
{
  "name": "qdrant-search",
  "version": "1.0.0",
  "description": "Qdrant vector store semantic search",
  "transport": "stdio",
  "command": "python",
  "args": ["-m", "src.mcp_servers.qdrant_server"],
  "env": {
    "QDRANT_URL": "http://127.0.0.1:6333",
    "COLLECTION": "second_brain"
  },
  "tools": [
    {
      "name": "search",
      "description": "Search for similar documents",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "top_k": {"type": "integer", "default": 10},
          "modality": {"type": "string", "enum": ["text", "image", "both"], "default": "both"},
          "filter": {"type": "object"}
        },
        "required": ["query"]
      }
    }
  ]
}
```

### tests.py

```python
import pytest
from src.mcp_servers.qdrant_server import QdrantMCPServer

@pytest.fixture
def server():
    return QdrantMCPServer(collection="second_brain_test")

def test_search_text(server):
    server.upsert(
        file_id="test1",
        text_vec=[0.1] * 768,
        payload={"text": "hello world"}
    )
    result = server.search(query="greeting", top_k=1, modality="text")
    assert len(result["results"]) == 1
    assert result["results"][0]["file_id"] == "test1"

def test_search_image(server):
    server.upsert(
        file_id="test_img",
        image_vec=[0.1] * 512,
        payload={"path": "/tmp/test.jpg"}
    )
    result = server.search(query="image", top_k=1, modality="image")
    assert len(result["results"]) == 1
    assert result["results"][0]["file_id"] == "test_img"

def test_search_with_filter(server):
    server.upsert(
        file_id="family1",
        text_vec=[0.1] * 768,
        payload={"tag": "family", "text": "Christmas 2024"}
    )
    server.upsert(
        file_id="work1",
        text_vec=[0.2] * 768,
        payload={"tag": "work", "text": "Q4 planning"}
    )
    result = server.search(query="Christmas", top_k=5, filter={"tag": "family"})
    assert all(r["file_id"] == "family1" for r in result["results"])
```

---

## Skill 2: `filesystem-search`

**Purpose**: Find files by name, date, type, or tag using metadata from SQLite.

### SKILL.md (excerpt)

```markdown
---
name: filesystem-search
description: Find files in the personal archive by filename, date range, file type, or tag. Use this for "find the file called X", "what photos did I take in 2024", or any metadata-based lookup.
---

## Tools

### `find`
Find files matching metadata criteria.

**Input**:
```json
{
  "filename": "hermes*",
  "type": "image|text|video|audio",
  "from_date": "2024-01-01",
  "to_date": "2024-12-31",
  "tag": "family",
  "limit": 20
}
```

### `stat`
Get metadata for a specific file.

### `tag`
Add/remove/list tags.
```

(Full `SKILL.md` follows the same structure as Skill 1.)

---

## Skill 3: `video-slice`

**Purpose**: Split videos into ≤10s segments using PySceneDetect; extract middle frame; transcribe audio.

### SKILL.md (excerpt)

```markdown
---
name: video-slice
description: Split a video into segments using PySceneDetect, extract representative frames, and optionally transcribe audio. Use when the user wants to "process this video" or "slice this clip".
---

## Tools

### `slice`
Split video into segments.

**Input**:
```json
{
  "video_path": "/path/to/video.mp4",
  "max_segment_sec": 10,
  "detector": "adaptive|threshold|content",
  "extract_frames": true,
  "transcribe": true
}
```

**Output**:
```json
{
  "segments": [
    {
      "start_sec": 0.0,
      "end_sec": 10.0,
      "middle_frame": "/path/to/frame.jpg",
      "transcript": "..."
    }
  ]
}
```

### `keyframes`
Extract keyframes only (no scene detection).

### `transcribe`
Transcribe audio only.
```

---

## Skill directory layout

```
src/hermes_skills/
├── qdrant-search/
│   ├── SKILL.md
│   ├── manifest.json
│   ├── tests.py
│   ├── README.md
│   └── src/
│       └── qdrant_server.py
├── filesystem-search/
│   ├── SKILL.md
│   ├── manifest.json
│   ├── tests.py
│   ├── README.md
│   └── src/
│       └── filesystem_server.py
└── video-slice/
    ├── SKILL.md
    ├── manifest.json
    ├── tests.py
    ├── README.md
    └── src/
        └── video_slice_server.py
```

---

## Adding a new skill

1. Create directory: `src/hermes_skills/<name>/`
2. Write `SKILL.md` with frontmatter (name + description) and body (instructions)
3. Write `manifest.json` (MCP server config + tool schemas)
4. Write `src/<server>.py` (the actual MCP server)
5. Write `tests.py` (pytest)
6. Write `README.md` (human-facing example)
7. Add to `tests/integration/test_skills.py`
8. Update `docs/02_方案文檔/Hermes_Skill_範本庫.md` to reference the new skill
9. Add entry to `CHANGELOG.md` under `[Unreleased]`

---

## See also

- [agentskills.io spec](https://agentskills.io)
- [Hermes Agent 整合指南](../Hermes_Agent_整合指南.md)
- [v4 master plan §20](../個人AI第二腦落地方案_v4.md) — skill library overview
