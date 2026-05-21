#!/usr/bin/env python3
"""Proxy workflow test — v2"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.composer.proxy import ProxyManager, ProxyConfig, EditDecisionList, ExportEngine
from src.analyzer.video_analyzer import VideoAnalyzer

FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# STEP 1: Generate proxies (540p)
print("[package] Step 1: Generate proxies")
proxy_mgr = ProxyManager(ProxyConfig(proxy_width=960, proxy_height=540, proxy_preset="ultrafast", proxy_crf=28))
videos = sorted(Path(FOLDER).glob("*.mp4"))[:2]  # 2 clips for speed
proxies = proxy_mgr.batch_generate([str(v) for v in videos])
print(f"   [OK] {len(proxies)} proxies")

# STEP 2: Analyze proxies (fast)
print("\n[target] Step 2: Analyze proxies")
analyzer = VideoAnalyzer()
proxy_clips = []
for src, proxy in proxies:
    clip = analyzer.analyze_clip(proxy, detect_scenes=False)
    clip._source = src
    proxy_clips.append(clip)

# STEP 3: Build EDL from segments
print("\n[clipboard] Step 3: Build Edit Decision List")
edl = EditDecisionList()
for src, proxy in proxies:
    edl.add_source(src)
for clip in proxy_clips:
    sid = Path(clip._source).stem
    if clip.audio and clip.audio.segments:
        for seg in clip.audio.segments[:3]:  # first 3 segments per clip for quick test
            edl.add_segment(sid, seg['start'], seg['end'], seg.get('type', 'music'))

edl_path = OUTPUT_DIR / "edl_test_v2.json"
edl.export(str(edl_path))
print(f"   [OK] {len(edl.segments)} edits, {edl.get_total_duration():.1f}s")

# STEP 4: Export from full-res sources
print("\n[video] Step 4: Export full-res from EDL")
exporter = ExportEngine()
result = exporter.export_linear(edl, str(OUTPUT_DIR / "final_proxy_test.mp4"))
print(f"   {'[OK]' if result.get('success') else '[FAIL]'} Output: {result.get('output_path', result.get('error'))}")

print("\n[OK] Proxy workflow complete!")
