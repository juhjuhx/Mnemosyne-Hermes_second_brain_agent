# qdrant-search

Qdrant vector store semantic search — one of the 3 example skills in
the Personal AI Second Brain.

## Quick example

```python
from src.mcp_servers.qdrant_server import QdrantMCPServer

server = QdrantMCPServer()

# Search
result = server.search(
    query="photos of my dog",
    top_k=5,
    modality="image",
    filter_dict={"tag": "family"},
)
for r in result["results"]:
    print(f"{r['file_id']}: {r['score']:.3f}  {r['path']}")

# Upsert (used by the indexer)
server.upsert(
    file_id="2024-07-15_dog-beach",
    text_vec=[0.1] * 768,
    image_vec=[0.2] * 512,
    payload={"path": "/Volumes/RAID/.../2024-07-15_dog-beach.jpg", "tag": "family"},
)
```

## Tools exposed

- `search` — semantic search

## Environment variables

| Var | Default | Description |
|---|---|---|
| `QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant server |
| `COLLECTION` | `second_brain` | Collection name |
| `EMBEDDING_URL` | `http://127.0.0.1:11434` | Ollama |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |

## See also

- [`SKILL.md`](SKILL.md) — full agent-facing documentation
- [`manifest.json`](manifest.json) — MCP server config
- [`tests.py`](tests.py) — unit tests
