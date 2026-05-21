#!/usr/bin/env python3
"""
Quick test compose - Trim clips and make 2x2 grid
"""

import subprocess
import sys
from pathlib import Path

# Clips from Group 1 (240s)
CLIPS = [
    "D:/Rush Cam A52s/Last Shot Guitar/20251023_154303.mp4",
    "D:/Rush Cam A52s/Last Shot Guitar/20251101_212302.mp4",
    "D:/Rush Cam A52s/Last Shot Guitar/20251101_213212.mp4",
    "D:/Rush Cam A52s/Last Shot Guitar/20251023_153716.mp4",
]

OUTPUT = "D:/Powerfull/GuitarMultiCamStudio/test_2x2.mp4"
DURATION = 30  # seconds per clip for test

def get_silence_trim(filepath):
    """Find start/end of non-silent audio using ffmpeg."""
    cmd = [
        'ffmpeg', '-i', filepath,
        '-af', 'silencedetect=n=-30dB:d=0.3',
        '-f', 'null', '-'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    start = 0
    end = None
    
    for line in result.stderr.split('\n'):
        if 'silencedetect' in line.lower():
            if 'silence_start' in line:
                parts = line.split('silence_start: ')
                if len(parts) > 1:
                    start = float(parts[1].split(' ')[0])
            elif 'silence_end' in line:
                parts = line.split('silence_end: ')
                if len(parts) > 1 and end is None:
                    end = float(parts[1].split(' ')[0])
    
    return start, end

def trim_and_compose():
    print("[video] GuitarMultiCam Test Compose 2x2")
    print("=" * 50)
    
    # Step 1: Trim each clip to 30s starting from silence end
    trimmed = []
    
    for i, clip in enumerate(CLIPS):
        print(f"\n[{i+1}/4] Processing: {Path(clip).name}")
        
        start, end = get_silence_trim(clip)
        print(f"   Silence ends at: {start:.1f}s")
        
        # Use 30s starting from after silence
        trim_start = start
        trim_end = start + DURATION
        
        output = f"D:/Powerfull/GuitarMultiCamStudio/trim_{i+1}.mp4"
        trimmed.append(output)
        
        cmd = [
            'ffmpeg', '-y', '-ss', str(trim_start), '-i', clip,
            '-t', str(DURATION),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            output
        ]
        
        print(f"   Trimming {trim_start:.1f}s -> {trim_end:.1f}s")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"   [FAIL] Error: {result.stderr[-200:]}")
        else:
            print(f"   [OK] Saved to {output}")
    
    # Step 2: Compose 2x2
    print("\n[5/4] Composing 2x2 grid...")
    
    # Build xstack filter for 2x2
    # TL | TR
    # BL | BR
    positions = "0_0|960_0|0_540|960_540"
    
    cmd = ['ffmpeg', '-y']
    for t in trimmed:
        cmd.extend(['-i', t])
    
    cmd.extend([
        '-filter_complex', f'[0:v][1:v][2:v][3:v]xstack=inputs=4:layout={positions}[v]',
        '-map', '[v]',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
        '-pix_fmt', 'yuv420p',
        OUTPUT
    ])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"\n[OK] Test video saved: {OUTPUT}")
        print(f"   Resolution: 1920x1080 (2x2 grid)")
        print(f"   Duration: {DURATION}s")
    else:
        print(f"\n[FAIL] Compose failed: {result.stderr[-500:]}")

if __name__ == '__main__':
    trim_and_compose()