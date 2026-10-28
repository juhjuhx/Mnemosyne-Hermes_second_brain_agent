"""P12.2-C (Phase 4 C5/C6): Path Isolation — RED negative tests.

No original media may be overwritten, and unknown filesystem
semantics fail closed. Pure path-string logic (no I/O beyond
`os.path.realpath` on existing paths), so the negative matrix is
deterministic on this host.

Run: pytest tests/test_dit22_path_isolation.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

from path_isolation import (
    HARDWARE_BLOCKED,
    PathIsolationError,
    check_path_isolation,
    same_path,
    windows_stem_safe,
)

# ── C5: containment matrix ──────────────────────────────────────────


def test_p1_out_dir_same_as_source_dir_rejected(tmp_path: Path):
    src = tmp_path / "reel_001.mxf"
    src.write_bytes(b"x")
    with pytest.raises(PathIsolationError, match="same"):
        check_path_isolation(str(src), str(tmp_path))


def test_p2_out_dir_contains_the_source_rejected(tmp_path: Path):
    src = tmp_path / "nested" / "reel.mxf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    with pytest.raises(PathIsolationError, match="contains"):
        check_path_isolation(str(src), str(tmp_path))


def test_p3_scratch_layout_inside_source_dir_allowed_unprotected(tmp_path: Path):
    # out_dir a sibling-subdir of the source's own dir is the normal
    # DIT working layout (source + sibling output dir) and does NOT
    # clobber the source (job-namespaced artifact names). By default
    # (unprotected scratch volume) it is allowed:
    src = tmp_path / "media" / "reel.mxf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    assert check_path_isolation(str(src), str(tmp_path / "media" / "out")) is True


def test_p3b_protected_source_inside_rejected(tmp_path: Path):
    # The SAME topology on a PROTECTED volume (camera card / NAS that
    # must stay pristine) is rejected: staging/quarantine must not be
    # written into the source's own folder tree (C5).
    src = tmp_path / "media" / "reel.mxf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    with pytest.raises(PathIsolationError) as exc:
        check_path_isolation(
            str(src), str(tmp_path / "media" / "out"),
            protected_source=True,
        )
    assert "INSIDE" in str(exc.value)


def test_p4_symlink_alias_of_source_dir_rejected(tmp_path: Path):
    # macOS: /tmp -> /private/tmp (real symlink alias). An out_dir that
    # alias-normalizes onto the source's own directory => the "same"
    # rule fires (realpath equality), regardless of which alias was
    # supplied. The source file need not exist (string/realpath logic).
    src_file = "/private/tmp/somesomefile.bin"
    out_alias = "/tmp"
    assert os.path.realpath(out_alias) == "/private/tmp"
    with pytest.raises(PathIsolationError) as exc:
        check_path_isolation(src_file, out_alias)
    assert "SAME" in str(exc.value)


def test_p5_case_insensitive_collision_rejected():
    # APFS (Mac) and NTFS (Windows) are case-INSENSITIVE:
    # `/Volumes/Vol/clip.mov` vs out `/volumes/vol` is the same dir.
    with pytest.raises(PathIsolationError):
        check_path_isolation("/Volumes/Vol/clip.mov", "/volumes/vol")


def test_p6_clean_disjoint_paths_pass(tmp_path: Path):
    src = tmp_path / "clip.mov"
    src.write_bytes(b"x")
    out = tmp_path / "proxies"
    # Disjoint: out is a SIBLING dir, not containing / contained by src.
    res = check_path_isolation(str(src), str(out))
    assert res is True


# ── C6: UNC / hardware-blocked ──────────────────────────────────────


def test_p7_unc_out_dir_is_hardware_blocked_not_supported():
    # A UNC share can still be *used*, but its rename/persistence
    # semantics are untested => the check reports HARDWARE_BLOCKED
    # rather than silently passing (C6).
    res = check_path_isolation(
        "/Volumes/SD1/clip.mov", r"\\nas\share\proxies"
    )
    assert res == HARDWARE_BLOCKED


# ── C6: Windows-safe stems ──────────────────────────────────────────


def test_p8_windows_stem_sanitizes_illegal_chars():
    # `:` `<` `>` `|` `?` `*` are illegal in NTFS names: replaced with
    # `-` (never dropped, so the result stays visually derivable).
    # Traceability of the ORIGINAL name is carried by the receipt
    # (argv + source_sha256), not embedded into the artifact name.
    clean = windows_stem_safe("bad:name?clip|0.mov")
    for ch in "<>:|?*":
        assert ch not in clean
    assert clean == "bad-name-clip-0.mov"
    # deterministic (same input -> same output, idempotent-ish):
    assert windows_stem_safe("bad:name?clip|0.mov") == clean


def test_p9_windows_reserved_names_detected():
    # A reserved device name (CON/NUL/COM1..9/LPT1..9/AUX, any case,
    # with or without an extension) must not survive as a bare
    # reserved word on NTFS: it gets an `x` prefix. Exact outputs:
    assert windows_stem_safe("CON") == "xCON"
    assert windows_stem_safe("NUL") == "xNUL"
    assert windows_stem_safe("COM1") == "xCOM1"
    assert windows_stem_safe("LPT9") == "xLPT9"
    # case-insensitive (con == CON on NTFS) and extension-bearing:
    assert windows_stem_safe("con.txt") == "xcon.txt"
    assert windows_stem_safe("CON.mov") == "xCON.mov"
    # a non-reserved stem passes through unchanged:
    assert windows_stem_safe("reel_A.mov") == "reel_A.mov"


# ── same_path helper (case-insensitive, alias-normalized) ──────────


def test_p10_same_path_case_and_alias_insensitive():
    assert same_path("/Volumes/VOL/a.mov", "/volumes/vol/a.mov") is True
    # realpath aliasing:
    assert same_path("/tmp/x", "/private/tmp/x") is True
    assert same_path("/a/b", "/a/c") is False
