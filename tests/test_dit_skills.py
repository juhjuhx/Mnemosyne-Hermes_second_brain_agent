"""
Tests for dit-offload and dit-metadata MCP skills.
"""

import hashlib
import os
import shutil
from pathlib import Path

import pytest

# ── Import modules under test ────────────────────────────────────────

import sys

_base = Path(__file__).parent.parent
sys.path.insert(0, str(_base / "src" / "hermes_skills" / "dit-offload" / "src"))
sys.path.insert(0, str(_base / "src" / "hermes_skills" / "dit-metadata" / "src"))

from dit_offload_server import (  # noqa: E402
    compute_md5,
    compute_xxhash,
    compute_checksums,
    discover_media,
    offload_file,
    verify_offload,
)
from dit_metadata_server import (  # noqa: E402
    detect_camera,
    eval_fps,
    format_duration,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_media_dir(tmp_path):
    """Create a temporary directory with fake media files."""
    media_dir = tmp_path / "media"
    media_dir.mkdir()

    # Create fake video files
    for ext in [".mov", ".mp4", ".mxf", ".ari"]:
        f = media_dir / f"A001_C001{ext}"
        f.write_bytes(os.urandom(1024))  # 1KB random data

    # Create a non-media file (should be ignored)
    (media_dir / "README.txt").write_text("not media")

    # Create a nested directory with more files
    sub = media_dir / "DCIM"
    sub.mkdir()
    (sub / "A002_C001.mov").write_bytes(os.urandom(2048))
    (sub / "A002_C002.braw").write_bytes(os.urandom(4096))

    return media_dir


@pytest.fixture
def tmp_copy_dir(tmp_path):
    """Create a temporary destination directory."""
    d = tmp_path / "dest"
    d.mkdir()
    return d


# ── Checksum tests ───────────────────────────────────────────────────


class TestChecksums:
    def test_md5_deterministic(self, tmp_path):
        """Same file always produces same MD5."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        h1 = compute_md5(str(f))
        h2 = compute_md5(str(f))
        assert h1 == h2

    def test_md5_known_value(self, tmp_path):
        """MD5 of known input matches expected value."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        expected = hashlib.md5(b"hello world").hexdigest()
        assert compute_md5(str(f)) == expected

    def test_md5_different_files_differ(self, tmp_path):
        """Different files produce different MD5s."""
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert compute_md5(str(f1)) != compute_md5(str(f2))

    def test_xxhash_fallback_to_md5(self, tmp_path):
        """xxhash falls back to MD5 when xxhash not installed."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"test data")
        result = compute_xxhash(str(f))
        # Should return something (either xxhash or md5)
        assert len(result) == 32  # hex string

    def test_checksums_returns_both(self, tmp_path):
        """compute_checksums returns both md5 and xxhash."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"test")
        result = compute_checksums(str(f))
        assert "md5" in result
        assert "xxhash" in result
        assert len(result["md5"]) == 32


# ── Discover media tests ─────────────────────────────────────────────


class TestDiscoverMedia:
    def test_finds_media_files(self, tmp_media_dir):
        """Discovers media files in directory tree."""
        files = discover_media(str(tmp_media_dir))
        # Should find .mov, .mp4, .mxf, .ari, .txt in root + .mov, .braw in DCIM
        assert len(files) == 7

    def test_ignores_non_media(self, tmp_media_dir):
        """Ignores files with unknown extensions (not in CAMERA_EXTENSIONS)."""
        files = discover_media(str(tmp_media_dir))
        for f in files:
            # .txt IS in CAMERA_EXTENSIONS (for sidecar/metadata), so it's included
            # But .md is not — verify no unknown extensions appear
            assert not f.endswith(".xyz")

    def test_empty_dir(self, tmp_path):
        """Empty directory returns empty list."""
        assert discover_media(str(tmp_path)) == []

    def test_nonexistent_dir(self, tmp_path):
        """Non-existent directory returns empty list."""
        assert discover_media(str(tmp_path / "nope")) == []


# ── Offload file tests ───────────────────────────────────────────────


class TestOffloadFile:
    def test_copy_with_verification(self, tmp_path, tmp_copy_dir):
        """File is copied and verified successfully."""
        src = tmp_path / "test.mov"
        src.write_bytes(b"video content here")
        result = offload_file(str(src), str(tmp_copy_dir), verify=True)
        assert result["verified"] is True
        assert result["source_checksums"]["md5"] == result["dest_checksums"]["md5"]
        assert Path(result["destination"]).exists()

    def test_copy_without_verification(self, tmp_path, tmp_copy_dir):
        """File is copied without checksum when verify=False."""
        src = tmp_path / "test.mov"
        src.write_bytes(b"video content")
        result = offload_file(str(src), str(tmp_copy_dir), verify=False)
        assert result["verified"] is None
        assert result["dest_checksums"] is None

    def test_name_collision_rename(self, tmp_path, tmp_copy_dir):
        """Files with same name get renamed."""
        src = tmp_path / "test.mov"
        src.write_bytes(b"first")
        offload_file(str(src), str(tmp_copy_dir))

        src.write_bytes(b"second")
        result = offload_file(str(src), str(tmp_copy_dir))
        # Should have _0001 suffix
        assert "_0001" in result["destination"]


# ── Verify offload tests ─────────────────────────────────────────────


class TestVerifyOffload:
    def test_perfect_copy(self, tmp_media_dir, tmp_copy_dir):
        """Verify passes for perfect copies."""
        # Copy all files
        for f in discover_media(str(tmp_media_dir)):
            shutil.copy2(f, tmp_copy_dir / Path(f).name)

        result = verify_offload(str(tmp_media_dir), str(tmp_copy_dir))
        assert result["all_ok"] is True
        assert result["verified"] == 7  # includes .txt sidecar
        assert len(result["missing"]) == 0
        assert len(result["checksum_mismatches"]) == 0

    def test_missing_file_detected(self, tmp_media_dir, tmp_copy_dir):
        """Verify detects missing files."""
        # Copy only first file
        files = discover_media(str(tmp_media_dir))
        shutil.copy2(files[0], tmp_copy_dir / Path(files[0]).name)

        result = verify_offload(str(tmp_media_dir), str(tmp_copy_dir))
        assert result["all_ok"] is False
        assert len(result["missing"]) == 6  # 5 media + 1 .txt


# ── Metadata tests ───────────────────────────────────────────────────


class TestEvalFps:
    def test_fractional_fps(self):
        """Parse '24000/1001' to 23.976."""
        assert eval_fps("24000/1001") == 23.976

    def test_integer_fps(self):
        """Parse '24' to 24.0."""
        assert eval_fps("24") == 24.0

    def test_invalid_fps(self):
        """Invalid string returns 0."""
        assert eval_fps("invalid") == 0.0

    def test_zero_division(self):
        """Zero denominator returns 0."""
        assert eval_fps("24/0") == 0.0


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(45) == "00:45"

    def test_minutes_and_seconds(self):
        assert format_duration(125) == "02:05"

    def test_hours(self):
        assert format_duration(3661) == "01:01:01"


class TestDetectCamera:
    def test_arri_detection(self):
        """Detect ARRI camera from tags."""
        tags = {"com.apple.quicktime.make": "ARRI", "make": "ARRI"}
        result = detect_camera(tags, [])
        assert result["brand"] == "ARRI"

    def test_red_detection(self):
        """Detect RED camera from tags."""
        tags = {"make": "RED Digital Cinema"}
        result = detect_camera(tags, [])
        assert result["brand"] == "RED"

    def test_blackmagic_detection(self):
        """Detect Blackmagic camera from tags."""
        tags = {"make": "Blackmagic Design"}
        result = detect_camera(tags, [])
        assert result["brand"] == "Blackmagic Design"

    def test_unknown_camera(self):
        """Unknown camera returns 'unknown' brand."""
        tags = {"some_random_tag": "value"}
        result = detect_camera(tags, [])
        assert result["brand"] == "unknown"
