"""Contract test for DIT 2.2 synthetic fixture generator (synthetic data only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures" / "dit22"))

import generate_fixtures


def test_fixtures_are_deterministic(tmp_path: Path) -> None:
    m1 = generate_fixtures.generate(tmp_path / "a")
    m2 = generate_fixtures.generate(tmp_path / "b")
    assert m1.keys() == m2.keys()
    assert m1 == m2, "same seed must yield identical content hashes"


def test_fixtures_verify_after_generation(tmp_path: Path) -> None:
    m = generate_fixtures.generate(tmp_path / "card")
    results = generate_fixtures.verify(tmp_path / "card", m)
    assert all(results.values()), f"fixture hashes mismatch: {results}"
    assert any("zero-byte" in k for k in m), "zero-length edge case must exist"


def test_fixture_tree_is_writable_copy_target(tmp_path: Path) -> None:
    """Simulate an offload destination readback without touching any real media."""
    src = tmp_path / "card"
    dest = tmp_path / "dest"
    m = generate_fixtures.generate(src)
    for rel in m:
        data = (src / rel).read_bytes()
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    assert all(generate_fixtures.verify(dest, m).values())
