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
        synced = self._step_apply_offsets(cfg, proxies, alignment)
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

    def _validate_video_file(self, path: str) -> bool:
        """Validate video file with ffprobe. Returns True if valid."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", 
                 "format=duration", "-of", "json", path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return False
            data = json.loads(result.stdout)
            return "format" in data and "duration" in data["format"]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return False

    def _cleanup_corrupted_files(self, directory: Path):
        """Remove corrupted video files (moov atom not found)."""
        if not directory.exists():
            return
        for f in directory.glob("*.mp4"):
            if not self._validate_video_file(str(f)):
                print(f"   Removing corrupted: {f.name}")
                f.unlink(missing_ok=True)

    def _step_apply_offsets(self, cfg: PipelineConfig,
                            proxies: list[tuple[str, str]],
                            alignment: AlignmentResult) -> list[str]:
        print("\n[3/4] Apply sync offsets")
        t0 = time.time()
        min_offset = min(alignment.offsets.values())
        synced = []
        output_dir = Path(cfg.output_path).parent / "_synced"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Cleanup corrupted files from previous runs
        self._cleanup_corrupted_files(output_dir)

        for src_path, proxy_path in proxies:
            name = Path(src_path).name
            offset = alignment.offsets.get(name, 0.0)
            pad = offset - min_offset
            out_path = output_dir / f"synced_{name}"
            synced.append(str(out_path))

            try:
                if abs(pad) < 0.05:
                    # No adjustment needed
                    cmd = ["ffmpeg", "-y", "-i", proxy_path,
                           "-c", "copy", str(out_path)]
                    subprocess.run(cmd, capture_output=True, text=True, 
                                 timeout=300, check=True)
                    
                elif pad > 0:
                    # Need padding: use concat demuxer (simpler than filter_complex)
                    # Create temporary black video
                    black_path = output_dir / f"_black_{pad:.3f}s.mp4"
                    cmd_black = [
                        "ffmpeg", "-y", "-f", "lavfi", "-t", f"{pad:.3f}",
                        "-i", f"color=c=black:s={cfg.proxy_width}x{cfg.proxy_height}:r={cfg.output_fps}",
                        "-f", "lavfi", "-t", f"{pad:.3f}",
                        "-i", "anullsrc=r=48000:cl=mono",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        "-c:a", "aac", "-shortest", str(black_path)
                    ]
                    subprocess.run(cmd_black, capture_output=True, text=True,
                                 timeout=60, check=True)
                    
                    # Concat with demuxer
                    concat_list = output_dir / f"_concat_{name}.txt"
                    with open(concat_list, 'w') as f:
                        f.write(f"file '{black_path.absolute()}'\n")
                        f.write(f"file '{Path(proxy_path).absolute()}'\n")
                    
                    cmd_concat = [
                        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_list),
                        "-c", "copy", str(out_path)
                    ]
                    subprocess.run(cmd_concat, capture_output=True, text=True,
                                 timeout=300, check=True)
                    
                    # Cleanup temp files
                    black_path.unlink(missing_ok=True)
                    concat_list.unlink(missing_ok=True)
                    
                else:
                    # Need trimming
                    trim = -pad
                    cmd = ["ffmpeg", "-y", "-ss", f"{trim:.3f}",
                           "-i", proxy_path, "-c", "copy", str(out_path)]
                    subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=300, check=True)
                
                # Validate output
                if not self._validate_video_file(str(out_path)):
                    raise RuntimeError(f"Output validation failed: {out_path.name}")
                    
            except subprocess.TimeoutExpired:
                print(f"   [TIMEOUT] {name} (>300s)")
                out_path.unlink(missing_ok=True)
                raise RuntimeError(f"FFmpeg timeout on {name}")
            except subprocess.CalledProcessError as e:
                print(f"   [ERROR] {name}: {e}")
                out_path.unlink(missing_ok=True)
                raise RuntimeError(f"FFmpeg failed on {name}")

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

    def _apply_preset(self, cfg: PipelineConfig):
        if cfg.preset and cfg.preset in PRESETS:
            for k, v in PRESETS[cfg.preset].items():
                setattr(cfg, k, v)
            print(f"   Preset: {cfg.preset} ({cfg.output_width}x{cfg.output_height})")
