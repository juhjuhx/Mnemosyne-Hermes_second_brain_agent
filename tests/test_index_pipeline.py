"""
test_index_pipeline.py — Tests for the v4 single-worker file indexer.

These tests cover the parts of indexer.py that don't require a live
Qdrant or Ollama instance: config validation, file-type detection,
chunking, SQLite metadata, and the InboxHandler enqueue logic.
"""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Config: workers=1 invariant
# --------------------------------------------------------------------------- #

def test_config_rejects_workers_greater_than_one(tmp_dir):
    """The v3 invariant says workers MUST be 1. Multi-worker must error."""
    from indexer import Config

    cfg_path = tmp_dir / "cfg.yaml"
    cfg_path.write_text(textwrap.dedent(f"""
        inbox: {tmp_dir}/inbox
        archive: {tmp_dir}/archive
        qdrant_url: http://127.0.0.1:6333
        ollama_url: http://127.0.0.1:11434
        workers: 4
    """))
    with pytest.raises(ValueError, match="workers must be 1"):
        Config(str(cfg_path))


def test_config_accepts_workers_one(tmp_dir):
    from indexer import Config

    cfg_path = tmp_dir / "cfg.yaml"
    cfg_path.write_text(textwrap.dedent(f"""
        inbox: {tmp_dir}/inbox
        archive: {tmp_dir}/archive
        qdrant_url: http://127.0.0.1:6333
        ollama_url: http://127.0.0.1:11434
        workers: 1
    """))
    cfg = Config(str(cfg_path))
    assert cfg.workers == 1


# --------------------------------------------------------------------------- #
# detect_type
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("filename,expected", [
    ("note.md", "text"),
    ("essay.txt", "text"),
    ("paper.pdf", "text"),
    ("letter.docx", "text"),
    ("photo.jpg", "image"),
    ("pic.jpeg", "image"),
    ("pic.png", "image"),
    ("iphone.heic", "image"),
    ("clip.mp4", "video"),
    ("movie.mov", "video"),
    ("recording.m4a", "audio"),
    ("song.mp3", "audio"),
    ("archive.zip", "unknown"),
    ("no_extension", "unknown"),
])
def test_detect_type(filename, expected):
    from indexer import detect_type
    assert detect_type(Path(filename)) == expected


# --------------------------------------------------------------------------- #
# chunk_text
# --------------------------------------------------------------------------- #

def test_chunk_text_splits_on_paragraph():
    from indexer import chunk_text
    text = "p1.\n\np2.\n\np3."
    chunks = chunk_text(text, max_tokens=100)
    assert len(chunks) == 1
    assert "p1" in chunks[0] and "p3" in chunks[0]


def test_chunk_text_caps_at_max_tokens():
    from indexer import chunk_text
    # 10 paragraphs of 50 words each; max_tokens=80 → should split
    paras = [f"paragraph {i} " + "word " * 50 for i in range(10)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, max_tokens=80)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.split()) <= 100  # allow some overflow tolerance


def test_chunk_text_empty_input():
    from indexer import chunk_text
    assert chunk_text("") == [] or chunk_text("") == [""]


# --------------------------------------------------------------------------- #
# FileDB (SQLite)
# --------------------------------------------------------------------------- #

def test_filedb_file_exists_false_initially(tmp_dir):
    from indexer import FileDB
    db = FileDB(str(tmp_dir / "files.db"))
    assert db.file_exists("/nope.jpg") is False


def test_filedb_record_then_exists(tmp_dir):
    from indexer import FileDB
    db = FileDB(str(tmp_dir / "files.db"))
    db.record_file("abc123", "/x.md", "text", 100, "deadbeef", 1700000000, 3)
    assert db.file_exists("/x.md") is True


def test_filedb_record_chunk(tmp_dir):
    from indexer import FileDB
    db = FileDB(str(tmp_dir / "files.db"))
    db.record_file("abc", "/x.md", "text", 100, "h", 1, 1)
    db.record_chunk("abc:0", "abc", 0, "paragraph", "hello world", 12345)
    cur = db.conn.execute("SELECT chunk_id, text_content, point_id FROM chunks WHERE file_id=?", ("abc",))
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "abc:0"
    assert rows[0][1] == "hello world"
    assert rows[0][2] == 12345


