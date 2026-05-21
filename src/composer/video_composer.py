#!/usr/bin/env python3
"""
GuitarMultiCam Video Composer
Intelligent video composition from analyzed clips.

Combines:
- Beat-aligned segments
- Scene changes
- Multi-camera sync
- Smart angle selection
"""

import subprocess
import json
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import shutil
from .process_guard import ProcessGuard
from .gpu_accel import GPU_INFO


@dataclass
class CompositionConfig:
    """Configuration for video composition."""
    # Output
    output_path: str = "output/composition.mp4"
    output_width: int = 1920
    output_height: int = 1080
    output_fps: int = 30
    output_codec: str = "libx264"
    output_preset: str = "medium"
    output_crf: int = 23
    
    # Layout (max 1920x1080 output)
    grid_cols: int = 2
    grid_rows: int = 2
    grid_cell_width: int = 960  # 1920/2
    grid_cell_height: int = 540  # 1080/2
    padding: int = 2
    background_color: str = "black"
    
    # Composition
    transition_duration: float = 0.25  # seconds
    transition_type: str = "cut"  # cut, fade, dissolve
    min_segment_duration: float = 1.0  # minimum segment to include
    
    # Audio
    audio_normalize: bool = True
    audio_gain: float = 1.0


class VideoComposer:
    """
    Compose multi-camera video from analyzed clips.
    """
    
    def __init__(self, config: CompositionConfig = None):
        self.config = config or CompositionConfig()
        # Auto GPU si dispo
        if GPU_INFO['available']:
            self.config.output_codec = GPU_INFO['encoder']
            self.config.output_preset = GPU_INFO['encoder_preset']
        self.ffmpeg = 'ffmpeg'
        self.ffprobe = 'ffprobe'
    
    def compose(self, clips: list, segments: list = None, show_progress: bool = True) -> dict:
        """
        Compose a video from analyzed clips.
        
        Args:
            clips: List of ClipAnalysis objects
            segments: Optional pre-computed segments to use
            show_progress: If True, show progress bar during encoding
        
        Returns:
            Dict with output path and composition stats
        """
        if not clips:
            return {'error': 'No clips provided'}
        
        # Ensure output directory exists
        Path(self.config.output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Get all segments from all clips
        if segments is None:
            segments = self._collect_segments(clips)
        
        # Build composition timeline
        timeline = self._build_timeline(clips, segments)
        
        if not timeline:
            return {'error': 'No segments to compose'}
        
        # Generate composition commands
        composition_plan = self._plan_composition(timeline, clips)
        
        # Execute composition with progress
        output = self._execute_composition(composition_plan, clips, show_progress=show_progress)
        
        return output
    
    def _collect_segments(self, clips: list) -> list:
        """Collect all segments from clips."""
        all_segments = []
        
        for clip in clips:
            if clip.audio and clip.audio.segments:
                for seg in clip.audio.segments:
                    all_segments.append({
                        'clip_path': clip.path,
                        'clip_name': clip.name,
                        'start': seg['start'],
                        'end': seg['end'],
                        'type': seg.get('type', 'music'),
                        'beat_aligned': seg.get('beat_aligned', False),
                        'bars': seg.get('bars', 0)
                    })
        
        return all_segments
    
    def _build_timeline(self, clips: list, segments: list) -> list:
        """
        Build a timeline with segments aligned by musical position.
        Groups segments that happen at the same time across different clips.
        """
        timeline = []
        
        # Sort segments by start time
        sorted_segments = sorted(segments, key=lambda x: x['start'])
        
        # Group segments by time window (within 0.5 seconds)
        current_group = []
        current_time = None
        
        for seg in sorted_segments:
            if current_time is None:
                current_time = seg['start']
            
            # If within time window, add to current group
            if abs(seg['start'] - current_time) < 0.5:
                current_group.append(seg)
            else:
                # Save current group and start new one
                if current_group:
                    timeline.append({
                        'time': current_time,
                        'segments': current_group
                    })
                current_group = [seg]
                current_time = seg['start']
        
        # Add last group
        if current_group:
            timeline.append({
                'time': current_time,
                'segments': current_group
            })
        
        return timeline
    
    def _plan_composition(self, timeline: list, clips: list) -> list:
        """
        Plan which clip to use for each timeline segment.
        Smart selection based on:
        - Quality (resolution, clarity)
        - Angle diversity
        - Segment duration
        """
        plan = []
        
        last_used_clip = None
        
        for entry in timeline:
            time = entry['time']
            segments = entry['segments']
            
            # Calculate duration
            min_start = min(s['start'] for s in segments)
            max_end = max(s['end'] for s in segments)
            duration = max_end - min_start
            
            # Skip if too short
            if duration < self.config.min_segment_duration:
                continue
            
            # Select best segment (for now, just pick the first valid one)
            # TODO: Implement smart selection based on quality metrics
            selected = None
            for seg in segments:
                if seg['end'] - seg['start'] >= self.config.min_segment_duration:
                    selected = seg
                    break
            
            if selected:
                # Prefer different clip than last for variety
                if (last_used_clip and 
                    len(segments) > 1 and 
                    segments[0]['clip_path'] == last_used_clip):
                    # Find a different clip
                    for seg in segments[1:]:
                        if seg['clip_path'] != last_used_clip:
                            selected = seg
                            break
                
                plan.append({
                    'time': time,
                    'duration': duration,
                    'clip_path': selected['clip_path'],
                    'clip_start': selected['start'],
                    'clip_end': selected['end']
                })
                
                last_used_clip = selected['clip_path']
        
        return plan
    
    def _execute_composition(self, plan: list, clips: list, show_progress: bool = True) -> dict:
        """Execute composition plan via FFmpeg concat. Progress via FILE (no pipes)."""
        if not plan:
            return {'error': 'Empty composition plan'}
        
        # Create concat list
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            concat_list_path = f.name
        
        result = {'success': False, 'error': 'Unknown error'}
        
        try:
            with open(concat_list_path, 'w') as f:
                for segment in plan:
                    f.write(f"file '{segment['clip_path']}'\n")
                    f.write(f"inpoint {segment['clip_start']:.3f}\n")
                    f.write(f"outpoint {segment['clip_end']:.3f}\n")
            
            # Build FFmpeg command
            cmd = [self.ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list_path]
            
            if self.config.audio_normalize:
                cmd.extend(['-af', 'loudnorm=I=-16:TP=-1.5:LRA=11'])
            if self.config.audio_gain != 1.0:
                cmd.extend(['-af', f'volume={self.config.audio_gain}'])
            
            cmd.extend(['-c:v', self.config.output_codec, '-preset', self.config.output_preset,
                        '-crf', str(self.config.output_crf), '-r', str(self.config.output_fps),
                        '-c:a', 'aac', '-b:a', '192k'])
            cmd.append(self.config.output_path)
            
            # Progress via FILE (not pipe) — évite les thread crashes
            progress_path = tempfile.NamedTemporaryFile(suffix='.progress', delete=False).name
            cmd.extend(['-progress', progress_path])
            
            if show_progress:
                print("   Encoding video...")
                ProcessGuard.cleanup_stale()
                guard = ProcessGuard("composition")
                process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                guard.track(process.pid, "composition")
                
                total_duration = sum(s['duration'] for s in plan)
                last_pct = 0
                
                while process.poll() is None:
                    try:
                        with open(progress_path, 'r', errors='replace') as pf:
                            for line in pf.read().split('\n'):
                                if 'out_time_ms=' in line:
                                    ms = int(line.split('=')[1].strip())
                                    if ms > 0:
                                        pct = min(ms / (total_duration * 1_000_000) * 100, 100)
                                        if pct - last_pct >= 2 or pct >= 100:
                                            bars = '#' * int(pct/5) + '.' * (20 - int(pct/5))
                                            print(f"\r   [{bars}] {pct:.0f}%", end='', flush=True)
                                            last_pct = pct
                    except (OSError, ValueError):
                        pass
                    import time
                    time.sleep(0.5)
                
                process.wait()
                guard.untrack(process.pid)
                print(f"\r   [####################] 100%")
                returncode = process.returncode
            else:
                result = subprocess.run(cmd, capture_output=True, text=True)
                returncode = result.returncode
            
            # Cleanup progress file
            try:
                Path(progress_path).unlink(missing_ok=True)
            except:
                pass
            
            if returncode == 0:
                total_duration = sum(s['duration'] for s in plan)
                result = {
                    'success': True,
                    'output_path': self.config.output_path,
                    'total_segments': len(plan),
                    'total_duration': total_duration,
                    'segments': plan
                }
            else:
                result = {'success': False, 'error': f'FFmpeg exit code {returncode}'}
        
        finally:
            Path(concat_list_path).unlink(missing_ok=True)
        
        return result
    
    def compose_grid(self, clips: list, output_path: str = None, 
                     show_progress: bool = True, audio_source: int = 0) -> dict:
        """
        Create a 2x2 grid layout with synchronized audio from one source.
        
        Args:
            clips: List of ClipAnalysis or SimpleClip objects
            output_path: Optional output path
            show_progress: Progress bar during encoding
            audio_source: Index of clip to use for audio (default: 0)
        """
        if output_path:
            self.config.output_path = output_path
        
        if len(clips) == 0:
            return {'error': 'No clips'}
        
        max_clips = min(len(clips), self.config.grid_cols * self.config.grid_rows)
        selected_clips = clips[:max_clips]
        
        # Build grid filter for video
        filter_complex = self._build_grid_filter(selected_clips)
        
        # Build FFmpeg command: inputs + filter + map video + map audio + encode
        cmd = [self.ffmpeg, '-y']
        
        for clip in selected_clips:
            cmd.extend(['-i', clip.path])
        
        cmd.extend(['-filter_complex', filter_complex])
        cmd.extend(['-map', '[grid]'])  # Map the grid video output
        cmd.extend(['-map', f'{audio_source}:a'])  # Map audio from chosen source
        
        # Audio: re-encode to AAC
        cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
        
        # Video encoding
        cmd.extend([
            '-c:v', self.config.output_codec,
            '-preset', 'fast',
            '-crf', str(self.config.output_crf)
        ])
        
        # Progress via FILE (pas de pipe)
        import tempfile
        progress_path = tempfile.NamedTemporaryFile(suffix='.progress', delete=False).name
        cmd.extend(['-progress', progress_path])
        cmd.append(self.config.output_path)
        
        if show_progress:
            print("   Rendering 2x2 grid...")
            ProcessGuard.cleanup_stale()
            
            guard = ProcessGuard("grid")
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            guard.track(process.pid, "grid")
            
            total_duration = max(
                (c.audio.duration if hasattr(c, 'audio') and c.audio else 
                 getattr(c, 'duration', 0)) for c in selected_clips
            )
            if not total_duration or total_duration <= 0:
                total_duration = 200
            
            last_pct = 0
            while process.poll() is None:
                try:
                    with open(progress_path, 'r', errors='replace') as pf:
                        for line in pf.read().split('\n'):
                            if 'out_time_ms=' in line:
                                ms = int(line.split('=')[1].strip())
                                if ms > 0:
                                    pct = min(ms / (total_duration * 1_000_000) * 100, 99.9)
                                    if pct - last_pct >= 2:
                                        bars = '#' * int(pct/5) + '.' * (20 - int(pct/5))
                                        print(f"\r   [{bars}] {pct:.0f}%", end='', flush=True)
                                        last_pct = pct
                except (OSError, ValueError):
                    pass
                time.sleep(0.5)
            
            process.wait()
            guard.untrack(process.pid)
            print(f"\r   [####################] 100%")
            returncode = process.returncode
        
        # Cleanup progress file
        try:
            Path(progress_path).unlink(missing_ok=True)
        except:
            pass
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            returncode = result.returncode
        
        if returncode == 0:
            return {
                'success': True,
                'output_path': self.config.output_path,
                'clips_used': max_clips,
                'grid': f'{self.config.grid_cols}x{self.config.grid_rows}'
            }
        else:
            return {'success': False, 'error': 'FFmpeg error (check logs)'}
    
    def _build_grid_filter(self, clips: list) -> str:
        """
        Build FFmpeg hstack/vstack filter for 2x2 grid.
        Output label: [grid]
        Cell size: 960x540 (for 1080p grid output)
        """
        cols = self.config.grid_cols
        rows = self.config.grid_rows
        cell_w = self.config.grid_cell_width
        cell_h = self.config.grid_cell_height
        
        filters = []
        
        # Scale each input to cell size
        for i in range(len(clips)):
            filters.append(
                f"[{i}:v]scale={cell_w}:{cell_h}:force_original_aspect_ratio=increase,"
                f"crop={cell_w}:{cell_h}[v{i}]"
            )
        
        # Build rows with hstack
        for row in range(rows):
            idx_start = row * cols
            idx_end = min(idx_start + cols, len(clips))
            n_in_row = idx_end - idx_start
            
            if n_in_row == 0:
                continue
            
            if n_in_row == 1:
                filters.append(f"[v{idx_start}]copy[row{row}]")
            else:
                inputs = ''.join(f"[v{idx_start + c}]" for c in range(n_in_row))
                filters.append(f"{inputs}hstack=inputs={n_in_row}[row{row}]")
        
        # Stack rows vertically
        row_labels = ''.join(f"[row{r}]" for r in range(rows) if r * cols < len(clips))
        n_rows = sum(1 for r in range(rows) if r * cols < len(clips))
        
        if n_rows == 1:
            filters.append(f"{row_labels}copy[grid]")
        else:
            filters.append(f"{row_labels}vstack=inputs={n_rows}[grid]")
        
        return ";".join(filters)


class SmartComposer(VideoComposer):
    """
    Enhanced composer with AI-driven decisions.
    """
    
    def __init__(self, config: CompositionConfig = None):
        super().__init__(config)
    
    def select_best_angle(self, segments_at_time: list) -> dict:
        """
        Select the best camera angle for a given time.
        Uses heuristics based on:
        - Motion quality
        - Framing
        - Audio quality
        """
        if not segments_at_time:
            return None
        
        best = None
        best_score = 0
        
        for seg in segments_at_time:
            score = 0
            
            # Prefer segments with beat alignment
            if seg.get('beat_aligned'):
                score += 10
            
            # Prefer longer segments
            duration = seg['end'] - seg['start']
            score += duration * 2
            
            # Prefer segments with higher energy (more action)
            score += seg.get('energy_avg', 0.5) * 20
            
            if score > best_score:
                best_score = score
                best = seg
        
        return best