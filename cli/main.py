"""
GuitarMultiCam CLI — Command-line interface for video sync and composition.

Usage:
  guitarcam auto --clips *.mp4 --output final.mp4
  guitarcam sync --clips *.mp4
  guitarcam compose --clips *.mp4 --output final.mp4 --layout 2x2
  guitarcam analyze --clips *.mp4
  guitarcam config --template
"""

import json
import sys
from pathlib import Path

import click

_ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, _ROOT + "/src")
sys.path.insert(0, _ROOT)

from pipeline import Pipeline, PipelineConfig, load_config
from sync.audio_sync import SyncManager
from composer.video_composer import VideoComposer, CompositionConfig
from composer.process_guard import ProcessGuard
from models import Clip


@click.group()
def cli():
    """GuitarMultiCam Studio — Multi-cam video editing for musicians."""
    ProcessGuard.cleanup_stale()


@cli.command()
@click.option("--clips", "-c", multiple=True, required=True,
              type=click.Path(exists=True), help="Video files to process")
@click.option("--output", "-o", default="output/final.mp4",
              help="Output video path")
@click.option("--layout", "-l", default="2x2",
              type=click.Choice(["1x1", "2x1", "1x2", "2x2"]),
              help="Grid layout")
@click.option("--preset", "-p", default="",
              type=click.Choice(["", "youtube", "instagram", "tiktok"]),
              help="Export preset (overrides --width/--height)")
@click.option("--width", "-w", default=1920, type=int, help="Output width")
@click.option("--height", "-h", default=1080, type=int, help="Output height")
@click.option("--fps", "-f", default=30, type=int, help="Output framerate")
@click.option("--crf", default=23, type=int,
              help="Quality (lower=better, 18-28)")
@click.option("--proxy/--no-proxy", default=True,
              help="Use proxy for faster processing")
@click.option("--audio-source", default=0, type=int,
              help="Index of clip to use as audio source (0=first)")
@click.option("--workers", default=4, type=int,
              help="Max parallel workers for proxy generation")
@click.option("--cache/--no-cache", default=True,
              help="Reuse cached proxies and sync from previous runs")
@click.option("--config", default="", help="Path to YAML/JSON config file")
def auto(clips, output, layout, preset, width, height,
         fps, crf, proxy, audio_source, workers, cache, config):
    """Full pipeline: sync + compose in one command (grid mode)."""
    cfg = PipelineConfig(
        clips=list(clips),
        output_path=output,
        layout=layout,
        use_proxy=proxy,
        output_width=width,
        output_height=height,
        output_fps=fps,
        output_crf=crf,
        audio_source=audio_source,
        preset=preset,
        max_workers=workers,
        use_cache=cache,
        config_path=config,
    )
    pipeline = Pipeline(cfg)
    result = pipeline.run()

    if not result.get("success"):
        click.echo(f"\n[FAIL] {result.get('error', 'Unknown error')}", err=True)
        raise SystemExit(1)


@cli.command()
@click.option("--clips", "-c", multiple=True, required=True,
              type=click.Path(exists=True), help="Video files to sync")
@click.option("--output", "-o", default="output/offsets.json",
              help="Output alignment JSON")
def sync(clips, output):
    """Analyze audio and find optimal sync offsets for clips."""
    sync_mgr = SyncManager()
    alignment = sync_mgr.align_clips(list(clips))

    click.echo(f"\nReference: {alignment.reference_id}")
    click.echo(f"Confidence: {alignment.confidence:.1%}")
    for name, offset in alignment.offsets.items():
        click.echo(f"  {name}: {offset:+.3f}s")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump({
            "offsets": alignment.offsets,
            "confidence": alignment.confidence,
            "reference": alignment.reference_id,
        }, f, indent=2)
    click.echo(f"\n[OK] Offsets saved to {output}")


@cli.command()
@click.option("--clips", "-c", multiple=True, required=True,
              type=click.Path(exists=True), help="Video files to compose")
@click.option("--output", "-o", default="output/composition.mp4",
              help="Output video path")
@click.option("--layout", "-l", default="2x2",
              type=click.Choice(["1x1", "2x1", "1x2", "2x2"]),
              help="Grid layout")
@click.option("--audio-source", default=0, type=int,
              help="Index of clip to use as audio source (0=first)")
@click.option("--crf", default=23, type=int,
              help="Quality (lower=better, 18-28)")
def compose(clips, output, layout, audio_source, crf):
    """Compose clips into a grid layout (must be pre-synced)."""
    cols, rows = (int(x) for x in layout.split("x"))
    cell_w = 1920 // cols
    cell_h = 1080 // rows

    config = CompositionConfig(
        output_path=output,
        grid_cols=cols,
        grid_rows=rows,
        grid_cell_width=cell_w,
        grid_cell_height=cell_h,
        output_crf=crf,
    )

    Path(output).parent.mkdir(parents=True, exist_ok=True)

    composer = VideoComposer(config)
    grid_clips = [Clip.from_path(c, probe=True) for c in clips]
    result = composer.compose_grid(grid_clips, show_progress=True,
                                   audio_source=audio_source)

    if result.get("success"):
        click.echo(f"\n[OK] Video saved to {output}")
    else:
        click.echo(f"\n[FAIL] {result.get('error', 'Unknown error')}", err=True)
        raise SystemExit(1)


@cli.command()
@click.option("--clips", "-c", multiple=True, required=True,
              type=click.Path(exists=True), help="Video files to analyze")
@click.option("--output", "-o", default="output/analysis.json",
              help="Output analysis JSON")
def analyze(clips, output):
    """Analyze video clips for audio and scene features."""
    cfg = PipelineConfig(clips=list(clips))
    pipeline = Pipeline(cfg)
    result = pipeline.analyze()

    if result.get("success"):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            json.dump(result["clips"], f, indent=2)
        click.echo(f"\n[OK] Analysis saved to {output}")
    else:
        click.echo(f"\n[FAIL] Analysis failed", err=True)


@cli.command()
@click.option("--template", is_flag=True, help="Print config template")
def config(template):
    """Manage configuration."""
    if template:
        tmpl = """# GuitarMultiCam Studio Configuration
# Save as guitarcam.yaml and use: guitarcam auto --config guitarcam.yaml

output_path: output/final.mp4
layout: 2x2
use_proxy: true
output_width: 1920
output_height: 1080
output_fps: 30
output_crf: 23
audio_source: 0
preset: ""  # youtube, instagram, tiktok
max_workers: 4
clips:
  - path/to/clip1.mp4
  - path/to/clip2.mp4
  - path/to/clip3.mp4
  - path/to/clip4.mp4
"""
        click.echo(tmpl)
    else:
        click.echo("Use --template to print a config file template.")


@cli.command()
def clean():
    """Kill lingering ffmpeg processes (cleanup)."""
    ProcessGuard.cleanup_stale()
    click.echo("[OK] Done")


if __name__ == '__main__':
    cli()
