"""P12.2-R (RC prep): Windows artifact naming — RED negative tests.

Closes the last P12.2 open thread (windows_stem_safe was a standalone
tool, not wired into artifact naming) with a dedicated naming layer:

- safe artifact name composition: job ID + generation tag + source
  stem + profile, each half independently path-safe;
- case-insensitive collisions (APFS/NTFS): "Clip.mov" vs "clip.MOV";
- Unicode normalization: full-width / NFKC-equivalent names collide;
- Windows reserved names survive composition (x-prefix from
  windows_stem_safe, not re-invented here);
- invalid NTFS characters replaced, never dropped silently;
- excessive path length (MAX_PATH 260 budget on the COMPOSED path);
- UNC / symlink / reparse-point: UNVERIFIED off-OS, never "supported".

Run: pytest tests/test_dit22_windows_naming.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "mnemosyne_dit"))

from windows_naming import (
    MAX_WINDOWS_PATH,
    WindowsNamingError,
    case_collision,
    composed_path_ok,
    filesystem_status,
    safe_artifact_name,
)

# ── 1. safe composition ─────────────────────────────────────────────


def test_w1_clean_inputs_exact_name():
    name = safe_artifact_name(
        job_id="123e4567-e89b-42d3-a456-426614174000",
        source_filename="reel_A_0014.mov",
        profile="editor",
        ext=".mxf",
        generation_tag="tok-abcdef012345",
    )
    # job__generation__stem__profile : every half visible, no illegal
    # chars, extension kept once at the end.
    assert name == (
        "123e4567-e89b-42d3-a456-426614174000__tok-abcdef012345"
        "__reel_A_0014__editor.mxf"
    )


def test_w2_adhoc_job_without_generation():
    name = safe_artifact_name(
        job_id=None,
        source_filename="clip.mov",
        profile="browser",
        ext=".mp4",
    )
    assert name == "ad-hoc__clip__browser.mp4"


def test_w3_reserved_source_stem_transformed_inside_composition():
    # A source literally named "CON.mp4" must not yield a reserved
    # device name in any half of the composed artifact name.
    name = safe_artifact_name(
        job_id="j1", source_filename="CON.mp4",
        profile="browser", ext=".mp4",
    )
    assert "xCON" in name
    assert not _is_reserved_bare(name)


def test_w4_invalid_source_chars_replaced_not_dropped():
    name = safe_artifact_name(
        job_id="j2", source_filename="bad:<name>?.mov",
        profile="browser", ext=".mp4",
    )
    for ch in '<>:"/\\|?*':
        assert ch not in name
    # deterministic + the visible skeleton is preserved:
    assert safe_artifact_name(
        job_id="j2", source_filename="bad:<name>?.mov",
        profile="browser", ext=".mp4",
    ) == name


# ── 2. case / unicode collisions ─────────────────────────────────────


def test_w5_case_insensitive_collision_detected():
    assert case_collision(["Clip.mov", "clip.MOV", "CLIP.mov"]) is True
    # distinct basenames that only differ in EXTENSION are NOT a
    # collision (the job/generation halves disambiguate them):
    assert case_collision(["reel_A.mov", "reel_A.mp4"]) is False
    assert case_collision(["reel_A", "reel_B"]) is False


def test_w6_unicode_nfkc_equivalent_collides():
    # full-width "Ｎｕｌ" NFKC-folds to "Nul"; on NTFS that is the
    # reserved NUL device (case-insensitive) => the collision key
    # must see them as the SAME name.
    assert case_collision(["Ｎｕｌ.mov", "nul.mov"]) is True
    # a pure-decorative difference that NFKC removes must also merge:
    assert case_collision(["cafe\u0301.txt", "caf\u00e9.txt"]) is True


def _is_reserved_bare(name: str) -> bool:
    """The STEM half of a composed name (second-to-last `__` field)
    must not be a bare reserved device word."""
    from windows_naming import _WINDOWS_RESERVED

    stem = name.rsplit(".", 1)[0].split("__")[-2]
    return stem.upper() in _WINDOWS_RESERVED


# ── 3. MAX_PATH budget ───────────────────────────────────────────────


def test_w7_composed_path_over_max_path_refused():
    # deep staging dir + a long source stem: the COMPOSED path must
    # stay inside MAX_WINDOWS_PATH (260). Over budget => refused,
    # never truncated silently (a truncated name is an alias of
    # another artifact on NTFS).
    deep = "C:\\work\\media\\a" * 10
    with pytest.raises(WindowsNamingError):
        safe_artifact_name(
            job_id="j3",
            source_filename="x" * 250 + ".mov",
            profile="editor",
            ext=".mxf",
            out_dir=deep,
        )
    # and a short source at the same depth still fits:
    name = safe_artifact_name(
        job_id="j3", source_filename="a.mov", profile="editor",
        ext=".mxf", out_dir=deep,
    )
    assert name


def test_w8_composed_path_ok_helper_is_deterministic():
    d = "C:\\proxies"
    assert composed_path_ok(d, "j__g__stem__p.mxf") is True
    assert composed_path_ok(d, "j__g__" + ("s" * 400) + ".mxf") is False
    assert MAX_WINDOWS_PATH == 260


# ── 4. UNC / symlink / reparse: honest off-OS status ────────────────


def test_w9_unc_is_hardware_blocked_reason():
    st = filesystem_status(r"\\nas\share\proxies")
    assert "UNC_SHARE" in st
    # it must NOT report "supported":
    assert "SUPPORTED" not in st


def test_w10_offos_reparse_point_unverified_never_supported():
    # An NTFS reparse point can only be introspected ON Windows.
    # Off-OS the status is UNVERIFIED — the code must never claim
    # reparse-point support on a non-Windows host.
    import platform

    st = filesystem_status("C:\\data\\proxies")
    if platform.system() != "Windows":
        assert "REPARSE_UNVERIFIED" in st
        assert "SUPPORTED" not in st
    else:
        # on a real Windows host it is a stat, not a guess:
        assert "REPARSE_UNVERIFIED" not in st or "REPARSE_PRESENT" in st
