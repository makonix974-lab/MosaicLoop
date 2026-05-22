#!/usr/bin/env python3
"""Test direct grid composition sur fichiers synced existants"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from composer.video_composer import VideoComposer, CompositionConfig
from composer.process_guard import ProcessGuard
import subprocess

ProcessGuard.cleanup_stale()
subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], capture_output=True)

synced_dir = Path("output/_synced")
synced_files = sorted(synced_dir.glob("synced_*.mp4"))

print(f"[Grid Test] Found {len(synced_files)} synced files")
for f in synced_files:
    print(f"  - {f.name}")

class ClipWrap:
    def __init__(self, path):
        self.path = str(path)
        self.name = path.name

config = CompositionConfig(
    output_path="output/test_grid_direct.mp4",
    output_width=1920, output_height=1080,
    grid_cols=2, grid_rows=1,
    grid_cell_width=960, grid_cell_height=1080,
    output_codec="libx264", output_preset="fast", output_crf=23
)

print("\n[Compose] Starting grid composition...")
composer = VideoComposer(config)
clips = [ClipWrap(f) for f in synced_files]

result = composer.compose_grid(clips, show_progress=True, audio_source=0)

if result.get('success'):
    print(f"\n[OK] {result['output_path']}")
else:
    print(f"\n[FAIL] {result.get('error')}")
