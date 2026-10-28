"""P11.1-A — Source Admission Gate: negative-first contract tests.

Spec: docs/engineering/P11.1-safety-integration-review.md §2.4 (gap G5).

The gate is fail-closed on every missing signal:
no replica record / unverified replica / no trusted read-back evidence /
dangling or cross-asset evidence / source SHA256 mismatch / missing file /
untrusted device identity => DENIED, and a denied source NEVER reaches ffmpeg.

An admitted source authorizes proxy ENCODING only. No surface of this
module may ever say a camera card is safe to format (P05 `ReuseEligibility`
contract, re-asserted here). Synthetic fixtures may flow through the
pipeline ONLY in isolated `test_mode` — and that mode must never write a
catalog/evidence row, so a fixture can't masquerade as a formal verified
source.

Markers: `@fixture_only` = pure catalog logic on synthetic bytes (no
media, no ffmpeg); `@behavior_tested` = real-ffmpeg encode through the
gated `generate_proxy`. No v4 files.db/qdrant/indexer, no cloud.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

import proxy_generator
from asset_schema import (
    DeviceIdentity,
    Dit22Catalog,
    MediaAsset,
    Replica,
    StaticDeviceIdentityProvider,
    VerificationEvidence,
    asset_id_for_bytes,
    asset_id_for_file,
)
from source_admission import (
    AdmissionDecision,
    ProxySourceAdmissionError,
    admit_source,
    record_admission_evidence,
)


def _catalog(
    tmp_path: Path,
    *,
    verified: bool = True,
    with_evidence: bool = True,
    replica: bool = True,
    domain: str = "nas-a",
    content: bytes = b"synthetic-clip-bytes",
) -> tuple[Dit22Catalog, str, Path]:
    """A full trusted chain (asset + verified replica + PASS read-back)
    by default; every variant breaks exactly one link."""
    cat = Dit22Catalog(tmp_path / "dit22-test.db")
    aid = asset_id_for_bytes(content)
    (tmp_path / "clip.mp4").write_bytes(content)
    cat.upsert_asset(MediaAsset(source_sha256=aid))
    if replica:
        cat.add_replica(
            Replica("r1", aid, "storage-a", domain, str(tmp_path / "clip.mp4"),
                    verified=verified, verified_at=123)
        )
    if with_evidence:
        cat.add_evidence(
            VerificationEvidence("e1", aid, "clip.mp4", "sha256", aid,
                                 device_id="dev-a", verdict="PASS",
                                 replica_id="r1")
        )
    return cat, aid, tmp_path / "clip.mp4"


def _media(tmp_path: Path) -> Path:
    """Real (synthetic, zero real material) media for behavior tests."""
    p = tmp_path / "m.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)],
        check=True,
    )
    return p


# ── admission gate: positive control + every single-link break ─────


@pytest.mark.fixture_only
def test_trusted_source_is_admitted(tmp_path):
    cat, aid, clip = _catalog(tmp_path)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert d.admitted and d.reason == "admitted"
    assert d.replica_id == "r1" and d.source_sha256 == aid


@pytest.mark.fixture_only
def test_unverified_replica_is_denied(tmp_path):
    cat, _aid, clip = _catalog(tmp_path, verified=False)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert not d.admitted
    assert "replica_verified" in d.reason


@pytest.mark.fixture_only
def test_missing_replica_record_is_denied(tmp_path):
    cat, _aid, clip = _catalog(tmp_path, replica=False, with_evidence=False)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert not d.admitted and "replica_recorded" in d.reason


@pytest.mark.fixture_only
def test_missing_readback_evidence_is_denied(tmp_path):
    cat, _aid, clip = _catalog(tmp_path, with_evidence=False)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert not d.admitted and "trusted_readback_evidence" in d.reason


@pytest.mark.fixture_only
def test_dangling_evidence_is_denied(tmp_path):
    """A PASS verdict whose replica_id points at nothing is a record,
    not a verification (P07.1 trust-source rule)."""
    cat, aid, clip = _catalog(tmp_path, with_evidence=False)
    cat.add_evidence(
        VerificationEvidence("e-x", aid, "clip.mp4", "sha256", aid,
                             device_id="dev-a", verdict="PASS",
                             replica_id="r-GONE")
    )
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert not d.admitted and "trusted_readback_evidence" in d.reason


@pytest.mark.fixture_only
def test_cross_asset_evidence_is_denied(tmp_path):
    """Evidence pointing at ANOTHER asset's replica never admits this one."""
    cat, aid, clip = _catalog(tmp_path, with_evidence=False)
    other = asset_id_for_bytes(b"another-asset")
    cat.upsert_asset(MediaAsset(source_sha256=other))
    cat.add_replica(
        Replica("r-o", other, "storage-b", "nas-b", "/somewhere/other.mp4",
                verified=True, verified_at=1)
    )
    cat.add_evidence(
        VerificationEvidence("e-o", aid, "clip.mp4", "sha256", aid,
                             device_id="dev-a", verdict="PASS",
                             replica_id="r-o")
    )
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert not d.admitted and "trusted_readback_evidence" in d.reason


