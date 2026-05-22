"""
Final validation — P11.

Runs the v0.2 pipeline on the real production rushes and compares the
output to a v0.1 baseline (frame extracted at 50% of duration). This is
the automated visual check we promised in the refactor plan.

Usage:
    python tests/_validate_v0.2.py

Requires:
    - Real rushes in D:/Rush Cam A52s/Last Shot Guitar/Same same/
    - Existing v0.1 baseline at output/final_2x2_grid.mp4 (made earlier today)

Pixel-difference threshold:
    Mean absolute pixel difference (per channel, 0..255) < 5.0
    => visually equivalent under typical encoder non-determinism.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import numpy as np

RUSHES_DIR = Path("D:/Rush Cam A52s/Last Shot Guitar/Same same")
N_CLIPS = 4

V01_BASELINE = ROOT / "output" / "final_2x2_grid.mp4"
V02_OUTPUT = ROOT / "output" / "v0.2_final.mp4"
FRAME_DIR = ROOT / "output" / "_frames"


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def _extract_frame(video: Path, at_seconds: float, out_png: Path) -> None:
    """Extract one PNG frame at a given timestamp."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{at_seconds:.3f}",
            "-i", str(video),
            "-frames:v", "1",
            str(out_png),
        ],
        check=True, capture_output=True, timeout=30,
    )


def _load_image_as_array(png_path: Path) -> np.ndarray:
    """Load a PNG into numpy via FFmpeg's rawvideo output (no Pillow dep)."""
    # Probe size
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "stream=width,height",
         "-of", "json", str(png_path)],
        capture_output=True, text=True, timeout=10,
    )
    info = json.loads(probe.stdout)["streams"][0]
    w, h = int(info["width"]), int(info["height"])

    raw = subprocess.run(
        ["ffmpeg", "-v", "error",
         "-i", str(png_path),
         "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-"],
        check=True, capture_output=True, timeout=20,
    ).stdout
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
    return arr


def run_v02_pipeline() -> tuple[float, dict]:
    """Run v0.2 pipeline on the 4 real rushes. Returns (elapsed, result)."""
    from pipeline import Pipeline, PipelineConfig

    rushes = sorted(RUSHES_DIR.glob("*.mp4"))[:N_CLIPS]
    assert len(rushes) == N_CLIPS, f"need {N_CLIPS} rushes, found {len(rushes)}"

    # Clean caches so the timing is honest
    for d in [
        ROOT / "output" / "_synced",
        RUSHES_DIR / "_proxy",
    ]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    if V02_OUTPUT.exists():
        V02_OUTPUT.unlink()

    cfg = PipelineConfig(
        clips=[str(r) for r in rushes],
        output_path=str(V02_OUTPUT),
        layout="2x2",
        use_proxy=True,
        proxy_width=960, proxy_height=540,
        output_width=1920, output_height=1080,
        output_fps=30,
        max_workers=4,
        use_cache=False,  # honest cold timing
    )
    t0 = time.time()
    result = Pipeline(cfg).run()
    return time.time() - t0, result


def compare_outputs() -> dict:
    """Frame-level diff between v0.1 baseline and v0.2 output."""
    assert V01_BASELINE.exists(), f"missing v0.1 baseline: {V01_BASELINE}"
    assert V02_OUTPUT.exists(), f"missing v0.2 output: {V02_OUTPUT}"

    d01 = _ffprobe_duration(V01_BASELINE)
    d02 = _ffprobe_duration(V02_OUTPUT)
    print(f"  v0.1 duration: {d01:.2f}s")
    print(f"  v0.2 duration: {d02:.2f}s")

    # Compare a frame at 50% of the SHORTER duration to avoid going past EOF
    sample_t = min(d01, d02) * 0.5

    frame_a = FRAME_DIR / "v0.1_50pct.png"
    frame_b = FRAME_DIR / "v0.2_50pct.png"
    _extract_frame(V01_BASELINE, sample_t, frame_a)
    _extract_frame(V02_OUTPUT, sample_t, frame_b)

    a = _load_image_as_array(frame_a)
    b = _load_image_as_array(frame_b)

    if a.shape != b.shape:
        return {
            "match": False,
            "reason": f"frame size mismatch: v0.1={a.shape} v0.2={b.shape}",
            "duration_v01": d01, "duration_v02": d02,
        }

    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.float64)
    mean_diff = float(diff.mean())
    max_diff = float(diff.max())
    pct_pixels_close = float((diff.max(axis=2) < 8).mean() * 100)

    return {
        "match": mean_diff < 5.0,
        "mean_abs_diff": round(mean_diff, 3),
        "max_abs_diff": round(max_diff, 3),
        "pct_pixels_close_within_8": round(pct_pixels_close, 2),
        "duration_v01": round(d01, 2),
        "duration_v02": round(d02, 2),
        "duration_diff_seconds": round(abs(d01 - d02), 3),
        "sample_timestamp": round(sample_t, 2),
    }


def main() -> int:
    print("=" * 60)
    print("P11 Validation — v0.2 on real rushes")
    print("=" * 60)

    if not RUSHES_DIR.exists():
        print(f"[SKIP] Rushes directory not found: {RUSHES_DIR}")
        return 0
    if not V01_BASELINE.exists():
        print(f"[SKIP] v0.1 baseline not found: {V01_BASELINE}")
        print("       (Run the v0.1 pipeline first to produce a baseline.)")
        return 0

    print(f"\n[1/2] Running v0.2 pipeline on {N_CLIPS} rushes (cold)...")
    elapsed, result = run_v02_pipeline()
    if not result.get("success"):
        print(f"[FAIL] Pipeline failed: {result.get('error')}")
        return 1

    print(f"      Done in {elapsed:.2f}s")
    out_mb = V02_OUTPUT.stat().st_size / 1024 / 1024
    print(f"      Output: {V02_OUTPUT.name} ({out_mb:.1f} MB)")

    # Cache warm run
    print("\n[1b] Cache warm run (use_cache=True)...")
    from pipeline import Pipeline, PipelineConfig
    rushes = sorted(RUSHES_DIR.glob("*.mp4"))[:N_CLIPS]
    cfg = PipelineConfig(
        clips=[str(r) for r in rushes],
        output_path=str(V02_OUTPUT),
        layout="2x2",
        use_proxy=True,
        proxy_width=960, proxy_height=540,
        output_width=1920, output_height=1080,
        output_fps=30,
        max_workers=4,
        use_cache=True,
    )
    t0 = time.time()
    Pipeline(cfg).run()
    warm = time.time() - t0
    print(f"      Warm run: {warm:.2f}s (vs {elapsed:.2f}s cold = {elapsed/warm:.1f}x)")

    print("\n[2/2] Comparing frames at 50% duration...")
    comparison = compare_outputs()
    print(json.dumps(comparison, indent=2))

    if comparison["match"]:
        print("\n[OK] Frame comparison passed (mean diff < 5/255).")
    else:
        print("\n[FAIL] Frame comparison did not match v0.1 baseline.")
        return 1

    # Save final metrics
    metrics = {
        "v0.2_cold_seconds": round(elapsed, 2),
        "v0.2_warm_seconds": round(warm, 2),
        "v0.2_speedup_warm": round(elapsed / warm, 2),
        "v0.2_output_mb": round(out_mb, 2),
        "frame_comparison": comparison,
    }
    metrics_path = ROOT / "docs" / "v0.2-METRICS.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\nMetrics saved to {metrics_path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
