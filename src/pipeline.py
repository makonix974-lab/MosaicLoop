"""
Pipeline — Orchestre le workflow complet GuitarMultiCam.

Proxy -> Sync -> Apply Offsets -> Compose (Grid)
"""

import json
import subprocess
import tempfile
from pathlib import Path
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from sync.audio_sync import SyncManager, AlignmentResult
from composer.video_composer import VideoComposer, CompositionConfig
from composer.proxy import ProxyManager, ProxyConfig
from composer.process_guard import ProcessGuard
from models import Clip


@dataclass
class PipelineConfig:
    clips: list[str] = field(default_factory=list)
    output_path: str = "output/final.mp4"
    layout: str = "2x2"  # 2x2, 1x1, 2x1, 1x2
    use_proxy: bool = True
    proxy_width: int = 960
    proxy_height: int = 540
    output_width: int = 1920
    output_height: int = 1080
    output_fps: int = 30
    output_crf: int = 23
    audio_source: int = 0
    preset: str = ""  # youtube, instagram, tiktok
    max_workers: int = 4
    config_path: str = ""


PRESETS = {
    "youtube": dict(
        output_width=1920, output_height=1080, output_fps=30, layout="2x2"
    ),
    "instagram": dict(
        output_width=1080, output_height=1080, output_fps=30, layout="2x2"
    ),
    "tiktok": dict(
        output_width=1080, output_height=1920, output_fps=30, layout="1x2"
    ),
}


def load_config(path: str) -> dict:
    """Load config from YAML or JSON file."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        import yaml
        with open(p) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


class Pipeline:
    def __init__(self, config: PipelineConfig = None):
        self.config = config or PipelineConfig()
        if self.config.config_path:
            self._merge_config(load_config(self.config.config_path))

    def _merge_config(self, overrides: dict):
        for k, v in overrides.items():
            if hasattr(self.config, k) and v is not None:
                setattr(self.config, k, v)

    def run(self) -> dict:
        cfg = self.config
        n = len(cfg.clips)
        if n == 0:
            return {"success": False, "error": "No clips provided"}

        start = time.time()
        Path(cfg.output_path).parent.mkdir(parents=True, exist_ok=True)

        ProcessGuard.cleanup_stale()
        subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"],
                       capture_output=True)

        print(f"\n== GuitarMultiCam Pipeline == {n} clips -> grid")
        print("=" * 50)

        proxies = self._step_proxy(cfg)
        alignment = self._step_sync(cfg, proxies)
        result = self._step_compose_synced(cfg, proxies, alignment)

        elapsed = time.time() - start
        result["elapsed"] = round(elapsed, 1)
        if result.get("success"):
            print(f"\n[OK] Done in {elapsed:.1f}s -> {cfg.output_path}")
        else:
            print(f"\n[FAIL] {result.get('error', 'Unknown error')}")

        return result

    def analyze(self) -> dict:
        """Analyze clips without composing (for preview)."""
        from analyzer.video_analyzer import VideoAnalyzer
        analyzer = VideoAnalyzer()
        clips = analyzer.batch_analyze(self.config.clips)
        return {"success": True, "clips": [c.to_dict() for c in clips]}

    def _step_proxy(self, cfg: PipelineConfig) -> list[tuple[str, str]]:
        print("\n[1/3] Proxy generation")
        if not cfg.use_proxy:
            print("   Skipped (use_proxy=False)")
            return [(p, p) for p in cfg.clips]

        proxy_cfg = ProxyConfig(
            proxy_width=cfg.proxy_width,
            proxy_height=cfg.proxy_height,
            proxy_crf=30,
        )
        mgr = ProxyManager(proxy_cfg)
        t0 = time.time()
        proxies = mgr.batch_generate(cfg.clips, max_workers=cfg.max_workers)
        print(f"   {time.time() - t0:.1f}s")
        return proxies

    def _step_sync(self, cfg: PipelineConfig,
                   proxies: list[tuple[str, str]]) -> AlignmentResult:
        print("\n[2/3] Audio sync")
        t0 = time.time()
        sync = SyncManager()
        alignment = sync.align_clips(cfg.clips)
        print(f"   Confidence: {alignment.confidence:.0%}")
        print(f"   Reference: {alignment.reference_id}")
        print(f"   {time.time() - t0:.1f}s")
        return alignment

    def _step_compose_synced(self, cfg: PipelineConfig,
                             proxies: list[tuple[str, str]],
                             alignment: AlignmentResult) -> dict:
        """
        Single-pass compose: applies sync pads inside the filter_complex.
        No intermediate _synced/ files; one FFmpeg invocation.
        """
        print("\n[3/3] Grid composition (with sync pads)")

        self._apply_preset(cfg)

        cols, rows = (int(x) for x in cfg.layout.split("x"))
        cell_w = cfg.output_width // cols
        cell_h = cfg.output_height // rows

        config = CompositionConfig(
            output_path=cfg.output_path,
            output_width=cfg.output_width,
            output_height=cfg.output_height,
            output_fps=cfg.output_fps,
            output_crf=cfg.output_crf,
            grid_cols=cols,
            grid_rows=rows,
            grid_cell_width=cell_w,
            grid_cell_height=cell_h,
        )

        # Compute per-clip pad in seconds (relative to earliest start)
        min_offset = min(alignment.offsets.values())

        # Build unified Clip objects pointing at the proxy renderable
        clip_refs: list[Clip] = []
        pads: list[float] = []
        for src_path, proxy_path in proxies:
            clip = Clip(path=src_path, proxy_path=proxy_path)
            offset = alignment.offsets.get(Path(src_path).name, 0.0)
            pad = offset - min_offset
            clip_refs.append(clip)
            pads.append(max(0.0, pad))

        # The composer reads `c.path` as the FFmpeg input. Point it at the
        # proxy through render_path semantics: temporarily swap path on the
        # clips so existing composer code stays untouched.
        for c in clip_refs:
            c.path = c.render_path

        t0 = time.time()
        composer = VideoComposer(config)
        result = composer.compose_grid(
            clip_refs,
            show_progress=True,
            audio_source=cfg.audio_source,
            pad_seconds=pads,
        )
        result["elapsed"] = round(time.time() - t0, 1)
        return result

    def _apply_preset(self, cfg: PipelineConfig):
        if cfg.preset and cfg.preset in PRESETS:
            for k, v in PRESETS[cfg.preset].items():
                setattr(cfg, k, v)
            print(f"   Preset: {cfg.preset} ({cfg.output_width}x{cfg.output_height})")