@pytest.mark.fixture_only
def test_source_sha_mismatch_is_denied(tmp_path):
    cat, _aid, clip = _catalog(tmp_path)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip),
                     expected_sha256="0" * 64)
    assert not d.admitted and "sha_matches" in d.reason


@pytest.mark.fixture_only
def test_missing_file_is_denied_and_unrecordable(tmp_path):
    cat, _aid, _ = _catalog(tmp_path)
    d = admit_source(cat, storage_id="storage-a",
                     replica_path=str(tmp_path / "nope.mp4"))
    assert not d.admitted and "file_exists" in d.reason
    # No on-disk content => no content identity => nothing to attribute an
    # evidence row to; the controlled ledger refuses it.
    assert d.asset_id is None
    with pytest.raises(ValueError, match="no asset identity"):
        record_admission_evidence(cat, d, job_id="job-z", evidence_id="e-z")


@pytest.mark.fixture_only
def test_untrusted_device_denies_when_provider_given(tmp_path):
    cat, _aid, clip = _catalog(tmp_path)
    prov = StaticDeviceIdentityProvider(
        {str(clip): DeviceIdentity("net-share", False, "smb")}
    )
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip),
                     device_provider=prov)
    assert not d.admitted and "device_identity_trusted" in d.reason


@pytest.mark.fixture_only
def test_physical_device_passes_when_provider_given(tmp_path):
    cat, _aid, clip = _catalog(tmp_path)
    prov = StaticDeviceIdentityProvider(
        {str(clip): DeviceIdentity("disk-c", True, "usb-sd")}
    )
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip),
                     device_provider=prov)
    assert d.admitted


# ── the gate can ADMIT but can never authorize a card format ──────


@pytest.mark.fixture_only
def test_admission_never_authorizes_card_format(tmp_path):
    cat, aid, clip = _catalog(tmp_path)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    assert not hasattr(d, "safe_to_format")
    assert not hasattr(cat, "safe_to_format")
    assert "SAFE_TO_FORMAT" not in d.reason
    # the P05 verdict pair is the only eligibility surface, unchanged:
    el = cat.reuse_eligibility(aid)
    assert el.verdict in ("BLOCKED", "ELIGIBLE_FOR_REVIEW")


# ── controlled Job Evidence: results + reasons, append-only ────────


