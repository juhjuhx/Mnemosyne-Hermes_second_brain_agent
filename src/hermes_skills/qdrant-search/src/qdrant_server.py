"""
qdrant_server.py — MCP server exposing Qdrant vector search as a tool.

This is the implementation behind the `qdrant-search` skill.
"""

import os
from typing import Optional

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue


class QdrantMCPServer:
    def __init__(
        self,
        qdrant_url: Optional[str] = None,
        collection: Optional[str] = None,
        embedding_url: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        self.qdrant_url = qdrant_url or os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
        self.collection = collection or os.environ.get("COLLECTION", "second_brain")
        self.embedding_url = embedding_url or os.environ.get("EMBEDDING_URL", "http://127.0.0.1:11434")
        self.embedding_model = embedding_model or os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        self.client = QdrantClient(url=self.qdrant_url)

    def embed_text(self, text: str) -> list:
        """Embed a text query via Ollama."""
        r = requests.post(
            f"{self.embedding_url}/api/embeddings",
            json={"model": self.embedding_model, "prompt": text},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["embedding"]

    def build_filter(self, filter_dict: dict) -> Optional[Filter]:
        """Convert a flat dict filter to Qdrant Filter."""
        if not filter_dict:
            return None
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filter_dict.items()
        ]
        return Filter(must=conditions)

    def search(
        self,
        query: str,
        top_k: int = 10,
        modality: str = "both",
        filter_dict: Optional[dict] = None,
    ) -> dict:
        """Search the collection for documents similar to the query."""
        if not query.strip():
            return {"results": [], "error": "empty query"}

        vec = self.embed_text(query)
        flt = self.build_filter(filter_dict or {})

        if modality == "text":
            vector_name = "text_vec"
            vec_param = {"text_vec": vec}
        elif modality == "image":
            vector_name = "image_vec"
            vec_param = {"image_vec": vec}
        else:  # both — search text for now (text is more general)
            vector_name = "text_vec"
            vec_param = {"text_vec": vec}

        hits = self.client.search(
            collection_name=self.collection,
            query_vector=(vector_name, vec),
            limit=top_k,
            query_filter=flt,
            with_payload=True,
        )

        return {
            "results": [
                {
                    "file_id": h.payload.get("file_id"),
                    "score": h.score,
                    "modality": h.payload.get("modality", "unknown"),
                    "preview": h.payload.get("text", h.payload.get("path", ""))[:200],
                    "path": h.payload.get("path"),
                }
                for h in hits
            ]
        }

    def upsert(
        self,
        file_id: str,
        text_vec: Optional[list] = None,
        image_vec: Optional[list] = None,
        payload: Optional[dict] = None,
    ):
        """Upsert a point with named vectors. Used by the indexer."""
        from qdrant_client.models import PointStruct
        vectors = {}
        if text_vec is not None:
            vectors["text_vec"] = text_vec
        if image_vec is not None:
            vectors["image_vec"] = image_vec
        if not vectors:
            raise ValueError("at least one vector required")
        point_id = int(hash(file_id) % (2**63))
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=point_id, vector=vectors, payload=payload or {})],
        )


# MCP entrypoint (when run as `python -m src.mcp_servers.qdrant_server`)
def main():
    import json
    import sys
    server = QdrantMCPServer()
    # Minimal stdio MCP loop
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if req.get("method") == "tools/call":
                args = req.get("params", {}).get("arguments", {})
                result = server.search(**args)
                print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}))
            elif req.get("method") == "initialize":
                print(json.dumps({
                    "jsonrpc": "2.0", "id": req["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "qdrant-search", "version": "1.0.0"},
                        "capabilities": {"tools": {}}
                    }
                }))
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "error": str(e)}))


if __name__ == "__main__":
    main()
