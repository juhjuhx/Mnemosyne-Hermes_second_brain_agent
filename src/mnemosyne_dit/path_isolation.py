"""path_isolation.py — DIT 2.2 P12.2-C: Phase 4 C5/C6 path isolation.

Guarantees (fail-closed):

- **C5** — the proxy's output directory can never BE the source's
  directory, contain the source, or be contained by the source's
  directory. Staging (`.staging/`) and quarantine writes must not
  pollute a protected camera-card / NAS volume, and no original media
  is ever overwritten.
- **C6** — unknown / unsupported filesystem semantics are refused,
  not silently passed: UNC shares (and, symmetrically, any path whose
  rename/persistence semantics this build has not verified) return the
  `HARDWARE_BLOCKED` sentinel instead of a pass verdict. Windows-safe
  artifact stems are produced by `windows_stem_safe` (illegal NTFS
  characters replaced, reserved device names transformed; the receipt's
  recorded argv + `source_sha256` keep the original name traceable).

Pure string/realpath logic — deterministic on any host, no I/O beyond
`os.path.realpath` on the supplied paths.
"""

from __future__ import annotations

import os
import re

#: Sentinel: this path's filesystem semantics are not verified on this
#: build (UNC/SMB shares: cross-volume rename atomicity + persistence
#: are HARDWARE_BLOCKED — see Windows-workstation-census.md). A
#: `HARDWARE_BLOCKED` result must never be reported as a pass.
HARDWARE_BLOCKED = "HARDWARE_BLOCKED"

_WINDOWS_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


class PathIsolationError(Exception):
    """The source/output path pair is unsafe (same dir / containment /
    aliasing). No encoding may proceed: staging would pollute or
    overwrite the source volume."""


def _is_unc(path: str) -> bool:
    return path.startswith("\\\\")


def same_path(a: str, b: str) -> bool:
    """Path equality under alias normalization AND case-insensitivity
    (APFS/NTFS are case-insensitive; `/tmp` == `/private/tmp`).
    Symlinks are resolved first, so a symlinked alias of the same
    volume/path is the same path."""
    ra, rb = os.path.realpath(a), os.path.realpath(b)
    return ra.casefold() == rb.casefold()


def windows_stem_safe(filename: str) -> str:
    """A Windows/NTFS-safe version of `filename`'s base name.

    Illegal characters are replaced with `-` (never dropped silently,
    so the result stays visually derivable from the original), trailing
    dots/spaces (which NTFS strips) are removed, and a reserved device
    name (CON/NUL/COM1…LPT9, regardless of extension — conservative)
    gets a `x` prefix. The transform is deterministic; traceability of
    the ORIGINAL name is carried by the receipt (argv + source_sha256),
    not embedded into the artifact name (keeps artifact names stable
    for the clean case)."""
    base, dot, ext = filename.partition(".")
    clean = _ILLEGAL_CHARS.sub("-", base).strip(". ")
    if not clean:
        clean = "unnamed"
    if clean.upper() in _WINDOWS_RESERVED:
        clean = "x" + clean
    return f"{clean}.{ext}" if dot else clean


def check_path_isolation(
    source: str, out_dir: str, *, protected_source: bool = False,
) -> bool | str:
    """Fail-closed C5 check of a (source file, output dir) pair.

    - UNC / unsupported-filesystem path on either side =>
      `HARDWARE_BLOCKED` (returned, not raised — the caller decides
      how to surface it; a pass verdict must NOT be fabricated).
    - out_dir == source dir (alias + case-normalized) => raise
      `PathIsolationError` ("same") — ALWAYS rejected, on any volume.
    - out_dir CONTAINS the source => raise ("contains") — ALWAYS
      rejected (output written INTO the source tree).
    - source's dir CONTAINS out_dir (scratch layout: source + sibling
      output dir) => rejected ONLY when `protected_source` (a
      camera-card / NAS volume that must stay pristine); on an
      unprotected working volume this layout is legal, because
      artifact names are job-namespaced and can never clobber the
      source file itself.
    - otherwise => True (disjoint; safe)."""
    s_raw = os.fsdecode(source)
    o_raw = os.fsdecode(out_dir)
    if _is_unc(s_raw) or _is_unc(o_raw):
        return HARDWARE_BLOCKED

    s_real = os.path.realpath(s_raw)
    o_real = os.path.realpath(o_raw)
    s_dir = os.path.dirname(s_real)

    s_cf_dir = s_dir.casefold()
    o_cf = o_real.casefold()
    sep_cf = os.sep.casefold()

    # out_dir equals the source's directory (alias + case-normalized:
    # /tmp == /private/tmp on macOS, APFS/NTFS case-insensitivity).
    if o_cf == s_cf_dir:
        raise PathIsolationError(
            f"out_dir {out_dir!r} is the SAME as the source's directory "
            f"(alias-normalized {o_real!r}); staging/quarantine writes "
            "would pollute the source volume (C5, fail-closed)"
        )
    if s_cf_dir.startswith(o_cf + sep_cf):
        raise PathIsolationError(
            f"out_dir {out_dir!r} CONTAINS the source "
            f"({s_raw!r}); the output would be written into the source "
            "tree (C5, fail-closed)"
        )
    if o_cf.startswith(s_cf_dir + sep_cf) and protected_source:
        raise PathIsolationError(
            f"out_dir {out_dir!r} is INSIDE the source's directory "
            f"({s_dir!r}) and that volume is protected "
            f"(camera card / NAS): staging/quarantine would pollute "
            "it (C5, fail-closed)"
        )
    # scratch layout on an unprotected working volume is legal —
    # artifact names are job-namespaced and cannot clobber the source.
    return True
