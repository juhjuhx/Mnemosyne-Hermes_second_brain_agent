"""
tests for the qdrant-search skill.
"""

import pytest

from .src.qdrant_server import QdrantMCPServer


@pytest.fixture
def server(monkeypatch):
    """Create a server pointed at a test collection."""
    # In real tests, we'd use a separate test collection;
    # for v4 baseline, we mock the Qdrant client.
    s = QdrantMCPServer(
        qdrant_url="http://test-qdrant:6333",
        collection="second_brain_test",
        embedding_url="http://test-ollama:11434",
    )
    return s


def test_embed_text_calls_ollama(monkeypatch, server):
    """embed_text should call Ollama's /api/embeddings endpoint."""
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["payload"] = json

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"embedding": [0.1] * 768}

        return R()

    monkeypatch.setattr("requests.post", fake_post)
    vec = server.embed_text("hello world")
    assert len(vec) == 768
    assert "test-ollama:11434/api/embeddings" in captured["url"]
    assert captured["payload"]["prompt"] == "hello world"


def test_build_filter_empty():
    """build_filter should return None for empty dict."""
    from .src.qdrant_server import QdrantMCPServer

    s = QdrantMCPServer()
    assert s.build_filter({}) is None
    assert s.build_filter(None) is None


def test_build_filter_with_conditions():
    """build_filter should produce a Qdrant Filter with must-conditions."""
    from .src.qdrant_server import QdrantMCPServer

    s = QdrantMCPServer()
    flt = s.build_filter({"tag": "family", "year": 2024})
    assert flt is not None
    assert len(flt.must) == 2


def test_search_with_empty_query(server):
    """search with empty query should return empty results, not crash."""
    result = server.search(query="", top_k=5)
    assert result["results"] == []
