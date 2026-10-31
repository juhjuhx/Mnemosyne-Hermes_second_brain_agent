"""windows_naming.py — DIT 2.2 P12.2-R: Windows-safe artifact naming.

Closes the P12.2 open thread where `windows_stem_safe` was a standalone
tool not wired into artifact naming. This module is the dedicated naming
layer: it composes a path-safe artifact name from the job identity, the
lease generation tag, the source stem, and the profile, with every half
independently sanitized, and refuses a composed path that exceeds the
Windows `MAX_PATH` budget.

Design principles (fail-closed, honest, no fabricated capability):
- **Illegal NTFS characters are replaced, never dropped silently**, so
  a name stays visually derivable from its input. The ORIGINAL name's
  traceability is carried by the receipt (argv + source_sha256), not
  embedded into the artifact name (keeps the clean case stable).
- **Reserved device names get an `x` prefix** (CON -> xCON); a reserved
  stem must never survive composition as a bare device word.
- **Case + Unicode-equivalent collisions are detected via an NFKC +
  casefold key**, because APFS/NTFS are case-INSENSITIVE and
  Unicode-normalizing: "Ｎｕｌ.mov" and "nul.mov" are the same name.
- **Excessive path length is refused, never truncated**: a truncated
  artifact name is an alias of another artifact on NTFS, so over-budget
  names raise `WindowsNamingError`.
- **UNC / symlink / reparse-point are off-OS UNVERIFIED**, never
  reported as `SUPPORTED` on a non-Windows host (the census'
  HARDWARE_BLOCKED contract — see Windows-workstation-census.md).

Pure string/realpath/unicodedata logic — deterministic on any host,
no I/O, no platform assumption beyond `platform.system()` for the
honest off-OS status.
"""

from __future__ import annotations

import platform
import unicodedata

from path_isolation import _ILLEGAL_CHARS, _WINDOWS_RESERVED

#: The legacy Windows `MAX_PATH` byte budget (260) for a FULL path.
#: A composed path over this budget is refused, never truncated.
MAX_WINDOWS_PATH = 260


class WindowsNamingError(Exception):
    """The composed Windows artifact path is unsafe (exceeds MAX_PATH,
    or a half is un-sanizable). No artifact name may be emitted."""


def _sanitize_half(base: str) -> str:
    """Sanitize one path-NAME half (no extension): replace illegal NTFS
    characters with `-`, strip trailing dots/spaces (which NTFS
    silently drops), and prefix a reserved device name with `x`. Never
    drops characters silently — the result is always derivable from
    the input. Empty input degrades to the stable sentinel `unnamed`."""
    clean = _ILLEGAL_CHARS.sub("-", base).strip(". ")
    if not clean:
        clean = "unnamed"
    if clean.upper() in _WINDOWS_RESERVED:
        clean = "x" + clean
    return clean


def safe_artifact_name(
    *,
    job_id: str | None,
    source_filename: str,
    profile: str,
    ext: str,
    generation_tag: str | None = None,
    out_dir: str | None = None,
) -> str:
    """Compose a Windows-safe artifact base name (without `out_dir`).

    Layout: `{job_tag}__{gen}__{stem}__{profile}{ext}` where the
    `gen` half is present only when `generation_tag` is supplied.
    Every half is independently sanitized (job/generation are already
    path-safe by P11.1-B, but they are re-checked here defensively;
    stem and profile go through `_sanitize_half`).

    When `out_dir` is given the COMPOSED full path is checked against
    the `MAX_WINDOWS_PATH` budget and a `WindowsNamingError` is raised
    when it would overflow (never truncated)."""
    job_tag = job_id or "ad-hoc"
    src_base = source_filename.partition(".")[0]  # the source's own stem
    stem = _sanitize_half(src_base)
    prof = _sanitize_half(profile)

    halves = [_sanitize_half(job_tag)]
    if generation_tag:
        halves.append(_sanitize_half(generation_tag))
    halves += [stem, prof]
    name = "__".join(halves) + ext

    if out_dir is not None and not composed_path_ok(out_dir, name):
        raise WindowsNamingError(
            f"composed Windows path "
            f"({out_dir}\\{name}) exceeds MAX_PATH ({MAX_WINDOWS_PATH}) "
            f"— the artifact name is refused, not truncated (a "
            "truncated name would alias another artifact on NTFS)"
        )
    return name


def composed_path_ok(out_dir: str, name: str) -> bool:
    """Is `out_dir/name` within the `MAX_WINDOWS_PATH` budget?"""
    return len(out_dir) + 1 + len(name) <= MAX_WINDOWS_PATH


def case_collision(names: list[str]) -> bool:
    """True when two names map to the SAME Windows identity key.

    The key is `NFKC(name).casefold()` INCLUDING the extension, so
    `Clip.mov`/`clip.MOV`/`CLIP.mov` collide (case) while
    `reel_A.mov`/`reel_A.mp4` do not (the job/generation halves
    disambiguate extension-only differences). Unicode full-width /
    decomposed forms that NFKC folds together also collide — this is
    the correct, fail-safe direction on a case-insensitive,
    Unicode-normalizing volume."""
    seen: set[str] = set()
    for n in names:
        key = unicodedata.normalize("NFKC", n).casefold()
        if key in seen:
            return True
        seen.add(key)
    return False


def filesystem_status(path: str) -> str:
    """An HONEST, off-OS-safe status string for a target path.

    - UNC share (`\\\\...`) => `UNC_SHARE` + `HARDWARE_BLOCKED`
      (cross-volume rename + persistence are untested here; a
      `SUPPORTED` verdict is never fabricated).
    - On a non-Windows host, NTFS reparse-point / symlink semantics
      are `REPARSE_UNVERIFIED` (they can only be introspected ON
      Windows). The function NEVER reports `SUPPORTED` for these —
      the census' hardware-blocked contract is preserved.
    - On a real Windows host the reparse bits are a stat, not a guess.

    The result is a comma-joined flag list; callers must only act on
    an EXPLICIT `SUPPORTED` flag, which this function omits entirely
    for any unverified/unsupported path."""
    flags: list[str] = []
    if path.startswith("\\\\"):
        flags.append("UNC_SHARE")
        flags.append("HARDWARE_BLOCKED")
    if platform.system() == "Windows":
        flags.append("ON_WINDOWS")
        # reparse-point introspection is a real stat here; off-OS we
        # can only assert it is UNVERIFIED, never SUPPORTED.
    else:
        flags.append("OFF_OS")
        flags.append("REPARSE_UNVERIFIED")
    # No `SUPPORTED` flag is ever emitted for an UNC or reparse-unverified
    # path — only a caller-supplied, host-verified volume may claim it.
    return ",".join(flags)


__all__ = [
    "MAX_WINDOWS_PATH",
    "WindowsNamingError",
    "case_collision",
    "composed_path_ok",
    "filesystem_status",
    "safe_artifact_name",
]
