"""
conftest.py — Shared pytest fixtures and path setup.

This file is the entrypoint for pytest discovery. It:
1. Adds the relevant src/ subdirs to sys.path so the test files
   can import from `indexer`, `qdrant_server`, etc. without
   requiring a full editable install.
2. Provides shared fixtures: temp dirs, dummy files, mock HTTP,
   ephemeral SQLite, ephemeral Qdrant (in-memory or test collection).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# --------------------------------------------------------------------------- #
# Path setup
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "src" / "scripts"
HERMES_SKILLS_DIR = REPO_ROOT / "src" / "hermes_skills"

# Add the subdirs that contain importable modules to sys.path.
for p in (SCRIPTS_DIR,):
    sys.path.insert(0, str(p))

# Per-skill sys.path entries: each skill is importable as e.g.
#   from qdrant_server import QdrantMCPServer
# because the server module lives at <skill>/src/<skill>_server.py.
for skill in ("qdrant-search", "filesystem-search", "video-slice"):
    sys.path.insert(0, str(HERMES_SKILLS_DIR / skill / "src"))


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmp_dir():
    """A fresh temp directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory(prefix="ai_brain_test_") as d:
        yield Path(d)


@pytest.fixture
def sample_text_file(tmp_dir):
    """A small .md file with two paragraphs (chunkable)."""
    p = tmp_dir / "note.md"
    p.write_text(
        "First paragraph about hermes agent and how it orchestrates skills.\n\n"
        "Second paragraph about mnemosyne and how it stores long-term memory.\n\n"
        "Third paragraph about qdrant and how it indexes named vectors.\n"
    )
    return p


@pytest.fixture
def sample_image_file(tmp_dir):
    """A minimal valid JPEG (1x1 white pixel)."""
    p = tmp_dir / "photo.jpg"
    p.write_bytes(
        # Smallest valid JPEG (white 1x1 pixel)
        bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
            "07090908"
            "0a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837"
            "292c30313434341f27393d38323c2e333432ffc0000b08000100010101110000ff"
            "c4001f0000010501010101010100000000000000000102030405060708090a0bff"
            "c4001f0100030101010101010101010000000000000102030405060708090a0bff"
            "da0008010100003f00fb0000ffd9"
        )
    )
    return p


@pytest.fixture
def fake_ollama_embedding(monkeypatch):
    """Patch requests.post to return a deterministic 768-dim embedding."""
    captured: dict = {}

    def fake_post(url, json=None, timeout=None, **_):
        captured["url"] = url
        captured["payload"] = json

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                if "embeddings" in url:
                    # Deterministic vector from the prompt
                    prompt = (json or {}).get("prompt", "")
                    seed = sum(ord(c) for c in prompt) % 1000
                    return {
                        "embedding": [
                            (seed * (i + 1) % 100) / 100.0 for i in range(768)
                        ]
                    }
                return {"embedding": [0.0] * 768}

        return R()

    monkeypatch.setattr("requests.post", fake_post)
    return captured


@pytest.fixture
def in_memory_qdrant():
    """An in-memory stand-in for QdrantClient used by the qdrant-search skill."""
    client = MagicMock()

    store: dict = {}  # point_id -> (vectors, payload)

    def upsert(collection_name, points, **_):
        for pt in points:
            store[pt.id] = (pt.vector, pt.payload)

    def search(
        collection_name, query_vector, limit, query_filter=None, with_payload=True, **_
    ):
        name, vec = query_vector
        results = []
        for pid, (vectors, payload) in store.items():
            if name not in vectors:
                continue
            v = vectors[name]
            # Cosine similarity
            num = sum(a * b for a, b in zip(v, vec))
            den = (sum(a * a for a in v) ** 0.5) * (
                sum(b * b for b in vec) ** 0.5 + 1e-9
            )
            score = num / den
            # Apply filter
            if query_filter and query_filter.must:
                ok = True
                for cond in query_filter.must:
                    if payload.get(cond.key) != cond.match.value:
                        ok = False
                        break
                if not ok:
                    continue
            results.append(MagicMock(score=score, payload=payload))
        results.sort(key=lambda r: -r.score)
        return results[:limit]

    client.upsert = upsert
    client.search = search
    return client, store
