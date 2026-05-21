"""
Pipeline — Orchestre le workflow complet GuitarMultiCam.

Proxy -> Sync -> Apply Offsets -> Compose (Grid/Smart)
"""

import json
import subprocess
import tempfile
from pathlib import Path
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from tqdm import tqdm

from sync.audio_sync import SyncManager, AlignmentResult
from composer.video_composer import VideoComposer, CompositionConfig
from composer.smart_composer import SmartComposer
from composer.proxy import ProxyManager, ProxyConfig
from composer.process_guard import ProcessGuard


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
    smart: bool = False
    style: str = "auto"  # auto, dynamic, stable
    trim_silence: bool = True
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

        mode = "smart" if cfg.smart else "grid"
        print(f"\n== GuitarMultiCam Pipeline == {n} clips -> {mode}")
        print("=" * 50)

        proxies = self._step_proxy(cfg)
        alignment = self._step_sync(cfg, proxies)
        synced = self._step_apply_offsets(cfg, proxies, alignment)

        if cfg.smart:
            result = self._step_smart_compose(cfg, synced)
        else:
            result = self._step_compose(cfg, synced, alignment)

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
        print("\n[1/4] Proxy generation")
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
        print("\n[2/4] Audio sync")
        t0 = time.time()
        sync = SyncManager()
        alignment = sync.align_clips(cfg.clips)
        print(f"   Confidence: {alignment.confidence:.0%}")
        print(f"   Reference: {alignment.reference_id}")
        print(f"   {time.time() - t0:.1f}s")
        return alignment

    def _step_apply_offsets(self, cfg: PipelineConfig,
                            proxies: list[tuple[str, str]],
                            alignment: AlignmentResult) -> list[str]:
        print("\n[3/4] Apply sync offsets")
        t0 = time.time()
        min_offset = min(alignment.offsets.values())
        synced = []
        output_dir = Path(cfg.output_path).parent / "_synced"
        output_dir.mkdir(parents=True, exist_ok=True)

        for src_path, proxy_path in proxies:
            name = Path(src_path).name
            offset = alignment.offsets.get(name, 0.0)
            pad = offset - min_offset
            out_path = output_dir / f"synced_{name}"
            synced.append(str(out_path))

            if abs(pad) < 0.05:
                cmd = ["ffmpeg", "-y", "-i", proxy_path,
                       "-c", "copy", str(out_path)]
            elif pad > 0:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-t", f"{pad:.3f}",
                    "-i", f"color=c=black:s={cfg.proxy_width}x{cfg.proxy_height}:r={cfg.output_fps}",
                    "-f", "lavfi", "-t", f"{pad:.3f}",
                    "-i", "anullsrc=r=48000:cl=mono",
                    "-i", proxy_path,
                    "-filter_complex",
                    "[0:v][1:a][2:v][2:a]concat=n=2:v=1:a=1[vo][ao]",
                    "-map", "[vo]", "-map", "[ao]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-c:a", "aac", str(out_path),
                ]
            else:
                trim = -pad
                cmd = ["ffmpeg", "-y", "-ss", f"{trim:.3f}",
                       "-i", proxy_path, "-c", "copy", str(out_path)]

            subprocess.run(cmd, capture_output=True, text=True)

        print(f"   {time.time() - t0:.1f}s")
        return synced

    def _step_compose(self, cfg: PipelineConfig,
                      synced: list[str],
                      alignment: AlignmentResult) -> dict:
        print("\n[4/4] Grid composition")

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

        t0 = time.time()
        composer = VideoComposer(config)

        class ClipWrap:
            def __init__(self, path: str):
                self.path = path
                self.name = Path(path).name
                self.audio = type("a", (), {"duration": 0})()

        grid_clips = [ClipWrap(p) for p in synced]
        result = composer.compose_grid(
            grid_clips, show_progress=True, audio_source=cfg.audio_source
        )

        result["elapsed"] = round(time.time() - t0, 1)
        return result

    def _step_smart_compose(self, cfg: PipelineConfig,
                            synced: list[str]) -> dict:
        print("\n[4/4] Smart composition (AI-driven)")

        self._apply_preset(cfg)

        config = CompositionConfig(
            output_path=cfg.output_path,
            output_width=cfg.output_width,
            output_height=cfg.output_height,
            output_fps=cfg.output_fps,
            output_crf=cfg.output_crf,
        )

        t0 = time.time()
        composer = SmartComposer(config)
        result = composer.compose_smart(
            synced,
            style=cfg.style,
            trim_silence=cfg.trim_silence,
        )

        result["elapsed"] = round(time.time() - t0, 1)
        if result.get("success"):
            switches = result.get("camera_switches", 0)
            print(f"   Camera switches: {switches}")
        return result

    def _apply_preset(self, cfg: PipelineConfig):
        if cfg.preset and cfg.preset in PRESETS:
            for k, v in PRESETS[cfg.preset].items():
                setattr(cfg, k, v)
            print(f"   Preset: {cfg.preset} ({cfg.output_width}x{cfg.output_height})")