@pytest.mark.fixture_only
def test_admission_recorded_and_reentry_idempotent(tmp_path):
    cat, aid, clip = _catalog(tmp_path)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    record_admission_evidence(cat, d, job_id="job-77", evidence_id="adm-job-77-x")
    rows = [e for e in cat.evidence_for(aid) if e.file_name == "admission/job-77"]
    assert len(rows) == 1 and rows[0].verdict == "ADMITTED"
    assert rows[0].digest == d.fingerprint
    # identical re-entry: append-only no-op (P05.1 S5)
    record_admission_evidence(cat, d, job_id="job-77", evidence_id="adm-job-77-x")
    assert len([e for e in cat.evidence_for(aid)
                if e.file_name == "admission/job-77"]) == 1


@pytest.mark.fixture_only
def test_denial_recorded_with_reason(tmp_path):
    cat, aid, clip = _catalog(tmp_path, verified=False)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    record_admission_evidence(cat, d, job_id="job-78", evidence_id="adm-job-78-x")
    rows = [e for e in cat.evidence_for(aid) if e.file_name == "admission/job-78"]
    assert rows and rows[0].verdict.startswith("DENIED:")
    assert "replica_verified" in rows[0].verdict


@pytest.mark.fixture_only
def test_admission_row_is_not_trusted_readback(tmp_path):
    """An ADMITTED row authorizes encoding only; it must NOT make another
    asset's replicas read-back-eligible (no masquerading as verification)."""
    cat, _aid, clip = _catalog(tmp_path, with_evidence=False)
    d = admit_source(cat, storage_id="storage-a", replica_path=str(clip))
    other = asset_id_for_bytes(b"other-clip")
    cat.upsert_asset(MediaAsset(source_sha256=other))
    cat.add_replica(
        Replica("r-2", other, "storage-a", "nas-a", str(clip),
                verified=True, verified_at=5)
    )
    cat.add_evidence(
        VerificationEvidence("e-adm", other, "clip.mp4",
                             "sha256-admission-gate", d.fingerprint,
                             verdict="ADMITTED", replica_id="r-2")
    )
    el = cat.reuse_eligibility(other)
    assert el.gates["readback_evidence"] is False


# ── gate wired into generate_proxy (formal catalog mode) ──────────


def _spy_ffmpeg(monkeypatch) -> list:
    calls: list = []

    def fake(ffmpeg_bin, args, timeout_s):
        calls.append(args)
        return 1, b"", b"spied: must not be reached"

    monkeypatch.setattr(proxy_generator, "_run_ffmpeg", fake)
    return calls


@pytest.mark.behavior_tested
def test_denied_source_blocks_encode_before_ffmpeg(tmp_path, monkeypatch):
    cat, _aid, clip = _catalog(tmp_path, verified=False)
    calls = _spy_ffmpeg(monkeypatch)
    with pytest.raises(ProxySourceAdmissionError, match="DENIED"):
        proxy_generator.generate_proxy(
            clip, "browser", tmp_path / "out",
            job_id="job-bad", catalog=cat, storage_id="storage-a",
        )
    assert calls == [], "a denied source must never reach ffmpeg"


@pytest.mark.behavior_tested
def test_formal_catalog_mode_requires_storage_id(tmp_path, monkeypatch):
    cat, _aid, clip = _catalog(tmp_path)
    calls = _spy_ffmpeg(monkeypatch)
    with pytest.raises(ProxySourceAdmissionError, match="storage_id"):
        proxy_generator.generate_proxy(
            clip, "browser", tmp_path / "out", job_id="job-x", catalog=cat
        )
    assert calls == []


@pytest.mark.behavior_tested
def test_formal_missing_source_file_raises_admission_not_value_error(
    tmp_path, monkeypatch
):
    """A formal job pointing at a missing replica must surface
    `ProxySourceAdmissionError` (the gate's denial), never a raw
    `ValueError` from the controlled-evidence layer (there is no asset
    identity to attribute a ledger row to when the file is absent)."""
    cat, _aid, _clip = _catalog(tmp_path)
    calls = _spy_ffmpeg(monkeypatch)
    with pytest.raises(ProxySourceAdmissionError, match="DENIED"):
        proxy_generator.generate_proxy(
            tmp_path / "ghost.mp4", "browser", tmp_path / "out",
            job_id="job-ghost", catalog=cat, storage_id="storage-a",
        )
    assert calls == [], "a missing source must never reach ffmpeg"


