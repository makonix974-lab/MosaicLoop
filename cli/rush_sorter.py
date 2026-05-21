#!/usr/bin/env python3
"""
Rush Sorter — Classify and group video rushes by audio waveform analysis.
"""

import subprocess
import json
import numpy as np
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def get_video_duration(filepath: str) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'json',
        filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data['format']['duration'])


def extract_audio_waveform(video_path: str, sample_rate: int = 8000) -> dict:
    """
    Extract audio waveform features from video file.
    Uses ffmpeg to extract audio, then analyzes the waveform.
    """
    import tempfile
    import os
    
    # Create temp WAV file
    temp_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    temp_wav.close()
    
    try:
        # Extract audio to WAV
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-ac', '1',  # Mono
            '-ar', str(sample_rate),
            '-acodec', 'pcm_s16le',
            temp_wav.name
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        
        # Read WAV file
        import wave
        with wave.open(temp_wav.name, 'rb') as w:
            frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Remove silence at start/end
        threshold = 0.01
        start = 0
        end = len(audio)
        
        for i in range(len(audio)):
            if abs(audio[i]) > threshold:
                start = i
                break
        
        for i in range(len(audio) - 1, -1, -1):
            if abs(audio[i]) > threshold:
                end = i
                break
        
        audio = audio[start:end]
        
        if len(audio) == 0:
            return {'duration': 0, 'energy': 0, 'peak': 0, 'rms': 0}
        
        # Compute features
        duration = len(audio) / sample_rate
        energy = np.sum(audio ** 2) / len(audio)
        peak = np.max(np.abs(audio))
        rms = np.sqrt(energy)
        
        # Compute energy envelope (divide into 1-second chunks)
        chunk_size = sample_rate
        n_chunks = len(audio) // chunk_size
        envelope = []
        for i in range(n_chunks):
            chunk = audio[i * chunk_size:(i + 1) * chunk_size]
            envelope.append(np.sum(chunk ** 2) / len(chunk))
        
        return {
            'duration': duration,
            'energy': float(energy),
            'peak': float(peak),
            'rms': float(rms),
            'envelope': envelope,
            'start_silence': start / sample_rate,
            'end_silence': (len(audio) - end) / sample_rate
        }
        
    finally:
        try:
            os.unlink(temp_wav.name)
        except:
            pass


def analyze_folder(folder: str) -> list:
    """Analyze all video files in folder."""
    folder_path = Path(folder)
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v']
    
    videos = []
    for ext in video_extensions:
        videos.extend(folder_path.glob(f'*{ext}'))
        videos.extend(folder_path.glob(f'*{ext.upper()}'))
    
    print(f"Found {len(videos)} video files")
    
    results = []
    for video in sorted(videos):
        print(f"Analyzing: {video.name}...", end=' ')
        try:
            features = extract_audio_waveform(str(video))
            duration = get_video_duration(str(video))
            
            # Normalize to standard float
            results.append({
                'path': str(video),
                'name': video.name,
                'duration': float(duration),
                'energy': float(features['energy']),
                'peak': float(features['peak']),
                'rms': float(features['rms']),
                'envelope': [float(x) for x in envelope]
            })
            print(f"{duration:.1f}s, energy={features['energy']:.4f}")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                'path': str(video),
                'name': video.name,
                'error': str(e)
            })
    
    return results


def group_by_similarity(results: list, energy_threshold: float = 0.5) -> list:
    """
    Group videos by audio similarity.
    Videos with similar duration and energy envelope are grouped together.
    """
    groups = defaultdict(list)
    
    for r in results:
        if 'error' in r:
            continue
        
        # Use duration and energy as primary grouping keys
        duration_bucket = round(r['duration'] / 10) * 10  # Round to 10s buckets
        energy_bucket = round(r['energy'] / energy_threshold) * energy_threshold
        
        key = (duration_bucket, round(energy_bucket, 3))
        groups[key].append(r)
    
    # Convert to sorted list
    sorted_groups = []
    for key, clips in sorted(groups.items(), key=lambda x: -len(x[1])):
        sorted_groups.append({
            'group_id': len(sorted_groups) + 1,
            'duration_approx': key[0],
            'energy_approx': key[1],
            'count': len(clips),
            'clips': clips
        })
    
    return sorted_groups


def print_groups(groups: list):
    """Pretty print groups."""
    print("\n" + "=" * 60)
    print("RUSH GROUPS — Click on a clip path to select it for your project")
    print("=" * 60)
    
    for group in groups:
        print(f"\n📁 Group {group['group_id']} — ~{group['count']} clips, ~{group['duration_approx']}s, energy={group['energy_approx']:.4f}")
        print("-" * 40)
        for clip in group['clips']:
            print(f"  • {clip['name']}")
            print(f"    Path: {clip['path']}")
            print(f"    Duration: {clip['duration']:.1f}s, Energy: {clip['energy']:.4f}")
    
    return groups


def save_results(results: list, output_path: str):
    """Save analysis results to JSON."""
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Results saved to {output_path}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze and group video rushes by audio')
    parser.add_argument('folder', help='Folder containing video rushes')
    parser.add_argument('--output', '-o', help='Output JSON file', default='rush_analysis.json')
    parser.add_argument('--energy-threshold', '-e', type=float, default=0.5, 
                       help='Energy similarity threshold (lower = stricter)')
    
    args = parser.parse_args()
    
    print("🎬 Rush Sorter — Audio Waveform Analysis")
    print("=" * 50)
    
    # Analyze folder
    results = analyze_folder(args.folder)
    
    # Group by similarity
    groups = group_by_similarity(results, args.energy_threshold)
    
    # Print results
    print_groups(groups)
    
    # Save
    save_results(results, args.output)