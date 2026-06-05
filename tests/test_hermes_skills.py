"""
test_hermes_skills.py — End-to-end integration test for the three skills.

Spawns each skill's MCP server as a subprocess, sends a real JSON-RPC
request over stdin, and asserts the response. Requires:
  - python3 on PATH
  - the `requests` package
  - a writable temp dir for filesystem-search's sqlite

These tests are skipped automatically if the skills are not importable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "src" / "hermes_skills"

# Map skill directory name → module name. The directory name uses
# kebab-case (e.g. "qdrant-search") but the Python module uses
# snake_case minus the noun (e.g. "qdrant_server", not "qdrant_search_server").
SKILL_TO_MODULE = {
    "qdrant-search": "qdrant_server",
    "filesystem-search": "filesystem_server",
    "video-slice": "video_slice_server",
}


def _spawn_skill(skill_name: str, db_path: Path = None) -> subprocess.Popen:
    """Launch a skill's MCP server and return the Popen handle."""
    skill_dir = SKILLS / skill_name
    src = skill_dir / "src"
    env = {
        "PYTHONPATH": str(src),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    if db_path is not None:
        env["DB_PATH"] = str(db_path)
    module_name = SKILL_TO_MODULE[skill_name]
    return subprocess.Popen(
        [sys.executable, "-c", f"from {module_name} import main; main()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )


def _rpc(p: subprocess.Popen, method: str, params: dict = None, id_: int = 1) -> dict:
    """Send one JSON-RPC request, read one JSON-RPC response."""
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    if not line:
        err = p.stderr.read()
        raise RuntimeError(f"no response; stderr: {err}")
    return json.loads(line)


# --------------------------------------------------------------------------- #
# Filesystem-search end-to-end
# --------------------------------------------------------------------------- #

def test_filesystem_search_initialize_and_find():
    if not shutil.which(sys.executable):
        pytest.skip("no python interpreter")
    db = Path(tempfile.gettempdir()) / "ai_brain_test_files.db"
    if db.exists():
        db.unlink()

    # Seed: create a tiny DB with a few rows
    import sqlite3
    con = sqlite3.connect(str(db))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            file_id TEXT PRIMARY KEY, path TEXT, type TEXT,
            size_bytes INTEGER, hash_sha256 TEXT, mtime INTEGER,
            indexed_at INTEGER, chunks INTEGER DEFAULT 0, suggested_move TEXT
        );
        INSERT INTO files (file_id, path, type, size_bytes, mtime)
        VALUES ('a', '/x/photo.jpg', 'image', 100, 1700000000);
    """)
    con.commit()
    con.close()

    p = _spawn_skill("filesystem-search", db_path=db)
    try:
        init = _rpc(p, "initialize", id_=0)
        assert init["result"]["serverInfo"]["name"] == "filesystem-search"

        result = _rpc(p, "tools/call", {
            "name": "find",
            "arguments": {"filename": "photo", "limit": 5},
        }, id_=1)
        assert "results" in result["result"]
        assert len(result["result"]["results"]) == 1
        assert result["result"]["results"][0]["file_id"] == "a"
    finally:
        p.terminate()
        p.wait(timeout=3)
        if db.exists():
            db.unlink()


# --------------------------------------------------------------------------- #
# video-slice end-to-end (graceful on missing video)
# --------------------------------------------------------------------------- #

def test_video_slice_initialize_and_missing_video():
    if not shutil.which(sys.executable):
        pytest.skip("no python interpreter")
    p = _spawn_skill("video-slice")
    try:
        init = _rpc(p, "initialize", id_=0)
        assert init["result"]["serverInfo"]["name"] == "video-slice"

        result = _rpc(p, "tools/call", {
            "name": "slice",
            "arguments": {"video_path": "/no/such/video.mp4"},
        }, id_=1)
        assert "error" in result["result"]
    finally:
        p.terminate()
        p.wait(timeout=3)


# --------------------------------------------------------------------------- #
# qdrant-search initialize (we don't run a real Qdrant; just check handshake)
# --------------------------------------------------------------------------- #

def test_qdrant_search_initialize():
    if not shutil.which(sys.executable):
        pytest.skip("no python interpreter")
    p = _spawn_skill("qdrant-search")
    try:
        init = _rpc(p, "initialize", id_=0)
        assert init["result"]["serverInfo"]["name"] == "qdrant-search"
        assert init["result"]["protocolVersion"] == "2024-11-05"
    finally:
        p.terminate()
        p.wait(timeout=3)
