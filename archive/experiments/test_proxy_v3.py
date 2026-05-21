#!/usr/bin/env python3
"""Proxy workflow — 900p test (pas d'export full-res)"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.composer.proxy import ProxyManager, ProxyConfig, EditDecisionList, ExportEngine
from src.composer.video_composer import VideoComposer, CompositionConfig
from src.analyzer.video_analyzer import VideoAnalyzer

FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# STEP 1: Proxies 900p
print("[package] Step 1: Proxies 900p")
proxy_mgr = ProxyManager(ProxyConfig(
    proxy_width=1600, proxy_height=900,
    proxy_preset="ultrafast", proxy_crf=28
))
videos = sorted(Path(FOLDER).glob("*.mp4"))[:2]
proxies = proxy_mgr.batch_generate([str(v) for v in videos], show_progress=True)
print(f"   [OK] {len(proxies)} proxies")

# STEP 2: Analyze FROM SOURCE (audio)
print("\n[target] Step 2: Analyse audio")
analyzer = VideoAnalyzer()
all_clips = []
for src_path, proxy_path in proxies:
    t0 = time.time()
    features = analyzer.audio.analyze_full(src_path)
    all_clips.append({
        'source': src_path, 'proxy': proxy_path,
        'name': Path(src_path).stem, 'bpm': features.bpm,
        'beats': features.beat_times, 'segments': features.segments,
    })
    print(f"   {all_clips[-1]['name']}: BPM {features.bpm:.0f}, {len(features.segments)} segs ({time.time()-t0:.0f}s)")

# STEP 3: Compose DIRECTLY on proxies (900p output, no full-res re-encode)
print("\n[link] Step 3: Composition 900p")
composer = VideoComposer(CompositionConfig(
    output_path=str(OUTPUT_DIR / "proxy_900p_final.mp4"),
    output_width=1920, output_height=1080,
    output_crf=23, output_preset="fast",
    min_segment_duration=2.0
))

# Build clip objects from proxy files
class SimpleClip:
    def __init__(self, path, segments):
        self.path = path
        self.audio = type('obj', (object,), {'segments': segments, 'bpm': 0})()
        self.video = type('obj', (object,), {'duration': 0})()
        self.segments = segments
        self.name = Path(path).name
        self.match_score = 0

proxy_clips = []
for c in all_clips:
    segs = [{'start': s['start'], 'end': s['end']} for s in c['segments']]
    clip = SimpleClip(c['proxy'], segs)
    proxy_clips.append(clip)

result = composer.compose(proxy_clips, show_progress=True)
if result.get('success'):
    print(f"   [OK] {result['total_segments']} segments, {result['total_duration']:.0f}s")
else:
    print(f"   [FAIL] {result.get('error')}")

print("\n[OK] Test terminé !")
