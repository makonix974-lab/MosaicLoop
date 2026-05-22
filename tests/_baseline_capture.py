"""
Baseline metrics capture — runs the full pipeline on synthetic fixtures
and records timing, output size, intermediate files. Used to compare
v0.1 → v0.2 progress.

Usage:
    python tests/_baseline_capture.py
"""

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
SYNCED_DIR = ROOT / "output" / "_synced"
PROXY_DIR = FIXTURES / "_proxy"
OUTPUT = ROOT / "output" / "baseline_4clips.mp4"


def clean_caches() -> None:
    for d in [SYNCED_DIR, PROXY_DIR]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    if OUTPUT.exists():
        OUTPUT.unlink()


def main() -> dict:
    from pipeline import Pipeline, PipelineConfig

    clean_caches()

    cfg = PipelineConfig(
        clips=[str(FIXTURES / f"clip_{x}.mp4") for x in "abcd"],
        output_path=str(OUTPUT),
        layout="2x2",
        use_proxy=True,
        proxy_width=320, proxy_height=240,
        output_width=1920, output_height=1080,
        output_fps=30,
        max_workers=4,
    )

    t0 = time.time()
    result = Pipeline(cfg).run()
    elapsed = time.time() - t0

    output_mb = OUTPUT.stat().st_size / 1024 / 1024 if OUTPUT.exists() else 0
    synced = list(SYNCED_DIR.glob("*.mp4")) if SYNCED_DIR.exists() else []
    synced_mb = sum(f.stat().st_size for f in synced) / 1024 / 1024

    metrics = {
        "success": bool(result.get("success")),
        "total_seconds": round(elapsed, 2),
        "output_mb": round(output_mb, 2),
        "intermediate_files": len(synced),
        "intermediate_mb": round(synced_mb, 2),
        "error": result.get("error"),
    }
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
