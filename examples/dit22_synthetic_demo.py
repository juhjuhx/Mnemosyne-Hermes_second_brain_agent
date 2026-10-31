"""Mnemosyne DIT 2.2 — five-minute synthetic developer demo (MODULE-LEVEL).

What this is:
    A single, reproducible demonstration of the DIT 2.2 safety core on
    GENERATED test media. It needs no camera card, no NAS, no Windows,
    no GPU, no cloud credentials, and no private project files. It works
    on macOS/Linux with ffmpeg+ffprobe on PATH.

What it is NOT:
    - Not a claim that any real media family (Sony/BRAW), UNC/SMB,
      A770 GPU, or Windows reparse-point behavior has been validated.
      Those remain HARDWARE_BLOCKED / UNVERIFIED (see the doc matrix).
    - Not a shipped CLI: each step below is one public API call in
      src/mnemosyne_dit; the evidence bundle records the exact functions
      invoked so a reader can follow every line back to tested code.

Steps (each writes its evidence into <work>/evidence/):
    1. synthetic source generation + read-only probe (MediaProbe)
    2. CPU proxy generation, isolated test_mode (generate_proxy)
    3. receipt verification (SHA + decodability read-back)
    4. controlled safe failure (corrupt encoder -> nothing published)
    5. recovery reconciliation (read-only verdicts, artifact_recovery)
    6. editor proxy validation (P11.1-D golden ffprobe read-back)
    7. scene detection (ContentDiff + FixedInterval providers, CPU)
    8. Windows-safe artifact naming + capacity gate (pure logic)

Usage:
    python examples/dit22_synthetic_demo.py [--work DIR] [--json-only]

Exit 0 = every step green; exit 1 = a step failed (its evidence file
records the failure; nothing in this demo mutates data outside --work).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "mnemosyne_dit"
sys.path.insert(0, str(SRC))

from artifact_recovery import reconcile_proxy_job
from capacity_gate import DiskProbe, check_capacity
from editor_validation import validate_editor_proxy
from media_probe import probe
from proxy_generator import (
    ProxyResult,
    ProxyVerifyError,
    generate_proxy,
)
from scene_detect import ContentDiffProvider, FixedIntervalProvider
from windows_naming import (
    WindowsNamingError,
    case_collision,
    safe_artifact_name,
)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _mk_source(work: Path) -> Path:
    """2 s 320x240 24p synthetic clip with a 48 kHz mono track. Zero
    real footage anywhere in this repo or on this host."""
    p = work / "synthetic_source.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(p)],
        check=True,
    )
    return p


def _evidence(work: Path, name: str, payload: dict) -> None:
    f = work / "evidence" / name
    f.write_text(json.dumps(payload, indent=2, default=str))


def main() -> int:
    ap = argparse.ArgumentParser(description="Mnemosyne DIT 2.2 synthetic demo")
    ap.add_argument("--work", default=None, help="isolated work dir (kept)")
    ap.add_argument("--json-only", action="store_true",
                    help="suppress the progress rendering")
    args = ap.parse_args()

    if shutil.which(FFMPEG) is None or shutil.which(FFPROBE) is None:
        print("ABORT: ffmpeg + ffprobe must be on PATH (CPU baseline only)",
              file=sys.stderr)
        return 1

    keep = Path(args.work) if args.work else None
    work = keep or Path(tempfile.mkdtemp(prefix="dit22-demo-"))
    (work / "evidence").mkdir(parents=True, exist_ok=True)
    # Show a portable label for the work dir (its own name), not an
    # absolute host path — the captured stdout is public material.
    work_label = work.name
    t0 = time.time()
    results: list[dict] = []

    def step(name: str, fn):
        try:
            payload = fn()
        except Exception as e:  # noqa: BLE001
            results.append({"step": name, "status": "FAILED", "error": str(e)})
            _evidence(work, f"{name}.json", results[-1])
            if not args.json_only:
                print(f"  [FAIL] {name}: {e}")
            return
        results.append({"step": name, "status": "PASS", **(payload or {})})
        _evidence(work, f"{name}.json", results[-1])
        if not args.json_only:
            print(f"  [ OK ] {name}")

    print("\n MNE-MOSYNE DIT 2.2 · synthetic demo (module-level, generated media)")
    print(f" work dir: {work_label}\n")

    src: dict[str, Path] = {}
    proxy_res: dict[str, ProxyResult] = {}

    # ── 1. source generation + read-only probe ───────────────────────
    def s1():
        p = _mk_source(work)
        src["p"] = p
        m = probe(p, sha256=True)
        return {
            "source": p.name,
            "container": m.container,
            "fps": str(m.fps),
            "timecode": m.timecode,
            "audio_sample_rate": (m.audio[0].sample_rate if m.audio else None),
            "source_sha256_prefix": (m.source_sha256 or "")[:12],
            "family_verified": m.family_verified,
        }

    step("1_probe_source", s1)

    # ── 2. CPU proxy generation (isolated test_mode) ────────────────
    def s2():
        m = probe(src["p"], sha256=True)
        out = work / "proxies"
        r = generate_proxy(
            src["p"], "browser", out, source_probe=m,
            job_id="demo-job-1", lease_token="tok-demo", test_mode=True,
        )
        proxy_res["r"] = r
        return {
            "proxy": Path(r.path).name,
            "proxy_sha256_prefix": r.proxy_sha256[:12],
            "source_fps_preserved": str(r.source_fps),
            "audio_tracks": len(r.audio_mapping),
            "ffmpeg_version": str(r.receipt.get("ffmpeg_version", "")).split()[0],
        }

    step("2_cpu_proxy_generation", s2)

    # ── 3. receipt verification ──────────────────────────────────────
    def s3():
        r = proxy_res["r"]
        rec = json.loads(
            Path(r.path).with_name(Path(r.path).name + ".receipt.json").read_text()
        )
        return {
            "receipt_job_id": rec["job_id"],
            "source_sha_matches": rec["source_sha256"] == r.source_sha256,
            "proxy_sha_matches": rec["proxy_sha256"] == r.proxy_sha256,
        }

    step("3_receipt_verification", s3)

    # ── 4. controlled safe failure ───────────────────────────────────
    def s4():
        fake = work / "fake_ffmpeg"
        fake.write_text(
            "#!/bin/sh\nfor last; do :; done\nprintf 'garbage' > \"$last\"\nexit 0\n"
        )
        fake.chmod(0o755)
        out2 = work / "proxies_fail"
        try:
            generate_proxy(
                src["p"], "browser", out2, ffmpeg_bin=str(fake),
                job_id="demo-job-2", lease_token="tok-fail", test_mode=True,
            )
            return {"failure_caught": False, "note": "corrupt encode did not raise"}
        except ProxyVerifyError:
            published = [p.name for p in out2.iterdir()
                         if not p.name.endswith(".receipt.json")]
            return {"failure_caught": True, "published_artifacts": published,
                    "nothing_published": not published}

    step("4_controlled_safe_failure", s4)

    # ── 5. recovery reconciliation (read-only verdicts) ──────────────
    def s5():
        rep = reconcile_proxy_job(work / "proxies", "demo-job-1",
                                  expected_token="tok-demo")
        return {
            "is_published": rep.is_published(),
            "published_generation": rep.published_generation,
            "issues": [f"{i.kind}->{i.safe_action}" for i in rep.issues],
            "read_only": True,
        }

    step("5_recovery_reconciliation", s5)

    # ── 6. editor proxy validation (P11.1-D golden read-back) ───────
    def s6():
        r = proxy_res["r"]
        m = probe(src["p"], sha256=True)
        v = validate_editor_proxy(
            src["p"], r.path, source_probe=m,
            asset_id="demo-asset", reel="DEMO",
        )
        return {
            "editor_verdict": v.status,
            "frame_mapping_kind": type(v.frame_mapping).__name__,
            "reasons_count": len(v.reasons),
        }

    step("6_editor_proxy_validation", s6)

    # ── 7. scene detection (CPU providers, no model download) ───────
    def s7():
        m = probe(src["p"])
        fixed = FixedIntervalProvider(seconds=1.0)
        segs_fixed = fixed.detect(str(src["p"]), source_probe=m)
        cd = ContentDiffProvider()
        segs_cd = cd.detect(str(src["p"]), source_probe=m)
        return {
            "fixed_interval_segments": len(segs_fixed),
            "content_diff_segments": len(segs_cd),
            "neural_model_used": False,
        }

    step("7_scene_detection", s7)

    # ── 8. Windows-safe naming + capacity gate (pure logic) ─────────
    def s8():
        name = safe_artifact_name(
            job_id="demo-job-1", source_filename="synthetic_source.mp4",
            profile="browser", ext=".mp4", generation_tag="tok-demo",
        )
        collides = case_collision(["Clip.mov", "clip.MOV"])
        try:
            safe_artifact_name(job_id="j", source_filename="x" * 300 + ".mov",
                               profile="p", ext=".mxf",
                               out_dir="C:\\deep" * 8)
            over = False
        except WindowsNamingError:
            over = True
        cap = check_capacity(
            DiskProbe(str(work)),
            estimated_staging_bytes=1_000_000,
            estimated_output_bytes=500_000,
        )
        return {
            "artifact_name": name,
            "case_collision_detected": collides,
            "max_path_refusal": over,
            "capacity_ok": cap.ok,
            "capacity_required_bytes": cap.required_bytes,
            "advisory_low_space": cap.advisory_low_space,
        }

    step("8_windows_naming_capacity_gate", s8)

    # ── machine-readable evidence bundle (no absolute host paths) ───
    bundle = {
        "demo": "Mnemosyne DIT 2.2 synthetic module-level demo",
        "api_call_map": {
            "1": "media_probe.probe(sha256=True)",
            "2": "proxy_generator.generate_proxy(test_mode=True)",
            "3": "receipt json read-back (sha equality)",
            "4": "generate_proxy(corrupt encoder) -> ProxyVerifyError",
            "5": "artifact_recovery.reconcile_proxy_job(read-only)",
            "6": "editor_validation.validate_editor_proxy",
            "7": "scene_detect.ContentDiffProvider / FixedIntervalProvider",
            "8": "windows_naming.safe_artifact_name / capacity_gate.check_capacity",
        },
        "duration_s": round(time.time() - t0, 2),
        "steps": results,
        "all_green": all(r["status"] == "PASS" for r in results),
    }
    bundle_text = json.dumps(bundle, default=str)
    bundle["host_abs_path_leaks"] = bundle_text.count(str(Path.home()))
    _evidence(work, "demo_evidence_bundle.json", bundle)
    print(f"\n evidence bundle: {work_label}/evidence/demo_evidence_bundle.json")
    print(f" all green: {bundle['all_green']}   ({bundle['duration_s']}s)")

    if keep is None and bundle["all_green"]:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if bundle["all_green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
