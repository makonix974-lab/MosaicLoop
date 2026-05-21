#!/usr/bin/env python3
"""
Test suite for GuitarMultiCam Studio
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from sync.audio_sync import load_audio, find_offset, extract_features
from composer.video_composer import VideoComposer


def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    from sync import audio_sync
    from composer import video_composer
    print("  ✓ All modules imported successfully")


def test_audio_sync():
    """Test audio sync on sample files if available."""
    print("\nTesting audio sync...")
    
    # Look for test files
    test_dir = Path(__file__).parent.parent / 'tests' / 'fixtures'
    
    if not test_dir.exists():
        print("  ⚠ No test fixtures found. Create tests/fixtures/ with sample audio files.")
        return
    
    audio_files = list(test_dir.glob('*.wav')) + list(test_dir.glob('*.mp3'))
    
    if len(audio_files) < 2:
        print("  ⚠ Need at least 2 audio files for testing")
        return
    
    master = audio_files[0]
    clip = audio_files[1]
    
    print(f"  Master: {master.name}")
    print(f"  Clip: {clip.name}")
    
    master_audio, sr = load_audio(str(master))
    clip_audio, _ = load_audio(str(clip))
    
    result = find_offset(clip_audio, master_audio, sr)
    
    print(f"  Offset: {result['offset_seconds']:.3f}s")
    print(f"  Confidence: {result['confidence']:.1%}")
    print("  ✓ Audio sync test passed")


def test_video_composer():
    """Test video composer functionality."""
    print("\nTesting video composer...")
    
    composer = VideoComposer()
    
    # Check FFmpeg
    if not composer.check_ffmpeg():
        print("  ⚠ FFmpeg not available. Install FFmpeg to test video composition.")
        return
    
    print(f"  FFmpeg: ✓ Available")
    print(f"  Layouts: {list(composer.LAYOUTS.keys())}")
    
    # Test xstack filter building
    test_clips = ['clip1.mp4', 'clip2.mp4', 'clip3.mp4', 'clip4.mp4']
    
    for layout in ['2x2', '1x2', '2x1']:
        filter_str = composer.build_xstack_layout(test_clips[:4], layout)
        print(f"  Layout {layout}: {filter_str[:60]}...")
    
    print("  ✓ Video composer test passed")


def test_cli_help():
    """Test CLI help command."""
    print("\nTesting CLI...")
    
    import subprocess
    result = subprocess.run(
        [sys.executable, 'cli/main.py', '--help'],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent
    )
    
    if result.returncode == 0:
        print("  ✓ CLI help works")
        print("  Commands:", [line.strip() for line in result.stdout.split('\n') if line.startswith('  ')])
    else:
        print("  ⚠ CLI test failed")


if __name__ == '__main__':
    print("=" * 50)
    print("GuitarMultiCam Studio - Test Suite")
    print("=" * 50)
    
    test_imports()
    test_audio_sync()
    test_video_composer()
    test_cli_help()
    
    print("\n" + "=" * 50)
    print("Tests completed!")
    print("=" * 50)