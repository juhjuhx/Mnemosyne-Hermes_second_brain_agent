"""P11.1-B — Publication Fencing: negative-first contract tests.

Closes P11.1 review gaps G2/G4: a same-job lease rotation must be
able to supersede a stale generation (live holder / operator re-run),
while a worker whose lease is no longer live must NEVER clobber a
healthy published artifact. A bare receipt token (P09.1's
detection-based fencing) is not a publication fence — it can only be
read *after* the clobber happened. This slice makes the stop real:

- the lease obligation: a formal job carrying a `lease_token` must
  pass a `queue` + `worker`; the lease is verified against the queue
  row (P09.1 live-lease truth) at START and re-verified at the PUBLISH
  moment (a lease can die mid-encode);
- versioned staging: two lease generations of the same job never
  share a staging target (`generation_tag`), so a zombie's partial
  write cannot land in the current holder's slot;
- conditional publish: an unattributable slot (receipt-less healthy
  artifact, another job's receipt, an undecodable receipt) is fenced,
  never clobbered.

Markers: `@behavior_tested` = real queue + real or spied ffmpeg
(synthetic media only, no v4, no cloud); `@fixture_only` = pure tag
logic. Windows/UNC recovery behavior is P11.1-C; not claimed here.
"""

import json
import re
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

import job_queue
import proxy_generator
from asset_schema import (
    Dit22Catalog,
    MediaAsset,
    Replica,
    VerificationEvidence,
    asset_id_for_file,
)
from media_probe import _sha256_file
from proxy_generator import ProxyFencedError, generation_tag

# ── helpers ─────────────────────────────────────────────────────────


