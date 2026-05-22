#!/usr/bin/env python3
"""Test minimal avec la Pipeline corrigée"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("[1] Imports...")
from pipeline import Pipeline, PipelineConfig
from composer.process_guard import ProcessGuard
import subprocess

print("[2] Cleanup...")
ProcessGuard.cleanup_stale()
subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], capture_output=True)

print("[3] Get videos...")
FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
videos = sorted(Path(FOLDER).glob("*.mp4"))[:2]  # Only 2 videos for speed
print(f"    Found {len(videos)} videos")

print("[4] Run pipeline...")
config = PipelineConfig(
    clips=[str(v) for v in videos],
    output_path="output/test_pipeline_minimal.mp4",
    layout="2x1",  # 2x1 for 2 clips
    use_proxy=True,
    proxy_width=960,
    proxy_height=540,
    max_workers=2
)

pipeline = Pipeline(config)
result = pipeline.run()

if result.get('success'):
    print(f"\n[OK] Success! Output: {result['output_path']}")
    print(f"    Elapsed: {result.get('elapsed', 0)}s")
else:
    print(f"\n[FAIL] {result.get('error', 'Unknown error')}")