def test_filedb_record_file_upsert(tmp_dir):
    """record_file uses INSERT OR REPLACE — calling twice with the same
    file_id should not raise and should keep the row count at 1."""
    from indexer import FileDB
    db = FileDB(str(tmp_dir / "files.db"))
    db.record_file("abc", "/x.md", "text", 100, "h", 1, 1)
    db.record_file("abc", "/x.md", "text", 200, "h2", 2, 2)  # re-record
    cur = db.conn.execute("SELECT COUNT(*) FROM files WHERE file_id=?", ("abc",))
    assert cur.fetchone()[0] == 1


# --------------------------------------------------------------------------- #
# embed_text + dry-run flow
# --------------------------------------------------------------------------- #

def test_process_text_file_dry_run_no_qdrant_call(tmp_dir, sample_text_file):
    """In dry-run mode, no network calls should happen."""
    from indexer import Config, FileDB, process_text_file

    cfg = MagicMock(spec=Config)
    cfg.dry_run = True
    cfg.qdrant_url = "http://nope"
    cfg.ollama_url = "http://nope"
    cfg.collection = "x"

    db = MagicMock(spec=FileDB)
    n = process_text_file(sample_text_file, cfg, db)
    assert n == 0
    db.record_file.assert_not_called()


def test_process_text_file_real_flow(monkeypatch, tmp_dir, sample_text_file,
                                      fake_ollama_embedding, in_memory_qdrant):
    """Full happy path: read text → embed → upsert Qdrant → record SQLite."""
    from indexer import Config, FileDB, process_text_file

    client, store = in_memory_qdrant

    monkeypatch.setattr("indexer.upsert_qdrant",
                        lambda *a, **kw: client.upsert(*a, **kw))

    cfg = MagicMock(spec=Config)
    cfg.dry_run = False
    cfg.qdrant_url = "http://x"
    cfg.ollama_url = "http://x"
    cfg.collection = "second_brain"

    db = FileDB(str(tmp_dir / "files.db"))
    n = process_text_file(sample_text_file, cfg, db)
    assert n >= 1
    assert len(store) >= 1
    # Each point should have a text_vec
    for pid, (vecs, payload) in store.items():
        assert "text_vec" in vecs
        assert len(vecs["text_vec"]) == 768


# --------------------------------------------------------------------------- #
# InboxHandler — only enqueue unseen files
# --------------------------------------------------------------------------- #

def test_inbox_handler_only_enqueues_unseen(tmp_dir):
    from indexer import FileDB, InboxHandler
    db = MagicMock(spec=FileDB)
    db.file_exists.return_value = True  # simulate already-indexed

    q = Queue()
    h = InboxHandler(q, db)
    evt = MagicMock()
    evt.is_directory = False
    evt.src_path = str(tmp_dir / "already_indexed.jpg")

    h.on_created(evt)
    assert q.qsize() == 0


def test_inbox_handler_enqueues_new_file(tmp_dir):
    from indexer import FileDB, InboxHandler
    db = MagicMock(spec=FileDB)
    db.file_exists.return_value = False

    q = Queue()
    h = InboxHandler(q, db)
    evt = MagicMock()
    evt.is_directory = False
    evt.src_path = str(tmp_dir / "new_file.jpg")

    h.on_created(evt)
    assert q.qsize() == 1


def test_inbox_handler_ignores_directories(tmp_dir):
    from indexer import FileDB, InboxHandler
    db = MagicMock(spec=FileDB)
    q = Queue()
    h = InboxHandler(q, db)

    evt = MagicMock()
    evt.is_directory = True
    h.on_created(evt)
    assert q.qsize() == 0


# --------------------------------------------------------------------------- #
# SHA-256 hashing is stable
# --------------------------------------------------------------------------- #

def test_sha256_of_is_deterministic(tmp_dir):
    from indexer import sha256_of
    p = tmp_dir / "a.bin"
    p.write_bytes(b"hello world")
    h1 = sha256_of(p)
    h2 = sha256_of(p)
    assert h1 == h2
    assert len(h1) == 64
    # Known SHA-256 of "hello world"
    assert h1 == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
