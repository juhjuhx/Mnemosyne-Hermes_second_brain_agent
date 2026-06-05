---
name: qdrant-search
description: Search the personal second brain's Qdrant vector store for documents similar to a natural language query. Use this when the user asks "find me documents about X", "what's in my archive about Y", or any semantic search question. Returns top-K results with scores and file paths.
---

# qdrant-search skill

This skill exposes a `search` tool that returns the top-K documents most similar
to a natural language query, using both text and image embeddings.

## When to use

- User asks a semantic search question ("find me articles about X")
- User wants to recall something they previously indexed
- User asks "show me photos of X" or "find me notes about Y"
- User wants to find similar documents to a known file

## When NOT to use

- User wants exact-match filename lookup (use `filesystem-search` instead)
- User wants a SQL query (use `sqlite-query` instead)
- User wants to operate on a single file (use `filesystem-read` instead)
- User wants to write/modify the index (this skill is read-only)

## Tools

### `search`

Search for similar documents in the second_brain collection.

**Input schema**:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Natural language query"
    },
    "top_k": {
      "type": "integer",
      "default": 10,
      "description": "Number of results to return"
    },
    "modality": {
      "type": "string",
      "enum": ["text", "image", "both"],
      "default": "both",
      "description": "Which named vector to search"
    },
    "filter": {
      "type": "object",
      "description": "Optional payload filter (e.g. {\"tag\": \"family\"})"
    }
  },
  "required": ["query"]
}
```

**Output schema**:
```json
{
  "type": "object",
  "properties": {
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string"},
          "score": {"type": "number"},
          "modality": {"type": "string"},
          "preview": {"type": "string"},
          "path": {"type": "string"}
        }
      }
    }
  }
}
```

## Examples

User: "Find me photos of my dog at the beach"
→ `search(query="dog at beach", modality="image", top_k=5)`

User: "What did I write about climate change?"
→ `search(query="climate change", modality="text", top_k=5)`

User: "Photos tagged 'family' from 2024"
→ `search(query="family 2024", modality="image", filter={"tag": "family", "year": 2024})`

## Implementation

See `src/qdrant_server.py` for the MCP server implementation.
See `tests.py` for unit tests.
