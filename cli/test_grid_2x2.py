#!/usr/bin/env python3
"""Test 2x2 grid with audio — the real deal"""
import sys, time, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.composer.proxy import ProxyManager, ProxyConfig
from src.composer.video_composer import VideoComposer, CompositionConfig
from src.composer.process_guard import ProcessGuard

FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Clean any leftovers
ProcessGuard.cleanup_stale()
subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], capture_output=True)

# Step 1: Clean old proxies (they have no audio) + regen
print("📦 Generating proxies WITH audio...")
import shutil
shutil.rmtree(f"{FOLDER}/_proxy", ignore_errors=True)

proxy_mgr = ProxyManager(ProxyConfig(
    proxy_width=1280, proxy_height=720,
    proxy_preset="ultrafast", proxy_crf=28
))

videos = sorted(Path(FOLDER).glob("*.mp4"))[:4]
proxies = proxy_mgr.batch_generate([str(v) for v in videos], show_progress=True)
print(f"   ✅ {len(proxies)} proxies with audio")

# Step 3: Simple clip wrapper
class GridClip:
    def __init__(self, path):
        self.path = str(path)
        self.name = Path(path).name
        self.audio = type('o', (), {'duration': 100, 'bpm': 0})()
        self.video = type('o', (), {'duration': 100})()
        self.match_score = 0
        self.segments = []

grid_clips = [GridClip(p[1]) for p in proxies]

# Step 4: 2x2 grid with audio
print("\n🎬 Rendering 2x2 grid...")
config = CompositionConfig(
    output_path=str(OUTPUT_DIR / "grid_2x2_audio.mp4"),
    output_width=1920, output_height=1080,
    output_crf=23, output_preset="fast"
)
composer = VideoComposer(config)
result = composer.compose_grid(grid_clips, show_progress=True, audio_source=0)

if result.get('success'):
    print(f"\n   ✅ Grid 2x2 créé !")
    print(f"   📁 {result['output_path']}")
    print(f"   📺 {result['grid']}, {result['clips_used']} clips")
else:
    print(f"\n   ❌ {result.get('error')}")
