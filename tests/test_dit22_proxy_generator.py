"""P11 proxy generator — contract tests for `proxy_generator`.

Synthetic golden fixtures (ffmpeg-generated, `tmp_path`, zero real
media). Spec: docs/engineering/spec/P11-proxy-generator.md.

Markers: `@behavior_tested` = real ffmpeg encode + ffprobe read-back;
`@fixture_only` = pure logic (capability matrix / stale detection on a
crafted directory) without a codec run.
"""

import json
import stat
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "mnemosyne_dit"
sys.path.insert(0, str(_SRC))

import media_probe
import proxy_generator
from media_probe import probe
from proxy_generator import (
    ProxyEncodeError,
    ProxyInputError,
    ProxyVerifyError,
    delete_proxies,
    find_stale_proxies,
    generate_proxy,
)

FFMPEG = "ffmpeg"


def _mk(path: Path, *ffmpeg_args: str) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         *ffmpeg_args, str(path)],
        check=True,
    )
    assert path.exists() and path.stat().st_size > 0
    return path


def _source_with_audio(tmp_path: Path) -> Path:
    """2-second 320x240 24p lavfi source with one 48k mono audio track."""
    return _mk(
        tmp_path / "src.mp4",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
    )


# ── 1. browser golden: real H.264 MP4, read-back verified ──────────


@pytest.mark.behavior_tested
def test_browser_golden_publishes_h264_mp4(tmp_path):
    src = _source_with_audio(tmp_path)
    out = tmp_path / "proxies"
    r = generate_proxy(src, "browser", out, job_id="job-1", lease_token="tok-A", test_mode=True)

    assert r.codec == "h264" and r.container == "mp4" and r.degraded is False
    p = Path(r.path)
    assert p.exists() and p.stat().st_size > 0
    # ffprobe read-back (never trust the encoder's self-report):
    back = media_probe.run_ffprobe_json(p)
    v = next(s for s in back["streams"] if s["codec_type"] == "video")
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert r.duration_s is not None and abs(r.duration_s - 2.0) < 0.2
    # atomic publish: receipt present next to the published file
    receipt_path = p.with_name(p.name + ".receipt.json")
    assert receipt_path.exists()
    rec = json.loads(receipt_path.read_text())
    assert rec["job_id"] == "job-1" and rec["lease_token"] == "tok-A"
    assert rec["source_sha256"] == r.source_sha256
    assert rec["proxy_sha256"] == r.proxy_sha256
    assert rec["ffmpeg_version"].startswith("ffmpeg ")
    # no staging leftovers in the published dir
    assert not (out / ".staging").exists() or not any(
        (out / ".staging").iterdir()
    ), "staging must be cleaned after a successful publish"


# ── 2. source correspondence copied from the probe, not recomputed ─


@pytest.mark.behavior_tested
def test_source_correspondence_copied_from_probe(tmp_path):
    src = _source_with_audio(tmp_path)
    m = probe(src, sha256=True)
    out = tmp_path / "proxies"
    r = generate_proxy(
        src, "browser", out, source_probe=m, job_id="job-2", lease_token="t2",
        test_mode=True,
    )
    assert r.source_fps == Fraction(24)
    assert r.source_timecode == "non-drop"
    assert len(r.audio_mapping) == 1
    am = r.audio_mapping[0]
    assert am["sample_rate"] == 48000 and am["index"] == 1
    # receipt carries the source fingerprint too (drift detection):
    rec = json.loads(
        Path(r.path).with_name(Path(r.path).name + ".receipt.json").read_text()
    )
    assert rec["source_sha256"] == m.source_sha256


# ── 3. corrupt encode -> verification gate, nothing published ─────


