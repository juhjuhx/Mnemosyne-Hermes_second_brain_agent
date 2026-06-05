#!/usr/bin/env python3
"""
indexer.py — Single-worker file indexer for the Personal AI Second Brain.

v4 invariant: ONE worker, ONE file at a time. Parallelism is OK at the
*embedding* step (one file → N chunks → N embed calls in batch), NOT at
the *file* step.

Usage:
    python indexer.py --config indexer_config.yaml [--dry-run]
"""

import argparse
import hashlib
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Optional

import requests
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("indexer")


class Config:
    """Load and validate indexer config."""

    def __init__(self, path: str):
        with open(path) as f:
            raw = yaml.safe_load(f)
        self.inbox = Path(raw["inbox"]).expanduser()
        self.archive = Path(raw["archive"]).expanduser()
        self.qdrant_url = raw["qdrant_url"]
        self.ollama_url = raw["ollama_url"]
        self.collection = raw.get("collection", "second_brain")
        self.workers = raw.get("workers", 1)  # v3 invariant
        if self.workers != 1:
            raise ValueError("workers must be 1 (v3 invariant)")
        self.dry_run = raw.get("dry_run", False)


class FileDB:
    """SQLite-backed metadata store for indexed files."""

    def __init__(self, db_path: str = "files.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                file_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                type TEXT NOT NULL,
                size_bytes INTEGER,
                hash_sha256 TEXT,
                mtime INTEGER,
                indexed_at INTEGER,
                chunks INTEGER DEFAULT 0,
                suggested_move TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                file_id TEXT REFERENCES files(file_id),
                chunk_index INTEGER,
                chunk_type TEXT,
                text_content TEXT,
                point_id INTEGER
            )
            """
        )
        self.conn.commit()

    def file_exists(self, path: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM files WHERE path=?", (path,))
        return cur.fetchone() is not None

    def record_file(self, file_id: str, path: str, type_: str, size: int,
                    sha256: str, mtime: int, chunks: int):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO files
            (file_id, path, type, size_bytes, hash_sha256, mtime, indexed_at, chunks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, path, type_, size, sha256, mtime, int(time.time()), chunks),
        )
        self.conn.commit()

    def record_chunk(self, chunk_id: str, file_id: str, idx: int,
                     chunk_type: str, text: Optional[str], point_id: int):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO chunks
            (chunk_id, file_id, chunk_index, chunk_type, text_content, point_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, file_id, idx, chunk_type, text, point_id),
        )
        self.conn.commit()


def detect_type(path: Path) -> str:
    """Detect file type from extension."""
    ext = path.suffix.lower()
    if ext in {".md", ".txt", ".pdf", ".docx", ".rtf"}:
        return "text"
    if ext in {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}:
        return "image"
    if ext in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        return "video"
    if ext in {".mp3", ".m4a", ".wav", ".flac", ".ogg"}:
        return "audio"
    return "unknown"


def sha256_of(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def embed_text(text: str, ollama_url: str) -> list:
    """Call Ollama for text embedding (768-dim for nomic-embed-text)."""
    r = requests.post(
        f"{ollama_url}/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def upsert_qdrant(qdrant_url: str, collection: str, point_id: int,
                  vectors: dict, payload: dict):
    """Upsert a point with named vectors to Qdrant."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct
    client = QdrantClient(url=qdrant_url)
    client.upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vectors, payload=payload)],
    )


def chunk_text(text: str, max_tokens: int = 512) -> list:
    """Split text by paragraph, capped at max_tokens."""
    paragraphs = text.split("\n\n")
    chunks = []
    current = []
    current_tokens = 0
    for p in paragraphs:
        tokens = len(p.split())
        if current_tokens + tokens > max_tokens and current:
            chunks.append("\n\n".join(current))
            current = [p]
            current_tokens = tokens
        else:
            current.append(p)
            current_tokens += tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def process_text_file(path: Path, cfg: Config, db: FileDB) -> int:
    """Process a text file. Returns number of chunks indexed."""
    text = path.read_text(errors="ignore")
    chunks = chunk_text(text)
    file_id = sha256_of(path)[:16]
    n_chunks = 0
    for idx, chunk in enumerate(chunks):
        if cfg.dry_run:
            log.info(f"[DRY-RUN] chunk {idx}: {chunk[:80]}...")
            continue
        vec = embed_text(chunk, cfg.ollama_url)
        point_id = int(hash(f"{file_id}:{idx}") % (2**63))
        upsert_qdrant(
            cfg.qdrant_url, cfg.collection, point_id,
            vectors={"text_vec": vec},
            payload={"file_id": file_id, "chunk_index": idx, "text": chunk[:500]},
        )
        db.record_chunk(f"{file_id}:{idx}", file_id, idx, "paragraph", chunk[:1000], point_id)
        n_chunks += 1
    db.record_file(file_id, str(path), "text", path.stat().st_size,
                   sha256_of(path), int(path.stat().st_mtime), n_chunks)
    return n_chunks


def process_file(path: Path, cfg: Config, db: FileDB) -> int:
    """Dispatch by type. Returns chunks indexed."""
    type_ = detect_type(path)
    log.info(f"Processing: {path} (type={type_})")
    if type_ == "text":
        return process_text_file(path, cfg, db)
    elif type_ in {"image", "video", "audio"}:
        # Full pipelines for these types are in Phase 2 expansion.
        # For v4 baseline, just record metadata; embed in Phase 2.x.
        if cfg.dry_run:
            log.info(f"[DRY-RUN] {type_}: {path}")
            return 0
        file_id = sha256_of(path)[:16]
        db.record_file(file_id, str(path), type_, path.stat().st_size,
                       sha256_of(path), int(path.stat().st_mtime), 0)
        return 0
    else:
        log.warning(f"Unknown type for {path}, skipping")
        return 0


class InboxHandler(FileSystemEventHandler):
    """FSEvents / inotify handler — enqueue new files."""

    def __init__(self, queue: Queue, db: FileDB):
        self.queue = queue
        self.db = db

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self.db.file_exists(str(path)):
            self.queue.put(path)
            log.info(f"Enqueued: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = Config(args.config)
    if args.dry_run:
        cfg.dry_run = True

    db = FileDB()
    queue = Queue(maxsize=100)

    # Single worker (v3 invariant)
    def worker():
        while True:
            path = queue.get()
            try:
                n = process_file(path, cfg, db)
                log.info(f"Indexed {n} chunks: {path}")
            except Exception as e:
                log.exception(f"Failed: {path}: {e}")
            finally:
                queue.task_done()

    Thread(target=worker, daemon=True).start()

    # Watcher
    handler = InboxHandler(queue, db)
    observer = Observer()
    observer.schedule(handler, str(cfg.inbox), recursive=False)
    observer.start()
    log.info(f"Watching: {cfg.inbox}")

    # Graceful shutdown
    def shutdown(signum, frame):
        log.info("Shutting down...")
        observer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
