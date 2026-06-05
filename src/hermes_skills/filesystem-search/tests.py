"""Tests for filesystem-search skill."""

import os
import tempfile

import pytest

from .src.filesystem_server import FileDB


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    d = FileDB(path)
    # Seed
    d._conn().executescript("""
        INSERT INTO files (file_id, path, type, size_bytes, mtime)
        VALUES
          ('a1', '/path/to/photo1.jpg', 'image', 1000, 1721000000),
          ('a2', '/path/to/photo2.jpg', 'image', 2000, 1721100000),
          ('a3', '/path/to/note.md', 'text', 500, 1721200000);
        INSERT INTO tags (file_id, tag) VALUES
          ('a1', 'family'), ('a1', 'beach'),
          ('a2', 'family'),
          ('a3', 'work');
    """)
    d._conn().commit()
    yield d
    os.unlink(path)


def test_find_by_filename(db):
    results = db.find(filename="photo")
    assert len(results) == 2
    assert all("photo" in r["path"] for r in results)


def test_find_by_type(db):
    results = db.find(type_="image")
    assert len(results) == 2
    results = db.find(type_="text")
    assert len(results) == 1


def test_find_by_tag(db):
    results = db.find(tag="family")
    assert len(results) == 2
    results = db.find(tag="beach")
    assert len(results) == 1
    assert results[0]["file_id"] == "a1"


def test_find_by_date_range(db):
    results = db.find(from_date="2024-07-15", to_date="2024-07-16")
    assert len(results) == 2  # a1 and a2 are in this range; a3 is later


def test_find_limit(db):
    results = db.find(limit=1)
    assert len(results) == 1


def test_stat_existing(db):
    result = db.stat("a1")
    assert result is not None
    assert result["path"] == "/path/to/photo1.jpg"


def test_stat_nonexistent(db):
    result = db.stat("nonexistent")
    assert result is None


def test_tag_add(db):
    result = db.tag("add", file_id="a3", tag="important")
    assert result["ok"]


def test_tag_remove(db):
    db.tag("add", file_id="a1", tag="temp")
    db.tag("remove", file_id="a1", tag="temp")
    tags = db.tag("list", file_id="a1")["tags"]
    assert "temp" not in tags


def test_tag_list_all(db):
    result = db.tag("list_all")
    assert set(result["tags"]) == {"family", "beach", "work"}
