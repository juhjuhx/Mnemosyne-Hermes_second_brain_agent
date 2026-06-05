"""
test_mcp_servers.py — Tests for the MCP stdio transport used by all 3 skills.

The three skills (qdrant-search, filesystem-search, video-slice) all
expose their functionality over MCP via stdin/stdout JSON-RPC. This file
exercises the stdio loop without actually shelling out to the binary.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# --------------------------------------------------------------------------- #
# qdrant-search: stdio loop
# --------------------------------------------------------------------------- #

def test_qdrant_initialize_handshake(monkeypatch):
    from qdrant_server import QdrantMCPServer

    # Replace stdin with a single initialize request
    initialize_req = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize"
    }) + "\n"
    fake_stdin = io.StringIO(initialize_req)
    fake_stdout = io.StringIO()

    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdout", fake_stdout)

    # Patch the server to avoid network
    monkeypatch.setattr(QdrantMCPServer, "__init__",
                        lambda self: None)

    from qdrant_server import main
    main()

    out = fake_stdout.getvalue()
    assert "jsonrpc" in out
    assert "qdrant-search" in out
    assert "2024-11-05" in out  # protocol version


def test_qdrant_search_returns_jsonrpc_envelope(monkeypatch):
    from qdrant_server import QdrantMCPServer

    request = json.dumps({
        "jsonrpc": "2.0", "id": 7,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": "hi"}},
    }) + "\n"
    fake_stdin = io.StringIO(request)
    fake_stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdout", fake_stdout)

    # Mock the server instance to return a canned result
    inst = QdrantMCPServer.__new__(QdrantMCPServer)
    inst.search = lambda **kw: {"results": [{"file_id": "abc", "score": 0.9}]}
    monkeypatch.setattr(QdrantMCPServer, "__init__", lambda self: None)
    monkeypatch.setattr(QdrantMCPServer, "search", inst.search)

    from qdrant_server import main
    main()

    out = fake_stdout.getvalue()
    response = json.loads(out.strip())
    assert response["id"] == 7
    assert "result" in response
    assert response["result"]["results"][0]["file_id"] == "abc"


# --------------------------------------------------------------------------- #
# filesystem-search: stdio loop
# --------------------------------------------------------------------------- #

def test_filesystem_unknown_tool_returns_error(monkeypatch, tmp_dir):
    from filesystem_server import FilesystemMCPServer, FileDB

    db_path = tmp_dir / "files.db"
    db = FileDB(str(db_path))

    request = json.dumps({
        "jsonrpc": "2.0", "id": 11,
        "method": "tools/call",
        "params": {"name": "nope", "arguments": {}},
    }) + "\n"
    fake_stdin = io.StringIO(request)
    fake_stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdout", fake_stdout)

    monkeypatch.setattr(FilesystemMCPServer, "__init__", lambda self: None)
    monkeypatch.setattr(FilesystemMCPServer, "__init__", lambda self, db_path=None: None)
    inst = FilesystemMCPServer.__new__(FilesystemMCPServer)

    # Force the dispatcher to fail on unknown tools
    with patch.object(FilesystemMCPServer, "find",
                      side_effect=AttributeError("nope")):
        from filesystem_server import main
        # Patch builtins.hasattr to return False for 'nope'
        orig_hasattr = hasattr
        def fake_hasattr(obj, name):
            if name == "nope":
                return False
            return orig_hasattr(obj, name)
        with patch("filesystem_server.hasattr", fake_hasattr):
            main()

    out = fake_stdout.getvalue()
    response = json.loads(out.strip())
    assert "error" in response
    assert "unknown tool" in response["error"]


# --------------------------------------------------------------------------- #
# video-slice: stdio loop — gracefully reports missing video
# --------------------------------------------------------------------------- #

def test_video_slice_missing_file_returns_error_dict(monkeypatch):
    from video_slice_server import VideoSliceMCPServer

    request = json.dumps({
        "jsonrpc": "2.0", "id": 21,
        "method": "tools/call",
        "params": {"name": "slice", "arguments": {"video_path": "/no/such.mp4"}},
    }) + "\n"
    fake_stdin = io.StringIO(request)
    fake_stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdout", fake_stdout)

    from video_slice_server import main
    main()

    out = fake_stdout.getvalue()
    response = json.loads(out.strip())
    assert response["id"] == 21
    assert "error" in response["result"]


# --------------------------------------------------------------------------- #
# Cross-skill: all three servers emit valid JSON-RPC envelopes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("module,expected_name", [
    ("qdrant_server", "qdrant-search"),
    ("filesystem_server", "filesystem-search"),
    ("video_slice_server", "video-slice"),
])
def test_all_skills_initialize(module, expected_name, monkeypatch):
    """Every skill must respond to `initialize` with its name and version."""
    import importlib
    mod = importlib.import_module(module)
    main_fn = getattr(mod, "main")

    request = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize"}) + "\n"
    fake_stdin = io.StringIO(request)
    fake_stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdout", fake_stdout)

    main_fn()

    out = fake_stdout.getvalue()
    response = json.loads(out.strip())
    assert response["result"]["serverInfo"]["name"] == expected_name
    assert "version" in response["result"]["serverInfo"]
