#!/usr/bin/env python3
"""
Test Video Analyzer on "Same same" folder - all same song
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyzer.video_analyzer import VideoAnalyzer

# All clips from "Same same" folder
FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"

def main():
    analyzer = VideoAnalyzer()
    
    print("[guitar] GuitarMultiCam Video Analyzer — Same Same Test")
    print("=" * 60)
    
    # Batch analyze all clips
    results = analyzer.analyze_batch(FOLDER)
    
    # Match clips
    print("\n" + "=" * 60)
    print("[link] Matching clips by audio similarity...")
    matched = analyzer.match_clips(results)
    
    # Print detailed segment analysis for first clip
    if results:
        print("\n" + "=" * 60)
        print("[clipboard] SEGMENT DETAILS (first clip):")
        print("-" * 40)
        first_clip = results[0]
        if first_clip.audio and first_clip.audio.segments:
            for i, seg in enumerate(first_clip.audio.segments[:15]):  # First 15 segments
                duration = seg['end'] - seg['start']
                beat_aligned = "[music]" if seg.get('beat_aligned') else "  "
                bars = f"({seg.get('bars', 0)} bars)" if 'bars' in seg else ""
                print(f"  {beat_aligned}[{i+1:2d}] {seg['start']:6.1f}s -> {seg['end']:6.1f}s | {duration:5.1f}s | {seg['type']:8s} {bars}")
            if len(first_clip.audio.segments) > 15:
                print(f"  ... and {len(first_clip.audio.segments) - 15} more segments")
        else:
            print("  No segments found!")
        
        # Show scene detection if available
        if first_clip.video and first_clip.video.scene_changes:
            print("\n" + "-" * 40)
            print(f"[video] SCENE CHANGES ({len(first_clip.video.scene_changes)} detected):")
            for i, scene in enumerate(first_clip.video.scene_changes[:10]):
                print(f"  [{i+1:2d}] {scene['time']:6.1f}s | {scene['type']:6s} | {scene['duration']:.1f}s duration")
            if len(first_clip.video.scene_changes) > 10:
                print(f"  ... and {len(first_clip.video.scene_changes) - 10} more scenes")
        else:
            print("\n  No scene changes detected")
    
    # Print summary with segment counts
    print("\n" + "=" * 60)
    print("[chart] SUMMARY:")
    print("-" * 40)
    
    for clip in results:
        n_segments = len(clip.audio.segments) if clip.audio and clip.audio.segments else 0
        beat_aligned = sum(1 for s in clip.audio.segments if s.get('beat_aligned')) if clip.audio and clip.audio.segments else 0
        n_scenes = len(clip.video.scene_changes) if clip.video and clip.video.scene_changes else 0
        total_duration = sum(s['end'] - s['start'] for s in clip.audio.segments) if clip.audio and clip.audio.segments else 0
        
        print(f"\n{clip.name}")
        print(f"   BPM: {clip.audio.bpm:.1f} | Key: {clip.audio.key}")
        print(f"   Energy: {clip.audio.rms_energy:.4f}")
        print(f"   Segments: {n_segments} total, {beat_aligned} beat-aligned")
        print(f"   Scenes: {n_scenes} | Total music: {total_duration:.0f}s")
        print(f"   Match score: {clip.match_score:.2%}")
    
    # Export
    output = "D:/Powerfull/GuitarMultiCamStudio/same_same_analysis.json"
    analyzer.export_analysis(results, output)
    
    print(f"\n[OK] Analysis complete! Results: {output}")

if __name__ == '__main__':
    main()