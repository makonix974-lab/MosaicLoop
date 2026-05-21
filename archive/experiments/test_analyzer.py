#!/usr/bin/env python3
"""
Test Video Analyzer on Marc's actual clips
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyzer.video_analyzer import VideoAnalyzer

# Test clips from "Last Shot Guitar" folder
CLIPS = [
    "D:/Rush Cam A52s/Last Shot Guitar/20251023_154303.mp4",
    "D:/Rush Cam A52s/Last Shot Guitar/20251101_212302.mp4",
    "D:/Rush Cam A52s/Last Shot Guitar/20251101_213212.mp4",
    "D:/Rush Cam A52s/Last Shot Guitar/20251023_153716.mp4",
]

def main():
    analyzer = VideoAnalyzer()
    
    print("[guitar] GuitarMultiCam Video Analyzer — Test Run")
    print("=" * 60)
    
    results = []
    
    for i, clip_path in enumerate(CLIPS):
        print(f"\n[{i+1}/4] Analyzing: {Path(clip_path).name}")
        print("-" * 40)
        
        analysis = analyzer.analyze_clip(clip_path)
        results.append(analysis)
        
        # Print key findings
        if analysis.audio:
            audio = analysis.audio
            print(f"\n  [chart] Audio Analysis:")
            print(f"     Duration: {audio.duration:.1f}s")
            print(f"     BPM: {audio.bpm:.1f}")
            print(f"     Key: {audio.key}")
            print(f"     Energy RMS: {audio.rms_energy:.4f}")
            print(f"     Dynamic Range: {audio.dynamic_range:.4f}")
            print(f"     Beats detected: {len(audio.beat_times)}")
            print(f"     Onsets detected: {len(audio.onset_times)}")
            
            # Show segments
            if audio.segments:
                print(f"\n  [music] Segments found: {len(audio.segments)}")
                for j, seg in enumerate(audio.segments):
                    print(f"     [{j+1}] {seg['start']:.1f}s -> {seg['end']:.1f}s | {seg['type']} | energy={seg['energy_avg']:.4f}")
    
    # Match clips
    print("\n" + "=" * 60)
    print("[link] Matching clips by audio similarity...")
    matched = analyzer.match_clips(results)
    
    # Export
    output = "D:/Powerfull/GuitarMultiCamStudio/test_analysis.json"
    analyzer.export_analysis(results, output)
    
    print("\n[OK] Analysis complete!")
    print(f"   Results saved: {output}")

if __name__ == '__main__':
    main()