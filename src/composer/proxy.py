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
        
        # Progress via FILE (pas de pipe — thread crash)
        import tempfile
        progress_path = tempfile.NamedTemporaryFile(suffix='.progress', delete=False).name
        cmd.extend(['-progress', progress_path])
        
        # Run sans pipes
        guard = ProcessGuard(f"proxy_{video_path.stem}")
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        guard.track(process.pid, f"proxy_{video_path.stem}")
        
        info = self.get_info(str(video_path))
        duration = info['duration']
        
        last_pct = 0
        while process.poll() is None:
            try:
                with open(progress_path, 'r', errors='replace') as pf:
                    for line in pf.read().split('\n'):
                        if 'out_time_ms=' in line:
                            ms = int(line.split('=')[1].strip())
                            if ms > 0:
                                pct = min(ms / (duration * 1_000_000) * 100, 99.9)
                                if pct - last_pct >= 5:
                                    bars = '#' * int(pct / 5) + '.' * (20 - int(pct / 5))
                                    print(f"\r   [{bars}] {pct:.0f}%", end='', flush=True)
                                    last_pct = pct
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        
        process.wait()
        guard.untrack(process.pid)
        print(f"\r   [####################] 100%")
        
        # Cleanup progress file
        try:
            Path(progress_path).unlink(missing_ok=True)
        except:
            pass
        
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
    
    def restore_from_proxy(self, proxy_path: str, output_path: str, 
                            source_path: str = None, upscale_width: int = 1440,
                            upscale_height: int = 1440) -> str:
        """
        Upscale a proxy back to full resolution.
        
        Args:
            proxy_path: Path to proxy file
            output_path: Output path for upscaled version
            source_path: If provided, use source for reference metadata
            upscale_width/height: Target resolution
        
        Returns:
            Path to upscaled file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use lanczos for quality upscale
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
        
        # Qualité: CRF (CPU) ou CQ (GPU)
        if GPU_INFO['available']:
            cmd += ['-cq', str(self.config.proxy_crf)]
        else:
            cmd += ['-crf', str(self.config.proxy_crf)]
        
        cmd += [
            '-c:a', 'aac', '-b:a', '64k',
            str(output_path)
        ]
        
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, bufsize=1
        )
        
        last_pct = 0
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if 'out_time_ms=' in line:
                try:
                    out_time_ms = int(line.split('=')[1])
                except (ValueError, IndexError):
                    continue
                if out_time_ms > 0:
                    info = self.get_info(str(proxy_path))
                    duration = info['duration']
                    pct = min(out_time_ms / (duration * 1_000_000) * 100, 99.9)
                    if pct - last_pct >= 5:
                        bars = '#' * int(pct / 5) + '.' * (20 - int(pct / 5))
                        print(f"\r   [{bars}] {pct:.0f}%", end='', flush=True)
                        last_pct = pct
        
        process.wait()
        print(f"\r   [####################] 100%")
        
        return str(output_path)
    
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


class EditDecisionList:
    """
    Records edit decisions independently of resolution.
    
    An EDL contains:
    - Source file references
    - Time segments (start/end for each source)
    - Grid layout decisions
    - Transitions
    """
    
    def __init__(self):
        self.sources = {}  # {source_id: source_path}
        self.segments = []  # [{source_id, start, end, type}]
        self.layout = None  # {type: 'linear'|'grid', ...}
        self.metadata = {}
    
    def add_source(self, source_path: str) -> str:
        """Register source and return its ID."""
        source_id = Path(source_path).stem
        self.sources[source_id] = source_path
        return source_id
    
    def add_segment(self, source_id: str, start: float, end: float, 
                    segment_type: str = "music", **kwargs):
        """Add an edit segment."""
        self.segments.append({
            'source_id': source_id,
            'start': start,
            'end': end,
            'type': segment_type,
            **kwargs
        })
    
    def set_layout(self, layout_type: str = "linear", **params):
        """Set output layout."""
        self.layout = {'type': layout_type, **params}
    
    def export(self, output_path: str):
        """Export EDL to JSON."""
        data = {
            'sources': self.sources,
            'segments': self.segments,
            'layout': self.layout,
            'metadata': self.metadata
        }
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, input_path: str) -> 'EditDecisionList':
        """Load EDL from JSON."""
        edl = cls()
        with open(input_path) as f:
            data = json.load(f)
        edl.sources = data.get('sources', {})
        edl.segments = data.get('segments', [])
        edl.layout = data.get('layout')
        edl.metadata = data.get('metadata', {})
        return edl
    
    def get_total_duration(self) -> float:
        """Get total output duration."""
        return sum(s['end'] - s['start'] for s in self.segments)


class ExportEngine:
    """
    Apply EDL to full-resolution sources for final output.
    """
    
    def __init__(self):
        self.ffmpeg = 'ffmpeg'
    
    def export_linear(self, edl: EditDecisionList, output_path: str, 
                       show_progress: bool = True) -> dict:
        """
        Export linear composition from EDL using full-res sources.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build concat demuxer file
        concat_path = output_path.parent / f"_concat_{output_path.stem}.txt"
        
        with open(concat_path, 'w') as f:
            for seg in edl.segments:
                source_path = edl.sources.get(seg['source_id'])
                if source_path:
                    f.write(f"file '{source_path}'\n")
                    f.write(f"inpoint {seg['start']:.3f}\n")
                    f.write(f"outpoint {seg['end']:.3f}\n")
        
        cmd = [
            self.ffmpeg, '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(concat_path),
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '18',
            '-c:a', 'aac', '-b:a', '192k',
            '-progress', 'pipe:1',
            str(output_path)
        ]
        
        if show_progress:
            result = self._run_with_progress(cmd, edl.get_total_duration(),
                                              "Rendering full-res...")
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            returncode = result.returncode
            stderr = result.stderr
        
        concat_path.unlink(missing_ok=True)
        
        return {
            'success': returncode == 0,
            'output_path': str(output_path),
            'error': stderr[:2000] if not returncode == 0 else None
        }
    
    def _run_with_progress(self, cmd, total_duration, label="Processing"):
        """Run FFmpeg with progress bar."""
        import subprocess
        
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, bufsize=1
        )
        
        print(f"   {label}")
        last_pct = 0
        
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if 'out_time_ms=' in line:
                try:
                    out_time_ms = int(line.split('=')[1])
                except (ValueError, IndexError):
                    continue
                if out_time_ms > 0 and total_duration > 0:
                    pct = min(out_time_ms / (total_duration * 1_000_000) * 100, 99.9)
                    if pct - last_pct >= 1:
                        bars = '#' * int(pct / 5) + '.' * (20 - int(pct / 5))
                        print(f"\r   [{bars}] {pct:.0f}%", end='', flush=True)
                        last_pct = pct
        
        stderr = process.stderr.read()
        print(f"\r   [####################] 100%")
        
        return {
            'returncode': process.returncode,
            'stderr': stderr
        }