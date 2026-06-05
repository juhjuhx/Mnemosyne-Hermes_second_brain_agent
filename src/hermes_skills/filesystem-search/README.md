# filesystem-search

Metadata-based file lookup — one of the 3 example skills in the Personal AI Second Brain.

## Quick example

```python
from src.mcp_servers.filesystem_server import FilesystemMCPServer

server = FilesystemMCPServer(db_path="files.db")

# Find files
result = server.find(filename="hermes", limit=10)
for f in result["results"]:
    print(f"{f['file_id']}: {f['path']}")

# Stat
info = server.stat("abc123")
print(info["file"])

# Tag
server.tag("add", file_id="abc123", tag="important")
```

## Tools exposed

- `find` — find files by metadata
- `stat` — get metadata for one file
- `tag` — add/remove/list tags

## See also

- [`SKILL.md`](SKILL.md) — full agent-facing documentation
- [`manifest.json`](manifest.json) — MCP server config
- [`tests.py`](tests.py) — unit tests
