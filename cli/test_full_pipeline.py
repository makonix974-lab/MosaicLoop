#!/usr/bin/env python3
"""Pipeline complète : Proxy → Sync → Grid synchronisé"""
import sys, time, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.composer.proxy import ProxyManager, ProxyConfig
from src.composer.video_composer import VideoComposer, CompositionConfig
from src.composer.process_guard import ProcessGuard
from src.sync.audio_sync import SyncManager

FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
OUTPUT = Path(__file__).parent.parent / "output"
OUTPUT.mkdir(exist_ok=True)

ProcessGuard.cleanup_stale()
subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], capture_output=True)

videos = sorted(Path(FOLDER).glob("*.mp4"))[:4]
print(f"🎬 Pipeline: {len(videos)} clips")
print("=" * 50)

# 1. Proxy (parallèle)
print("\n📦 Proxy (parallel)")
t0 = time.time()
mgr = ProxyManager(ProxyConfig(proxy_width=960, proxy_height=540, proxy_crf=30))
proxies = mgr.batch_generate([str(v) for v in videos], max_workers=4)
print(f"   ⏱️  {time.time()-t0:.1f}s")

# 2. Sync audio (trouve les offsets)
print("\n🎯 Sync (source audio → offsets)")
t0 = time.time()
sync = SyncManager()
alignment = sync.align_clips([str(v) for v in videos])
print(f"   ⏱️  {time.time()-t0:.1f}s")

# 3. Appliquer offsets aux proxies (pad + trim)
print("\n🔄 Apply offsets to proxies")
t0 = time.time()
min_offset = min(alignment.offsets.values())
synced_proxies = []

for src_path, proxy_path in proxies:
    name = Path(src_path).name
    offset = alignment.offsets.get(name, 0.0)
    pad = offset - min_offset
    out_path = OUTPUT / f"synced_{name}"
    
    if abs(pad) < 0.05:
        # Presque synced, copie directe
        cmd = ['ffmpeg', '-y', '-i', proxy_path, '-c', 'copy', str(out_path)]
    elif pad > 0:
        # Ajouter du noir + silence au début
        cmd = ['ffmpeg', '-y',
               '-f', 'lavfi', '-t', f'{pad:.3f}', '-i', 'color=c=black:s=960x540:r=30',
               '-f', 'lavfi', '-t', f'{pad:.3f}', '-i', 'anullsrc=r=48000:cl=mono',
               '-i', proxy_path,
               '-filter_complex',
               '[0:v][1:a][2:v][2:a]concat=n=2:v=1:a=1[vo][ao]',
               '-map', '[vo]', '-map', '[ao]',
               '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
               '-c:a', 'aac', str(out_path)]
    else:
        # Trim le début
        trim = -pad
        cmd = ['ffmpeg', '-y', '-ss', f'{trim:.3f}', '-i', proxy_path,
               '-c', 'copy', str(out_path)]
    
    subprocess.run(cmd, capture_output=True, text=True)
    synced_proxies.append(str(out_path))

print(f"   ⏱️  {time.time()-t0:.1f}s")

# 4. Grid 2x2 sur proxies synchronisés
print("\n🔲 Grid 2x2 (synced!)")
t0 = time.time()

class ClipWrap:
    def __init__(self, path):
        self.path = path
        self.name = Path(path).name

config = CompositionConfig(
    output_path=str(OUTPUT / "grid_synced_final.mp4"),
    output_width=1920, output_height=1080,
    output_codec="libx264", output_preset="fast", output_crf=23
)
composer = VideoComposer(config)
grid_clips = [ClipWrap(p) for p in synced_proxies]
result = composer.compose_grid(grid_clips, show_progress=True, audio_source=0)

print(f"\n{'✅' if result.get('success') else '❌'} Grid: {result.get('output_path', result.get('error'))}")
print(f"⏱️  Total: {time.time()-t0:.1f}s")
print(f"\n{'='*50}\nFini!")
