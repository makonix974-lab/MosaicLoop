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
from utils.ffmpeg_run import run_ffmpeg


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

    @staticmethod
    def _extract_ffmpeg_error(stderr: str) -> str:
        """Extract the most relevant line from FFmpeg stderr."""
        if not stderr:
            return "Unknown FFmpeg error"
        lines = stderr.strip().split('\n')
        # Look for the last few error lines
        error_lines = [l for l in lines if 'error' in l.lower() or 'Invalid' in l or 'No such' in l]
        if error_lines:
            return error_lines[-1][:120]
        # Return last non-empty line
        meaningful = [l for l in lines if l.strip() and 'Stream mapping' not in l and 'Output' not in l]
        return (meaningful[-1][:120] if meaningful else lines[-1][:120])
    
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
        """Execute composition plan via FFmpeg concat demuxer."""
        if not plan:
            return {'success': False, 'error': 'Empty composition plan'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            concat_list_path = f.name

        try:
            with open(concat_list_path, 'w') as f:
                for segment in plan:
                    f.write(f"file '{segment['clip_path']}'\n")
                    f.write(f"inpoint {segment['clip_start']:.3f}\n")
                    f.write(f"outpoint {segment['clip_end']:.3f}\n")

            cmd = [self.ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list_path]

            audio_filters = []
            if self.config.audio_normalize:
                audio_filters.append('loudnorm=I=-16:TP=-1.5:LRA=11')
            if self.config.audio_gain != 1.0:
                audio_filters.append(f'volume={self.config.audio_gain}')
            if audio_filters:
                cmd.extend(['-af', ','.join(audio_filters)])

            cmd.extend(['-c:v', self.config.output_codec, '-preset', self.config.output_preset,
                        '-crf', str(self.config.output_crf), '-r', str(self.config.output_fps),
                        '-c:a', 'aac', '-b:a', '192k'])
            cmd.append(self.config.output_path)

            total_duration = sum(s['duration'] for s in plan)

            if show_progress:
                print("   Encoding video...")
                ProcessGuard.cleanup_stale()

            result = run_ffmpeg(
                cmd,
                total_duration=total_duration,
                show_progress=show_progress,
                timeout=1800,
            )

            if result.success:
                return {
                    'success': True,
                    'output_path': self.config.output_path,
                    'total_segments': len(plan),
                    'total_duration': total_duration,
                    'segments': plan,
                }
            return {
                'success': False,
                'error': f'FFmpeg exit code {result.returncode}: {result.short_error}',
            }
        finally:
            Path(concat_list_path).unlink(missing_ok=True)
    
    def compose_grid(self, clips: list, output_path: str = None,
                     show_progress: bool = True, audio_source: int = 0,
                     pad_seconds: list = None) -> dict:
        """
        Render a grid layout from N clips in a single FFmpeg pass.

        When `pad_seconds` is provided (list of non-negative floats, one per
        clip), each input video is delayed by its pad before being scaled
        and stacked, and the chosen audio source is delayed by its own pad.
        This collapses what was previously two separate steps (apply_offsets
        + compose_grid) into one FFmpeg invocation, eliminating intermediate
        files entirely.

        Args:
            clips: list of objects with a `.path` attribute (e.g. SimpleClip)
            output_path: override self.config.output_path
            show_progress: ASCII progress bar during encoding
            audio_source: index of the clip whose audio is used
            pad_seconds: per-clip delay in seconds (>=0). None => no padding.
        """
        if output_path:
            self.config.output_path = output_path
        if not clips:
            return {'success': False, 'error': 'No clips'}

        max_clips = min(len(clips), self.config.grid_cols * self.config.grid_rows)
        selected_clips = clips[:max_clips]
        pads = list(pad_seconds) if pad_seconds else [0.0] * len(selected_clips)
        # Pad list to match selected_clips length (truncate or extend with 0)
        pads = (pads[:max_clips] + [0.0] * max_clips)[:max_clips]

        filter_complex = self._build_grid_filter_with_pads(selected_clips, pads)
        audio_pad_s = pads[audio_source] if audio_source < len(pads) else 0.0
        if audio_pad_s > 0.05:
            filter_complex = (
                filter_complex + ";" +
                self._audio_pad_chain(audio_source, audio_pad_s)
            )

        cmd = [self.ffmpeg, '-y']
        for clip in selected_clips:
            cmd.extend(['-i', clip.path])

        cmd.extend(['-filter_complex', filter_complex])
        cmd.extend(['-map', '[grid]'])

        if audio_pad_s > 0.05:
            cmd.extend(['-map', '[aout]'])
        else:
            cmd.extend(['-map', f'{audio_source}:a'])

        cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
        cmd.extend([
            '-c:v', self.config.output_codec,
            '-preset', 'fast',
            '-crf', str(self.config.output_crf),
            '-r', str(self.config.output_fps),
        ])
        cmd.append(self.config.output_path)

        # Estimate total duration: longest clip + its pad
        durations = []
        for i, c in enumerate(selected_clips):
            d = (c.audio.duration if hasattr(c, 'audio') and c.audio
                 else getattr(c, 'duration', 0)) or 0
            durations.append(d + pads[i])
        total_duration = max(durations) if durations else 200
        if total_duration <= 0:
            total_duration = 200

        if show_progress:
            print("   Rendering grid...")
            ProcessGuard.cleanup_stale()

        result = run_ffmpeg(
            cmd,
            total_duration=total_duration,
            show_progress=show_progress,
            timeout=1800,
        )

        if result.success:
            return {
                'success': True,
                'output_path': self.config.output_path,
                'clips_used': max_clips,
                'grid': f'{self.config.grid_cols}x{self.config.grid_rows}',
            }
        return {
            'success': False,
            'error': f'FFmpeg exit code {result.returncode}: {result.short_error}',
        }
    
    def _build_grid_filter(self, clips: list) -> str:
        """Backward-compatible: build grid filter without padding."""
        return self._build_grid_filter_with_pads(clips, [0.0] * len(clips))

    def _build_grid_filter_with_pads(self, clips: list, pads: list) -> str:
        """
        Build FFmpeg filter_complex for an N-cell grid with optional per-clip
        VIDEO padding applied BEFORE scaling.

        For each input i with pad p_i (seconds):
          - if p_i > 0.05: prepend p_i seconds of black via tpad
          - then scale to cell size + center-crop

        Audio is handled separately by compose_grid (see _build_audio_chain).

        Output label: [grid]
        """
        cols = self.config.grid_cols
        rows = self.config.grid_rows
        cell_w = self.config.grid_cell_width
        cell_h = self.config.grid_cell_height

        filters: list[str] = []

        for i in range(len(clips)):
            pad = float(pads[i]) if i < len(pads) else 0.0
            chain_ops: list[str] = []
            if pad > 0.05:
                chain_ops.append(
                    f"tpad=start_duration={pad:.3f}:start_mode=add:color=black"
                )
            chain_ops.append(
                f"scale={cell_w}:{cell_h}:force_original_aspect_ratio=increase"
            )
            chain_ops.append(f"crop={cell_w}:{cell_h}")
            filters.append(f"[{i}:v]" + ",".join(chain_ops) + f"[v{i}]")

        for row in range(rows):
            idx_start = row * cols
            idx_end = min(idx_start + cols, len(clips))
            n_in_row = idx_end - idx_start
            if n_in_row == 0:
                continue
            if n_in_row == 1:
                filters.append(f"[v{idx_start}]copy[row{row}]")
            else:
                inputs = "".join(f"[v{idx_start + c}]" for c in range(n_in_row))
                filters.append(f"{inputs}hstack=inputs={n_in_row}[row{row}]")

        row_labels = "".join(
            f"[row{r}]" for r in range(rows) if r * cols < len(clips)
        )
        n_rows = sum(1 for r in range(rows) if r * cols < len(clips))
        if n_rows == 1:
            filters.append(f"{row_labels}copy[grid]")
        else:
            filters.append(f"{row_labels}vstack=inputs={n_rows}[grid]")

        return ";".join(filters)

    @staticmethod
    def _audio_pad_chain(audio_source: int, pad_seconds: float) -> str:
        """Audio sub-filter for padding the audio source. Output: [aout]."""
        ms = int(round(pad_seconds * 1000))
        return f"[{audio_source}:a]adelay={ms}|{ms}[aout]"