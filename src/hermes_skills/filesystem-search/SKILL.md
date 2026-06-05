---
name: filesystem-search
description: Find files in the personal archive by filename, date range, file type, or tag. Use this for "find the file called X", "what photos did I take in 2024", or any metadata-based lookup. Faster than semantic search for exact metadata queries.
---

# filesystem-search skill

This skill exposes metadata-based file lookup. It's faster than
`qdrant-search` for exact metadata queries and works even when the
vector index is empty.

## When to use

- User knows the filename (or part of it)
- User wants files from a specific time range
- User wants files of a specific type (image, video, audio, text)
- User wants files with a specific tag
- User wants metadata (size, mtime, hash) for a specific file

## When NOT to use

- User wants semantic search ("articles about X") — use `qdrant-search`
- User wants to read file contents — use `filesystem-read` (not yet implemented)
- User wants to move/delete files — those skills are not exposed by default (privacy)

## Tools

### `find`

Find files matching metadata criteria.

**Input**:
```json
{
  "filename": "hermes*",      // glob pattern, optional
  "type": "image|text|video|audio",  // optional
  "from_date": "2024-01-01",  // ISO date, optional
  "to_date": "2024-12-31",    // ISO date, optional
  "tag": "family",            // optional
  "limit": 20                 // default 20, max 100
}
```

**Output**:
```json
{
  "results": [
    {
      "file_id": "abc123",
      "path": "/Volumes/RAID/AISecondBrain/media/photos/2024-07-15.jpg",
      "type": "image",
      "size_bytes": 2345678,
      "mtime": 1721000000,
      "tags": ["family", "beach"]
    }
  ]
}
```

### `stat`

Get metadata for a specific file.

**Input**:
```json
{"file_id": "abc123"}
```

**Output**: Same as one item of `find` results, plus `indexed_at`, `chunks`, `suggested_move`.

### `tag`

Add, remove, or list tags.

**Input** (add):
```json
{"action": "add", "file_id": "abc123", "tag": "beach"}
```

**Input** (remove):
```json
{"action": "remove", "file_id": "abc123", "tag": "beach"}
```

**Input** (list tags for file):
```json
{"action": "list", "file_id": "abc123"}
```

**Input** (list all tags):
```json
{"action": "list_all"}
```

## Examples

User: "Find the file called hermes_config.yaml"
→ `find(filename="hermes_config.yaml")`

User: "What photos did I take in 2024?"
→ `find(type="image", from_date="2024-01-01", to_date="2024-12-31", limit=50)`

User: "Show me all my photos tagged 'family'"
→ `find(type="image", tag="family")`

## Implementation

See `src/filesystem_server.py` for the MCP server.
See `tests.py` for unit tests.
