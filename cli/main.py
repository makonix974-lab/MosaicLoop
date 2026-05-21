#!/usr/bin/env python3
"""
GuitarMultiCam CLI
Command-line interface for video sync and compose.
"""

import click
import json
from pathlib import Path
from tqdm import tqdm

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from sync.audio_sync import load_audio, find_offset, align_clips_to_master
from composer.video_composer import VideoComposer


@click.group()
def cli():
    """GuitarMultiCam Studio CLI"""
    pass


@cli.command()
@click.argument('master', type=click.Path(exists=True))
@click.argument('clips', nargs=-1, type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), help='Output JSON file for offsets')
def sync(master, clips, output):
    """Analyze audio and find optimal sync offsets for clips."""
    click.echo(f"Master: {master}")
    click.echo(f"Clips: {len(clips)}")
    
    clips_info = [{'path': str(c)} for c in clips]
    
    click.echo("\nAnalyzing audio alignment...")
    results = []
    
    master_audio, sr = load_audio(master)
    
    for clip_path in tqdm(clips, desc="Processing clips"):
        clip_audio, _ = load_audio(clip_path)
        result = find_offset(clip_audio, master_audio, sr)
        results.append({
            'path': str(clip_path),
            'offset_seconds': result['offset_seconds'],
            'confidence': result['confidence']
        })
        click.echo(f"  {Path(clip_path).name}: {result['offset_seconds']:.3f}s (conf: {result['confidence']:.1%})")
    
    if output:
        with open(output, 'w') as f:
            json.dump(results, f, indent=2)
        click.echo(f"\n✓ Offsets saved to {output}")
    else:
        click.echo(json.dumps(results, indent=2))


@cli.command()
@click.argument('clips', nargs=-1, type=click.Path(exists=True))
@click.option('--layout', '-l', default='2x2', help='Grid layout (1x1, 1x2, 2x1, 2x2, 3x1)')
@click.option('--output', '-o', default='output.mp4', help='Output file')
@click.option('--width', '-w', default=1920, help='Output width')
@click.option('--height', '-h', default=1080, help='Output height')
@click.option('--crf', default=23, help='Quality (lower=better, 18-28)')
def compose(clips, layout, output, width, height, crf):
    """Compose clips into grid layout."""
    composer = VideoComposer()
    
    if not composer.check_ffmpeg():
        click.echo("❌ FFmpeg not found! Install ffmpeg and add to PATH.", err=True)
        return
    
    click.echo(f"Composing {len(clips)} clips into {layout} layout...")
    
    result = composer.compose(
        clips=list(clips),
        output=output,
        layout=layout,
        resolution=(width, height),
        crf=crf
    )
    
    if result.returncode == 0:
        click.echo(f"✓ Video saved to {output}")
    else:
        click.echo(f"❌ Error: {result.stderr}", err=True)


@cli.command()
@click.argument('offsets_file', type=click.Path(exists=True))
@click.argument('master_audio', type=click.Path(exists=True))
@click.option('--layout', '-l', default='2x2', help='Grid layout')
@click.option('--output', '-o', default='final.mp4', help='Output file')
def render(offsets_file, master_audio, layout, output):
    """Render final video using sync offsets and master audio."""
    with open(offsets_file) as f:
        clips_offsets = json.load(f)
    
    composer = VideoComposer()
    
    if not composer.check_ffmpeg():
        click.echo("❌ FFmpeg not found!", err=True)
        return
    
    click.echo(f"Rendering {len(clips_offsets)} clips with offsets...")
    
    result = composer.compose_with_offsets(
        clips_offsets=clips_offsets,
        master_audio=master_audio,
        output=output,
        layout=layout
    )
    
    if result.returncode == 0:
        click.echo(f"✓ Final video: {output}")
    else:
        click.echo(f"❌ Error: {result.stderr}", err=True)


@cli.command()
@click.argument('master', type=click.Path(exists=True))
@click.argument('clips', nargs=-1, type=click.Path(exists=True))
@click.option('--layout', '-l', default='2x2', help='Grid layout')
@click.option('--output', '-o', default='final.mp4', help='Output file')
def auto(master, clips, layout, output):
    """Full pipeline: sync + render in one command."""
    import tempfile
    import os
    
    click.echo("🎸 GuitarMultiCam Auto Pipeline")
    click.echo("=" * 40)
    
    # Step 1: Sync
    click.echo("\n[1/2] Analyzing audio sync...")
    clips_info = [{'path': str(c)} for c in clips]
    
    master_audio, sr = load_audio(master)
    offsets = []
    
    for clip_path in clips:
        clip_audio, _ = load_audio(clip_path)
        result = find_offset(clip_audio, master_audio, sr)
        offsets.append({
            'path': str(clip_path),
            'offset_seconds': result['offset_seconds'],
            'confidence': result['confidence']
        })
    
    # Step 2: Render
    click.echo("\n[2/2] Composing video...")
    composer = VideoComposer()
    
    if not composer.check_ffmpeg():
        click.echo("❌ FFmpeg not found!", err=True)
        return
    
    result = composer.compose_with_offsets(
        clips_offsets=offsets,
        master_audio=master,
        output=output,
        layout=layout
    )
    
    if result.returncode == 0:
        click.echo(f"\n✅ Done! Video saved to {output}")
    else:
        click.echo(f"\n❌ Error: {result.stderr}", err=True)


if __name__ == '__main__':
    cli()