@pytest.mark.behavior_tested
def test_formal_empty_source_denied_before_any_evidence_or_ffmpeg(tmp_path, monkeypatch):
    """Review Minor #2 pin: a 0-B source on a FULL trust chain is
    refused before the ADMITTED ledger row is written (an 'ADMITTED'
    record must never point at a source from which no encode ran) and
    before ffmpeg is reached."""
    media = _media(tmp_path)
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
    # now a 0-B replica record pointing at an empty file, trusted chain:
    cat2 = cat  # same catalog
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    aid_empty = asset_id_for_file(empty)
    cat2.upsert_asset(MediaAsset(source_sha256=aid_empty))
    cat2.add_replica(
        Replica("r-e", aid_empty, "storage-a", "nas-a", str(empty),
                verified=True, verified_at=2)
    )
    cat2.add_evidence(
        VerificationEvidence("e-e", aid_empty, "empty.mp4", "sha256",
                             aid_empty, device_id="dev-a", verdict="PASS",
                             replica_id="r-e")
    )
    calls = _spy_ffmpeg(monkeypatch)
    with pytest.raises(proxy_generator.ProxyInputError, match="empty"):
        proxy_generator.generate_proxy(
            empty, "browser", tmp_path / "out",
            job_id="job-empty", catalog=cat2, storage_id="storage-a",
        )
    assert calls == []
    # no ADMITTED row may have been written for the empty source:
    rows = [e for e in cat2.evidence_for(aid_empty)
            if e.file_name == "admission/job-empty"
            and e.verdict == "ADMITTED"]
    assert rows == [], "a 0-B source must never produce an ADMITTED ledger row"


@pytest.mark.behavior_tested
def test_test_mode_is_isolated_and_never_writes_catalog(tmp_path):
    media = _media(tmp_path)
    # a test-mode run may not be given a real catalog at all:
    cat, _aid, _clip = _catalog(tmp_path)
    with pytest.raises(proxy_generator.ProxyInputError, match="test_mode"):
        proxy_generator.generate_proxy(
            media, "browser", tmp_path / "o1", test_mode=True, catalog=cat
        )
    # the isolated path (no catalog): a fixture flows through with a REAL
    # encode, and nothing is recorded anywhere as a formal verified source.
    before = cat.conn.execute("SELECT COUNT(*) FROM dit22_evidence").fetchone()[0]
    r = proxy_generator.generate_proxy(
        media, "browser", tmp_path / "o2", test_mode=True
    )
    assert r.admission is None
    after = cat.conn.execute("SELECT COUNT(*) FROM dit22_evidence").fetchone()[0]
    assert before == after, "test_mode must not create evidence rows"


@pytest.mark.behavior_tested
def test_admitted_source_encodes_and_records_admission(tmp_path):
    media = _media(tmp_path)
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
    r = proxy_generator.generate_proxy(
        media, "browser", tmp_path / "out",
        job_id="job-ok", catalog=cat, storage_id="storage-a",
    )
    assert r.admission is not None and r.admission.admitted
    rows = [e for e in cat.evidence_for(aid) if e.file_name == "admission/job-ok"]
    assert len(rows) == 1 and rows[0].verdict == "ADMITTED"


# ── API-surface pins ───────────────────────────────────────────────


@pytest.mark.fixture_only
def test_admission_decision_is_immutable_and_field_bounded():
    """The decision carries exactly the fields the gate decides on — no
    authorization surface beyond `admitted` (and never a format mandate)."""
    allowed = {
        "admitted", "reason", "gates", "storage_id", "replica_path",
        "asset_id", "replica_id", "source_sha256", "fingerprint",
    }
    assert set(AdmissionDecision.__dataclass_fields__) == allowed
