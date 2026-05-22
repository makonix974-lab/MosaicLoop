#!/usr/bin/env python3
"""
Proxy Manager — downscale/upscale videos for faster editing workflow.
"""

import subprocess
from pathlib import Path
import os
import json
import tempfile
import time
from dataclasses import dataclass, asdict
from .process_guard import ProcessGuard
from .gpu_accel import GPU_INFO, add_hwaccel
from utils.ffmpeg_run import run_ffmpeg


@dataclass
class ProxyConfig:
    """Proxy generation configuration."""
    proxy_width: int = 960  # 960x540 = 540p
    proxy_height: int = 540
    proxy_codec: str = "libx264"
    proxy_preset: str = "veryfast"  # ultrafast for proxy
    proxy_crf: int = 28  # Higher = smaller, faster
    output_dir: str = None  # None = auto (source_dir/_proxy/)


class ProxyManager:
    """
    Manage proxy generation for video files.
    Downscale for fast editing, then upscale for final render.
    """
    
    def __init__(self, config: ProxyConfig = None):
        self.config = config or ProxyConfig()
        self.ffmpeg = 'ffmpeg'
        self.ffprobe = 'ffprobe'
    
    def generate_proxy(self, video_path: str, output_path: str = None) -> str:
        """
        Generate a downscaled proxy of a video.
        
        Args:
            video_path: Source video path
            output_path: Optional proxy output path (auto if None)
        
        Returns:
            Path to proxy file
        """
        video_path = Path(video_path)
        
        if output_path is None:
            output_path = self._auto_proxy_path(video_path)
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Skip if proxy already exists and is valid
        if output_path.exists():
            src_mtime = os.path.getmtime(video_path)
            dst_mtime = os.path.getmtime(output_path)
            # Ensure file is not corrupt (minimum valid mp4 size ~10KB)
            if dst_mtime > src_mtime and output_path.stat().st_size > 10000:
                return str(output_path)
            else:
                # Remove corrupted/incomplete proxy
                try:
                    output_path.unlink()
                except OSError:
                    pass
        
        print(f"   Downscaling: {video_path.name} -> {output_path.name}")
        
        cmd = [
            self.ffmpeg, '-y',
        ]
        
        # GPU acceleration si dispo
        if GPU_INFO['available']:
            cmd += ['-hwaccel', 'cuda']
        
        cmd += [
            '-i', str(video_path),
            '-vf', f'scale={self.config.proxy_width}:{self.config.proxy_height}:'
                   f'force_original_aspect_ratio=decrease,'
                   f'pad={self.config.proxy_width}:{self.config.proxy_height}:'
                   f'(ow-iw)/2:(oh-ih)/2:black',
            '-c:v', GPU_INFO['encoder'] if GPU_INFO['available'] else self.config.proxy_codec,
            '-preset', GPU_INFO['encoder_preset'] if GPU_INFO['available'] else self.config.proxy_preset,
        ]
        
        # Qualité
        af = '-cq' if GPU_INFO['available'] else '-crf'
        cmd += [af, str(self.config.proxy_crf)]
        
        cmd += ['-c:a', 'aac', '-b:a', '64k', str(output_path)]

        info = self.get_info(str(video_path))
        duration = info['duration']

        result = run_ffmpeg(cmd, total_duration=duration, show_progress=True, timeout=600)

        if not result.success:
            raise RuntimeError(f"Proxy generation failed: {result.short_error}")

        return str(output_path)
    
    def batch_generate(self, video_paths: list, show_progress: bool = True,
                       max_workers: int = 4) -> list:
        """
        Generate proxies in PARALLEL using a thread pool.
        
        Args:
            video_paths: List of source video paths
            show_progress: If True, show progress per clip
            max_workers: Max parallel encodes (default: 4)
        
        Returns:
            List of (source_path, proxy_path) tuples
        """
        import concurrent.futures
        
        # Clean une fois avant le parallélisme (pas entre chaque proxy)
        ProcessGuard.cleanup_stale()
        
        results = [None] * len(video_paths)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for i, video_path in enumerate(video_paths):
                future = pool.submit(
                    self.generate_proxy, video_path, None
                )
                futures[future] = i
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    proxy_path = future.result()
                    results[idx] = (video_paths[idx], proxy_path)
                    if show_progress:
                        name = Path(video_paths[idx]).name
                        print(f"   [OK] [{idx+1}/{len(video_paths)}] {name}")
                except Exception as e:
                    if show_progress:
                        print(f"   [FAIL] [{idx+1}/{len(video_paths)}] {Path(video_paths[idx]).name}: {e}")
        
        # Filter out None results (failed)
        results = [r for r in results if r is not None]
        return results
    
    def _auto_proxy_path(self, video_path: Path) -> Path:
        """Auto-generate proxy path inside _proxy/ folder."""
        parent = video_path.parent
        proxy_dir = parent / '_proxy'
        return proxy_dir / f"{video_path.stem}_proxy.mp4"

    def get_info(self, video_path: str) -> dict:
        """Get video info using ffprobe."""
        cmd = [
            self.ffprobe, '-v', 'error',
            '-show_entries', 'stream=width,height,codec_name,r_frame_rate',
            '-show_entries', 'format=duration,size',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)

        streams = data.get('streams', [{}])
        video_stream = next((s for s in streams if s.get('codec_type') == 'video'), {})
        format_info = data.get('format', {})

        fps = video_stream.get('r_frame_rate', '0/1')
        if '/' in fps:
            num, den = fps.split('/')
            fps = float(num) / float(den) if float(den) > 0 else 0

        return {
            'duration': float(format_info.get('duration', 0)),
            'size': int(format_info.get('size', 0)),
            'width': int(video_stream.get('width', 0)),
            'height': int(video_stream.get('height', 0)),
            'fps': fps,
            'codec': video_stream.get('codec_name', 'unknown')
        }