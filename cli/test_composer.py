#!/usr/bin/env python3
"""
Test Video Composer on Marc's "Same same" clips
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyzer.video_analyzer import VideoAnalyzer
from src.composer.video_composer import VideoComposer, CompositionConfig, SmartComposer


def main():
    FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
    OUTPUT_DIR = Path(__file__).parent.parent / "output"
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    print("🎬 GuitarMultiCam Video Composer — Test")
    print("=" * 60)
    
    # Load previous analysis
    analysis_path = Path(__file__).parent.parent / "same_same_analysis.json"
    
    if analysis_path.exists():
        print(f"📂 Loading analysis from {analysis_path}")
        with open(analysis_path, 'r') as f:
            data = json.load(f)
        print(f"   Loaded {data['total_clips']} clips")
    else:
        print("❌ No analysis found. Run analyzer first!")
        return
    
    # Create composition config
    config = CompositionConfig(
        output_path=str(OUTPUT_DIR / "composition_linear.mp4"),
        grid_cols=2,
        grid_rows=2,
        output_fps=30,
        output_crf=23,
        min_segment_duration=2.0,
        transition_duration=0.25
    )
    
    # Create composer
    composer = SmartComposer(config)
    
    # Load clips with their analysis
    clips = []
    for clip_data in data['clips']:
        # Re-analyze to get full data
        analyzer = VideoAnalyzer()
        clip = analyzer.analyze_clip(clip_data['path'])
        clips.append(clip)
    
    print(f"\n🎞️ Composing video from {len(clips)} clips...")
    print("-" * 40)
    
    # Method 1: Linear composition (sequential segments)
    print("\n📹 Linear Composition:")
    result = composer.compose(clips)
    
    if result.get('success'):
        print(f"   ✅ Created: {result['output_path']}")
        print(f"   📊 Segments: {result['total_segments']}")
        print(f"   ⏱️ Duration: {result['total_duration']:.1f}s")
        
        # Show segment breakdown
        print("\n   Segment plan:")
        for i, seg in enumerate(result['segments'][:10]):
            clip_name = Path(seg['clip_path']).name
            print(f"   [{i+1:2d}] {seg['time']:.1f}s | {clip_name[:20]:20s} | {seg['duration']:.1f}s")
        if len(result['segments']) > 10:
            print(f"   ... and {len(result['segments']) - 10} more segments")
    else:
        print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
    
    # Method 2: Grid composition (2x2)
    print("\n📊 Grid Composition (2x2):")
    grid_output = OUTPUT_DIR / "composition_grid.mp4"
    grid_result = composer.compose_grid(clips, str(grid_output))
    
    if grid_result.get('success'):
        print(f"   ✅ Created: {grid_result['output_path']}")
        print(f"   📺 Clips used: {grid_result['clips_used']}")
    else:
        print(f"   ❌ Error: {grid_result.get('error', 'Unknown error')}")
    
    print("\n" + "=" * 60)
    print("✅ Composition test complete!")
    print(f"📁 Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()