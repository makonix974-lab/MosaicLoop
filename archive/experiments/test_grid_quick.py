#!/usr/bin/env python3
"""Quick grid filter test - skip audio, test filter only"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.composer.video_composer import VideoComposer, CompositionConfig
from src.analyzer.video_analyzer import ClipAnalysis

FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"

# Create mock clips with just paths (no analysis needed for grid)
clips = []
for name in ["20251109_172852.mp4", "20251109_173215.mp4", "20251109_174539.mp4", "20251109_175104.mp4"]:
    c = ClipAnalysis(path=f"{FOLDER}/{name}", name=name)
    clips.append(c)

config = CompositionConfig(output_path="D:/Powerfull/GuitarMultiCamStudio/output/grid_final.mp4")
composer = VideoComposer(config)

# Show the generated filter
filter_str = composer._build_xstack_filter(clips)
print("FILTER:")
print(filter_str)
print()

# Run composition
result = composer.compose_grid(clips)
print("RESULT:", result)