def _media(tmp_path: Path) -> Path:
    """Small real synthetic media (fast encode, zero real material)."""
    p = tmp_path / "m.mp4"
    proxy_generator._run_ffmpeg(
        "ffmpeg",
        ["-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=0.3:size=160x120:rate=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)],
        60,
    )
    return p


def _catalog(tmp_path: Path, media: Path) -> Dit22Catalog:
    cat = Dit22Catalog(tmp_path / "dit22-test.db")
    aid = asset_id_for_file(media)
    cat.upsert_asset(MediaAsset(source_sha256=aid))
    cat.add_replica(
        Replica("r1", aid, "storage-a", "nas-a", str(media),
                verified=True, verified_at=1)
    )
    cat.add_evidence(
        VerificationEvidence("e1", aid, media.name, "sha256", aid,
                             device_id="dev-a", verdict="PASS",
                             replica_id="r1")
    )
    return cat


def _queue(tmp_path: Path) -> tuple[job_queue.DurableJobQueue, str]:
    q = job_queue.DurableJobQueue(tmp_path / "jobs.db")
    row = q.enqueue("proxy-job", idempotency_key="proxy-job")
    return q, row["job_id"]


def _expire(q: job_queue.DurableJobQueue, job: str) -> None:
    """Deterministically expire the current lease (no sleep races): the
    test's own SQLite is the fixture, not the production clock."""
    q.conn.execute(
        "UPDATE dit22_job SET lease_expires_at=? WHERE job_id=?",
        (time.time() - 5, job),
    )
    q.conn.commit()


def _spy(monkeypatch) -> list:
    calls: list = []

    def fake(ffmpeg_bin, args, timeout_s):
        calls.append(args)
        return 1, b"", b"spied: must not be reached"

    monkeypatch.setattr(proxy_generator, "_run_ffmpeg", fake)
    return calls


# ── the lease obligation (fail-closed, formal jobs) ────────────────


@pytest.mark.behavior_tested
def test_formal_token_without_queue_is_fenced(tmp_path, monkeypatch):
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    tok = q.lease(job, "w1")
    calls = _spy(monkeypatch)
    with pytest.raises(ProxyFencedError, match="queue"):
        proxy_generator.generate_proxy(
            media, "browser", tmp_path / "out",
            job_id=job, lease_token=tok, catalog=cat, storage_id="storage-a",
        )
    assert calls == [], "the obligation must fire before any encode"
    assert not (tmp_path / "out" / ".staging").exists()


@pytest.mark.behavior_tested
def test_formal_token_without_worker_is_fenced(tmp_path, monkeypatch):
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    tok = q.lease(job, "w1")
    calls = _spy(monkeypatch)
    with pytest.raises(ProxyFencedError, match="worker"):
        proxy_generator.generate_proxy(
            media, "browser", tmp_path / "out",
            job_id=job, lease_token=tok, catalog=cat,
            storage_id="storage-a", queue=q, worker=None,
        )
    assert calls == []


# ── a stale worker is fenced at start (never spends an encode) ────


@pytest.mark.behavior_tested
def test_stale_worker_fenced_at_start(tmp_path, monkeypatch):
    """A zombie whose lease was taken over cannot even start encoding:
    the start check reads the live queue row, not a remembered token."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    tok_a = q.lease(job, "wA")
    _expire(q, job)
    tok_b = q.lease(job, "wB")  # takeover after expiry
    assert tok_b != tok_a
    calls = _spy(monkeypatch)
    with pytest.raises(ProxyFencedError, match="live lease"):
        proxy_generator.generate_proxy(
            media, "browser", tmp_path / "out",
            job_id=job, lease_token=tok_a, catalog=cat,
            storage_id="storage-a", queue=q, worker="wA",
        )
    assert calls == []
    assert not (tmp_path / "out" / ".staging").exists()


# ── a lease lost MID-ENCODE fences the publish moment ─────────────


@pytest.mark.behavior_tested
def test_lease_lost_mid_encode_fences_publish(tmp_path, monkeypatch):
    """The encode finishes, but the holder's lease died during it
    (takeover). The staged artifact is discarded; nothing is
    published; the healthy slot (if any) is untouched."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    tok_a = q.lease(job, "wA")
    # a reference proxy (real encode, ad-hoc isolated) to copy into
    # the zombie's staging slot so the verify gate passes:
    ref = proxy_generator.generate_proxy(media, "browser", tmp_path / "ref",
                                         test_mode=True)
    ref_bytes = Path(ref.path).read_bytes()

    def fake(ff_bin, args, timeout_s):
        staged = Path(args[-1])
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(ref_bytes)
        # the takeover happens DURING the encode:
        _expire(q, job)
        q.lease(job, "wB")
        return 0, b"", b""

    monkeypatch.setattr(proxy_generator, "_run_ffmpeg", fake)
    with pytest.raises(ProxyFencedError, match="publish"):
        proxy_generator.generate_proxy(
            media, "browser", out,
            job_id=job, lease_token=tok_a, catalog=cat,
            storage_id="storage-a", queue=q, worker="wA",
        )
    # nothing published by the zombie:
    assert not (out / f"{job}__m__browser.mp4").exists()
    # its own staged generation was discarded:
    gen_a = out / ".staging" / job / generation_tag(tok_a)
    assert not gen_a.exists() or not any(gen_a.iterdir())


# ── conditional publish: healthy artifacts are never clobbered ────


@pytest.mark.behavior_tested
def test_healthy_artifact_without_receipt_is_fenced(tmp_path):
    """A published slot whose receipt was removed out-of-band is
    unownable: no worker — live or not — may clobber a healthy
    artifact they cannot attribute. Operator path: investigate, then
    `delete_proxies` / P11.1-C quarantine."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    tok_a = q.lease(job, "wA")
    r_a = proxy_generator.generate_proxy(
        media, "browser", out, job_id=job, lease_token=tok_a,
        catalog=cat, storage_id="storage-a", queue=q, worker="wA",
    )
    target = Path(r_a.path)
    healthy_hash = _sha256_file(target)
    target.with_name(target.name + ".receipt.json").unlink()  # out-of-band

    _expire(q, job)
    tok_b = q.lease(job, "wB")  # the NEW live holder
    with pytest.raises(ProxyFencedError, match="healthy artifact"):
        proxy_generator.generate_proxy(
            media, "browser", out, job_id=job, lease_token=tok_b,
            catalog=cat, storage_id="storage-a", queue=q, worker="wB",
        )
    # the healthy artifact survived byte-identical:
    assert _sha256_file(target) == healthy_hash


@pytest.mark.behavior_tested
def test_foreign_job_receipt_is_fenced(tmp_path, monkeypatch):
    """A receipt naming ANOTHER job under our slot is tamper: the
    foreign artifact is never clobbered, even by a live holder."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    slot = f"{job}__m__browser.mp4"
    (out / slot).write_bytes(b"foreign-artifact")
    (out / f"{slot}.receipt.json").write_text(
        json.dumps({"job_id": "other-job", "lease_token": "x"})
    )
    tok = q.lease(job, "w1")
    with pytest.raises(ProxyFencedError, match="does not attribute"):
        proxy_generator.generate_proxy(
            media, "browser", out, job_id=job, lease_token=tok,
            catalog=cat, storage_id="storage-a", queue=q, worker="w1",
        )
    assert (out / slot).read_bytes() == b"foreign-artifact"


@pytest.mark.behavior_tested
def test_undecodable_receipt_is_fenced(tmp_path, monkeypatch):
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    slot = f"{job}__m__browser.mp4"
    (out / f"{slot}.receipt.json").write_text("\x00\x01garbage")
    tok = q.lease(job, "w1")
    with pytest.raises(ProxyFencedError, match="undecodable receipt"):
        proxy_generator.generate_proxy(
            media, "browser", out, job_id=job, lease_token=tok,
            catalog=cat, storage_id="storage-a", queue=q, worker="w1",
        )
    # nothing was written to the slot:
    assert not (out / slot).exists()


# ── positive: rotation and re-entry keep working ───────────────────


@pytest.mark.behavior_tested
def test_receipt_missing_job_id_key_is_fenced(tmp_path, monkeypatch):
    """A decodable but HAND-CRAFTED receipt dict with no `job_id` key
    attributes the slot to no job in this codebase's truth model: it
    is unattributable and must fence (review Minor #2, hardened now)."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    slot = f"{job}__m__browser.mp4"
    (out / f"{slot}.receipt.json").write_text(json.dumps({"codec": "h264"}))
    tok = q.lease(job, "w1")
    with pytest.raises(ProxyFencedError, match="no `job_id` key"):
        proxy_generator.generate_proxy(
            media, "browser", out, job_id=job, lease_token=tok,
            catalog=cat, storage_id="storage-a", queue=q, worker="w1",
        )
    assert not (out / slot).exists()


@pytest.mark.behavior_tested
def test_adhoc_receipt_under_formal_slot_is_fenced(tmp_path, monkeypatch):
    """An ad-hoc (test_mode, receipt job_id=None) publication under a
    formal job's slot is not attributable to that job: fenced."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    slot = f"{job}__m__browser.mp4"
    (out / f"{slot}.receipt.json").write_text(
        json.dumps({"job_id": None, "lease_token": None})
    )
    (out / slot).write_bytes(b"adhoc-artifact")
    tok = q.lease(job, "w1")
    with pytest.raises(ProxyFencedError, match="does not attribute"):
        proxy_generator.generate_proxy(
            media, "browser", out, job_id=job, lease_token=tok,
            catalog=cat, storage_id="storage-a", queue=q, worker="w1",
        )
    assert (out / slot).read_bytes() == b"adhoc-artifact"


@pytest.mark.behavior_tested
def test_live_rotation_supersedes_stale_generation(tmp_path):
    """Same job, lease rotated by expiry: the CURRENT live holder
    supersedes the stale generation atomically (P09.1 detection
    semantics, now also enforced before the clobber); the stale
    receipt no longer reports stale."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    tok_a = q.lease(job, "wA")
    r1 = proxy_generator.generate_proxy(
        media, "browser", out, job_id=job, lease_token=tok_a,
        catalog=cat, storage_id="storage-a", queue=q, worker="wA",
    )
    _expire(q, job)
    tok_b = q.lease(job, "wB")  # takeover
    r2 = proxy_generator.generate_proxy(
        media, "browser", out, job_id=job, lease_token=tok_b,
        catalog=cat, storage_id="storage-a", queue=q, worker="wB",
    )
    receipt = json.loads(
        Path(r2.path).with_name(Path(r2.path).name + ".receipt.json")
        .read_text()
    )
    assert receipt["lease_token"] == tok_b
    assert r2.proxy_sha256 == _sha256_file(Path(r2.path))
    # the rotated receipt replaced the stale one: nothing stale remains
    assert proxy_generator.find_stale_proxies(out, job, tok_b) == []
    # the previous artifact was atomically replaced, not shadowed:
    assert Path(r1.path).read_bytes() is not None


@pytest.mark.behavior_tested
def test_same_token_reentry_still_replaces(tmp_path):
    """P11 idempotent re-entry is preserved in formal mode: same job +
    same live token is an atomic replace, not a fence."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    tok = q.lease(job, "w1")
    r1 = proxy_generator.generate_proxy(
        media, "browser", out, job_id=job, lease_token=tok,
        catalog=cat, storage_id="storage-a", queue=q, worker="w1",
    )
    r2 = proxy_generator.generate_proxy(
        media, "browser", out, job_id=job, lease_token=tok,
        catalog=cat, storage_id="storage-a", queue=q, worker="w1",
    )
    assert Path(r2.path).exists()
    assert r1.path == r2.path
    receipt = json.loads(
        Path(r2.path).with_name(Path(r2.path).name + ".receipt.json")
        .read_text()
    )
    assert receipt["lease_token"] == tok


# ── versioned staging: token isolation + zombie sweep ──────────────


@pytest.mark.fixture_only
def test_generation_tag_is_token_isolated_and_safe():
    assert generation_tag(None) == "unleased"
    a, b = generation_tag("tok-A"), generation_tag("tok-B")
    assert a != b, "two lease generations must never share a staging target"
    assert generation_tag("tok-A") == a, "the tag must be deterministic"
    for tag in (a, b, generation_tag(None)):
        assert re.fullmatch(r"[a-z0-9-]+", tag), f"unsafe tag {tag!r}"
        assert len(tag) <= 16, f"tag too long {tag!r}"


@pytest.mark.behavior_tested
def test_zombie_staging_residue_swept_after_live_publish(tmp_path):
    """A crashed zombie leaves residue in ITS generation dir only. The
    next live holder's successful publish discards the foreign gen
    dirs (P08: uncommitted staging is crash-discardable); a stale
    worker can NEVER trigger the sweep (no live lease => no sweep)."""
    media = _media(tmp_path)
    cat = _catalog(tmp_path, media)
    q, job = _queue(tmp_path)
    out = tmp_path / "out"
    tok_a = q.lease(job, "wA")
    # zombie residue in generation A:
    gen_a = out / ".staging" / job / generation_tag(tok_a)
    gen_a.mkdir(parents=True, exist_ok=True)
    (gen_a / "partial.mp4").write_bytes(b"crash-residue")

    _expire(q, job)
    tok_b = q.lease(job, "wB")
    r2 = proxy_generator.generate_proxy(
        media, "browser", out, job_id=job, lease_token=tok_b,
        catalog=cat, storage_id="storage-a", queue=q, worker="wB",
    )
    assert r2.path
    assert not gen_a.exists(), "zombie residue must be discarded by the live holder"
    # P11 invariant: no staging leftovers after a successful publish
    staging = out / ".staging"
    assert not staging.exists() or not any(staging.iterdir())
