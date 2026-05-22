#!/usr/bin/env python3
"""Debug: afficher la commande FFmpeg grid sans l'exécuter"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from composer.video_composer import VideoComposer, CompositionConfig

synced_dir = Path("output/_synced")
synced_files = sorted(synced_dir.glob("synced_*.mp4"))

print(f"[Debug] {len(synced_files)} synced files")

class ClipWrap:
    def __init__(self, path):
        self.path = str(path)
        self.name = path.name

config = CompositionConfig(
    output_path="output/test_grid_debug.mp4",
    output_width=1920, output_height=1080,
    grid_cols=2, grid_rows=1,
    grid_cell_width=960, grid_cell_height=1080,
)

composer = VideoComposer(config)
clips = [ClipWrap(f) for f in synced_files]

# Build the filter manually to see what's generated
filter_str = composer._build_grid_filter(clips)
print("\n[Filter Complex]")
print(filter_str)

# Build command manually
cmd = [composer.ffmpeg, '-y']
for clip in clips:
    cmd.extend(['-i', clip.path])

cmd.extend(['-filter_complex', filter_str])
cmd.extend(['-map', '[grid]'])
cmd.extend(['-map', f'0:a'])  # Audio from first clip
cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
cmd.extend(['-c:v', config.output_codec, '-preset', 'fast', '-crf', str(config.output_crf)])
cmd.append(config.output_path)

print("\n[FFmpeg Command]")
print(' '.join(cmd))
print("\n[Test] Command built successfully (not executed)")
