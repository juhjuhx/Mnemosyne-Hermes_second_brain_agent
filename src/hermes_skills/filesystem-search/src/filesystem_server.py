"""
filesystem_server.py — MCP server exposing metadata-based file lookup.

Implementation behind the `filesystem-search` skill.
"""

import fnmatch
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional


class FileDB:
    """SQLite-backed metadata store. Thread-safe."""

    def __init__(self, db_path: str = "files.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        # tags table (file_id, tag) — many-to-many
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    file_id TEXT,
                    tag TEXT,
                    PRIMARY KEY (file_id, tag),
                    FOREIGN KEY (file_id) REFERENCES files(file_id)
                )
                """
            )
            c.commit()

    def _conn(self):
        c = sqlite3.connect(self.db_path, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def find(
        self,
        filename: Optional[str] = None,
        type_: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
    ) -> list:
        """Find files matching criteria."""
        with self._lock, self._conn() as c:
            sql = "SELECT f.file_id, f.path, f.type, f.size_bytes, f.mtime FROM files f WHERE 1=1"
            params = []

            if filename:
                sql += " AND f.path LIKE ?"
                params.append(f"%{filename}%")  # simple glob; could use fnmatch

            if type_:
                sql += " AND f.type = ?"
                params.append(type_)

            if from_date:
                from_ts = int(datetime.fromisoformat(from_date).timestamp())
                sql += " AND f.mtime >= ?"
                params.append(from_ts)

            if to_date:
                to_ts = int(datetime.fromisoformat(to_date).timestamp())
                sql += " AND f.mtime <= ?"
                params.append(to_ts)

            if tag:
                sql += " AND f.file_id IN (SELECT file_id FROM tags WHERE tag = ?)"
                params.append(tag)

            sql += " ORDER BY f.mtime DESC LIMIT ?"
            params.append(limit)

            cur = c.execute(sql, params)
            rows = cur.fetchall()
            return [
                {
                    "file_id": r[0],
                    "path": r[1],
                    "type": r[2],
                    "size_bytes": r[3],
                    "mtime": r[4],
                }
                for r in rows
            ]

    def stat(self, file_id: str) -> Optional[dict]:
        """Get metadata for a specific file."""
        with self._lock, self._conn() as c:
            cur = c.execute(
                "SELECT file_id, path, type, size_bytes, hash_sha256, mtime, indexed_at, chunks, suggested_move FROM files WHERE file_id = ?",
                (file_id,),
            )
            r = cur.fetchone()
            if not r:
                return None
            return {
                "file_id": r[0], "path": r[1], "type": r[2],
                "size_bytes": r[3], "hash_sha256": r[4], "mtime": r[5],
                "indexed_at": r[6], "chunks": r[7], "suggested_move": r[8],
            }

    def tag(self, action: str, file_id: Optional[str] = None, tag: Optional[str] = None) -> dict:
        """Add/remove/list tags."""
        with self._lock, self._conn() as c:
            if action == "add" and file_id and tag:
                c.execute("INSERT OR IGNORE INTO tags (file_id, tag) VALUES (?, ?)", (file_id, tag))
                c.commit()
                return {"ok": True, "action": "add", "file_id": file_id, "tag": tag}
            elif action == "remove" and file_id and tag:
                c.execute("DELETE FROM tags WHERE file_id = ? AND tag = ?", (file_id, tag))
                c.commit()
                return {"ok": True, "action": "remove", "file_id": file_id, "tag": tag}
            elif action == "list" and file_id:
                cur = c.execute("SELECT tag FROM tags WHERE file_id = ?", (file_id,))
                return {"tags": [r[0] for r in cur.fetchall()]}
            elif action == "list_all":
                cur = c.execute("SELECT DISTINCT tag FROM tags ORDER BY tag")
                return {"tags": [r[0] for r in cur.fetchall()]}
            else:
                return {"error": f"invalid action: {action}"}


class FilesystemMCPServer:
    def __init__(self, db_path: Optional[str] = None):
        self.db = FileDB(db_path or os.environ.get("DB_PATH", "files.db"))

    def find(self, **kwargs):
        return {"results": self.db.find(**kwargs)}

    def stat(self, file_id: str):
        result = self.db.stat(file_id)
        return {"file": result} if result else {"error": "not found"}

    def tag(self, action: str, **kwargs):
        return self.db.tag(action, **kwargs)


def main():
    import json
    import sys
    server = FilesystemMCPServer()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if req.get("method") == "tools/call":
                tool = req["params"]["name"]
                args = req["params"].get("arguments", {})
                if hasattr(server, tool):
                    result = getattr(server, tool)(**args)
                    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}))
                else:
                    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": f"unknown tool: {tool}"}))
            elif req.get("method") == "initialize":
                print(json.dumps({
                    "jsonrpc": "2.0", "id": req["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "filesystem-search", "version": "1.0.0"},
                        "capabilities": {"tools": {}}
                    }
                }))
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "error": str(e)}))


if __name__ == "__main__":
    main()