@pytest.mark.behavior_tested
def test_corrupt_encode_fails_verification_and_publishes_nothing(tmp_path):
    src = _source_with_audio(tmp_path)
    fake = tmp_path / "fake_ffmpeg"
    fake.write_text(
        "#!/bin/sh\n"
        "for last; do :; done\n"
        "printf 'garbage' > \"$last\"\n"
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    out = tmp_path / "proxies"
    with pytest.raises(ProxyVerifyError) as exc:
        generate_proxy(
            src, "browser", out, ffmpeg_bin=str(fake),
            job_id="job-3", lease_token="t3", test_mode=True,
        )
    assert "not decodable" in str(exc.value) or "verify" in str(exc.value).lower()
    # nothing may have landed in the published directory:
    assert not out.exists() or not any(
        f.name.endswith((".mp4", ".mov", ".mxf")) for f in out.iterdir()
    )


# ── 4. receipt fencing: stale-token artifacts are detectable ───────


@pytest.mark.behavior_tested
def test_stale_lease_token_artifact_is_detectable(tmp_path):
    a = _mk(tmp_path / "a.mp4",
            "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p")
    b = _mk(tmp_path / "b.mp4",
            "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p")
    out = tmp_path / "proxies"
    generate_proxy(a, "browser", out, job_id="job-4", lease_token="tok-old", test_mode=True)
    generate_proxy(b, "browser", out, job_id="job-4", lease_token="tok-now", test_mode=True)
    # current token is tok-now: the tok-old artifact is stale & discardable.
    # Artifacts are job-namespaced: {job_tag}__{src.stem}__{profile}{ext}.
    stale = find_stale_proxies(out, "job-4", expected_token="tok-now")
    assert "job-4__a__browser.mp4" in stale
    assert "job-4__b__browser.mp4" not in stale


# ── 4b. re-entry (same job) is an idempotent atomic replace ───────


@pytest.mark.behavior_tested
def test_reentry_same_job_is_idempotent_replace(tmp_path):
    src = _source_with_audio(tmp_path)
    out = tmp_path / "proxies"
    r1 = generate_proxy(src, "browser", out, job_id="job-r", lease_token="tk", test_mode=True)
    r2 = generate_proxy(src, "browser", out, job_id="job-r", lease_token="tk", test_mode=True)
    # same job + token republishes atomically to the SAME path (no dup):
    assert r1.path == r2.path
    files = [f.name for f in out.iterdir() if f.name.endswith(".mp4")]
    assert files.count(Path(r2.path).name) == 1, \
        "re-entry must replace, not duplicate"
    # the artifact + its receipt still form a valid committed pair:
    rec = json.loads(Path(r2.path).with_name(Path(r2.path).name + ".receipt.json").read_text())
    assert rec["job_id"] == "job-r" and rec["status"] == "published"


# ── 4c. two DIFFERENT jobs, same source+profile+out: no collision ──


@pytest.mark.behavior_tested
def test_different_jobs_same_source_do_not_collide(tmp_path):
    src = _source_with_audio(tmp_path)
    out = tmp_path / "proxies"
    j1 = generate_proxy(src, "browser", out, job_id="job-A", lease_token="tA", test_mode=True)
    j2 = generate_proxy(src, "browser", out, job_id="job-B", lease_token="tB", test_mode=True)
    # distinct artifacts, neither clobbered:
    assert j1.path != j2.path
    assert Path(j1.path).exists() and Path(j2.path).exists()
    rec1 = json.loads(Path(j1.path).with_name(Path(j1.path).name + ".receipt.json").read_text())
    rec2 = json.loads(Path(j2.path).with_name(Path(j2.path).name + ".receipt.json").read_text())
    assert rec1["job_id"] == "job-A" and rec2["job_id"] == "job-B"
    # each job's receipt is its own (the second publish did not overwrite
    # the first job's attribution):
    stale_a = find_stale_proxies(out, "job-A", expected_token="tA")
    assert Path(j1.path).name not in stale_a


# ── 5. proxies are deletable & rebuildable; source untouched ───────


@pytest.mark.behavior_tested
def test_delete_and_rebuild_source_untouched(tmp_path):
    src = _source_with_audio(tmp_path)
    out = tmp_path / "proxies"
    r1 = generate_proxy(src, "browser", out, job_id="job-5", lease_token="t5", test_mode=True)
    src_before = media_probe._sha256_file(src)

    delete_proxies(out, job_id="job-5")
    assert not Path(r1.path).exists()
    assert not Path(r1.path + ".receipt.json").exists()

    r2 = generate_proxy(src, "browser", out, job_id="job-5", lease_token="t5", test_mode=True)
    assert Path(r2.path).exists()
    # the source was never written — byte-identical through it all:
    assert media_probe._sha256_file(src) == src_before
    assert r1.source_sha256 == r2.source_sha256, \
        "same source + same profile must rebuild to the same source fingerprint"


# ── 6. the original is NEVER modified (explicit) ───────────────────


@pytest.mark.behavior_tested
def test_source_file_hash_invariant_across_encode(tmp_path):
    src = _source_with_audio(tmp_path)
    before = media_probe._sha256_file(src)
    generate_proxy(src, "browser", tmp_path / "out",
                   job_id="job-6", lease_token="t6", test_mode=True)
    assert media_probe._sha256_file(src) == before


# ── 7. editor target: honest capability decision, never a fake claim ─


@pytest.mark.behavior_tested
def test_editor_profile_honest_capability(tmp_path):
    src = _source_with_audio(tmp_path)
    out = tmp_path / "proxies"
    r = generate_proxy(src, "editor", out, job_id="job-7", lease_token="t7", test_mode=True)
    # This host HAS a prores encoder (10-bit yuv422p10le) and NO dnxhr,
    # so the honest result is real ProRes Proxy (not a h264 impostor):
    assert r.codec in ("dnxhr", "prores", "h264"), "sanity"
    if "prores" in proxy_generator.detect_editor_capabilities(FFMPEG):
        assert r.codec == "prores" and r.degraded is False, \
            "prores is present -> editor must NOT silently degrade"
    back = media_probe.run_ffprobe_json(Path(r.path))
    v = next(s for s in back["streams"] if s["codec_type"] == "video")
    assert v["codec_name"] == r.codec, \
        "the artifact must actually carry the claimed codec"


@pytest.mark.behavior_tested
def test_editor_degrades_honestly_when_no_editor_encoder(tmp_path, monkeypatch):
    src = _source_with_audio(tmp_path)
    monkeypatch.setattr(
        proxy_generator, "detect_editor_capabilities", lambda bin_: {}
    )
    r = generate_proxy(src, "editor", tmp_path / "out",
                       job_id="job-7b", lease_token="t7b", test_mode=True)
    assert r.degraded is True and r.codec == "h264", \
        "no DNxHR/ProRes encoder -> honest h264 fallback, degraded=True"
    assert "prores" not in r.codec and "dnxhr" not in r.codec


# ── 8. URL source refused before any subprocess ────────────────────


@pytest.mark.behavior_tested
def test_url_source_refused_before_subprocess(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        proxy_generator, "_run_ffmpeg",
        lambda *a, **k: calls.append(a) or (0, b"", b""),
    )
    with pytest.raises(ProxyInputError, match="network URL"):
        generate_proxy("http://example.com/clip.mp4", "browser", tmp_path / "o")
    assert not calls, "a URL must be refused before ffmpeg ever runs"


# ── 9. corrupt / empty source: fail-closed, no garbage published ───


@pytest.mark.behavior_tested
def test_empty_source_refused_without_ffmpeg(tmp_path, monkeypatch):
    src = tmp_path / "empty.mp4"
    src.write_bytes(b"")
    calls: list = []
    monkeypatch.setattr(
        proxy_generator, "_run_ffmpeg",
        lambda *a, **k: calls.append(a) or (0, b"", b""),
    )
    with pytest.raises(ProxyInputError, match="empty"):
        generate_proxy(src, "browser", tmp_path / "o")
    assert not calls


@pytest.mark.behavior_tested
def test_corrupt_source_raises_encode_error_publishes_nothing(tmp_path):
    good = _source_with_audio(tmp_path)
    bad = tmp_path / "trunc.mp4"
    bad.write_bytes(good.read_bytes()[:200])
    out = tmp_path / "proxies"
    with pytest.raises(ProxyEncodeError) as exc:
        generate_proxy(bad, "browser", out, job_id="job-9", lease_token="t9", test_mode=True)
    assert "ffmpeg" in str(exc.value).lower()
    assert not out.exists() or not any(
        f.name.endswith((".mp4", ".mov", ".mxf")) for f in out.iterdir()
    )


# ── 10. a proxy NEVER raises an archive safety verdict ─────────────


@pytest.mark.behavior_tested
def test_proxy_completion_does_not_touch_safety_verdict(tmp_path):
    import inspect
    src = _source_with_audio(tmp_path)
    out = tmp_path / "proxies"
    r = generate_proxy(src, "browser", out, job_id="job-10", lease_token="t10", test_mode=True)
    # structural: the generator API has no verdict/architecture surface
    params = set(inspect.signature(generate_proxy).parameters)
    assert not {"verdict", "safety_verdict", "archive_verdict"} & params
    # behavioral: the published dir holds ONLY proxy artifacts + receipts,
    # no verdict/safety side-effect files:
    contents = sorted(f.name for f in out.iterdir())
    for name in contents:
        assert name.endswith((".mp4", ".mov", ".mxf", ".receipt.json")), \
            f"unexpected side-effect file {name!r} in the proxy dir"
    assert r.path in [str(p) for p in out.iterdir() if p.name.endswith(".mp4")]


# ── pure-logic pins (no codec runs) ────────────────────────────────


@pytest.mark.fixture_only
def test_find_stale_proxies_on_crafted_receipts(tmp_path):
    out = tmp_path / "proxies"
    out.mkdir()
    for name, token in [("a__browser.mp4", "old"), ("b__browser.mp4", "new")]:
        (out / name).write_bytes(b"x")
        (out / (name + ".receipt.json")).write_text(
            json.dumps({"job_id": "J", "lease_token": token})
        )
    assert find_stale_proxies(out, "J", expected_token="new") == \
        ["a__browser.mp4"]
    assert find_stale_proxies(out, "J", expected_token="old") == \
        ["b__browser.mp4"]
    # unknown job -> nothing stale (a different job's artifacts are not
    # this job's to judge):
    assert find_stale_proxies(out, "OTHER", expected_token="new") == []


@pytest.mark.fixture_only
def test_delete_proxies_by_job_id_only(tmp_path):
    out = tmp_path / "proxies"
    out.mkdir()
    (out / "a__browser.mp4").write_bytes(b"x")
    (out / "a__browser.mp4.receipt.json").write_text(
        json.dumps({"job_id": "J1"})
    )
    (out / "b__editor.mov").write_bytes(b"y")
    (out / "b__editor.mov.receipt.json").write_text(
        json.dumps({"job_id": "J2"})
    )
    delete_proxies(out, job_id="J1")
    assert not (out / "a__browser.mp4").exists()
    assert (out / "b__editor.mov").exists(), "other jobs' artifacts survive"
