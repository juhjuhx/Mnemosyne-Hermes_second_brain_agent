"""Generate tiny synthetic media fixtures for DIT 2.2 offload/safety tests.

Synthetic data ONLY: small random files with deterministic content, fake
camera directory trees, and zero-length / Unicode-name edge cases. No real
footage, no binaries in git (files are generated at test time, not committed).

Usage:
    python tests/fixtures/dit22/generate_fixtures.py <output_dir>
"""

from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path


def _make_file(path: Path, size_bytes: int, seed: int) -> str:
    """Write a file with deterministic pseudo-random content; return sha256."""
    rng = random.Random(seed)
    chunks = []
    written = 0
    while written < size_bytes:
        n = min(4096, size_bytes - written)
        chunks.append(rng.randbytes(n))
        written += n
    data = b"".join(chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def generate(output_dir: Path) -> dict[str, str]:
    """Create a fake camera card tree. Returns {relative_path: sha256}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}

    # Normal footage files (small, deterministic)
    for i, (reel, size) in enumerate([("A001", 256 * 1024), ("A002", 128 * 1024), ("B001", 64 * 1024)]):
        rel = f"DCIM/CAM_{reel}/A{reel[-4:]}0101.A"
        manifest[rel] = _make_file(output_dir / rel, size, seed=1000 + i)

    # Edge cases for fault/safety tests
    manifest["DCIM/CAM_A001/zero-byte.A"] = _make_file(output_dir / "DCIM/CAM_A001/zero-byte.A", 0, 0)
    manifest["DCIM/CAM_A001/故報緣名サンプル.A"] = _make_file(
        output_dir / "DCIM/CAM_A001/故報緣名サンプル.A", 1024, 7
    )

    # Sidecar files
    manifest["DCIM/CAM_A001/A0010101.SRT"] = _make_file(output_dir / "DCIM/CAM_A001/A0010101.SRT", 256, 42)
    return manifest


def verify(output_dir: Path, manifest: dict[str, str]) -> dict[str, bool]:
    """Re-hash every fixture; return {rel_path: ok}."""
    results: dict[str, bool] = {}
    for rel, expected in manifest.items():
        p = output_dir / rel
        actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
        results[rel] = actual == expected
    return results


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dit22_fixtures_out")
    m = generate(out)
    ok = all(verify(out, m).values())
    print(f"fixtures={len(m)} verify={'OK' if ok else 'FAILED'} dir={out}")
    sys.exit(0 if ok else 1)
