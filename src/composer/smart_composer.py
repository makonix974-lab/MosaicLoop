"""
SmartComposer — AI-driven video composition using audio analysis.

Connects the analyzer (BPM, onsets, energy, segments) to the composer
for intelligent editing decisions:
- Beat-synced camera switching
- Energy-based angle selection
- Auto-trim silence
- Segment-aware composition (intro, verse, chorus, solo)
"""

import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from .video_composer import VideoComposer, CompositionConfig
from .process_guard import ProcessGuard


@dataclass
class SmartSegment:
    """A segment of the composition with smart editing metadata."""
    clip_path: str
    clip_name: str
    start: float
    end: float
    segment_type: str  # 'music', 'silence', 'quiet', 'loud', 'phrase'
    energy: float = 0.5
    beat_aligned: bool = False
    bars: int = 0


class SmartComposer(VideoComposer):
    """
    Enhanced composer using audio analysis for intelligent editing.

    Features:
    - Beat-synced camera switching (cuts on downbeats)
    - Energy-based angle selection (follow the action)
    - Auto-trim silence at start/end
    - Segment-aware composition (treats intro/verse/chorus differently)
    """

    def __init__(self, config: CompositionConfig = None):
        super().__init__(config)
        self.analyzer = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose_smart(
        self,
        clips: list,
        output_path: str = None,
        style: str = "auto",
        trim_silence: bool = True,
    ) -> dict:
        """
        Smart composition using audio analysis.

        Args:
            clips: List of clip paths or objects with .path attribute
            output_path: Output file path
            style: 'auto' (balanced), 'dynamic' (frequent cuts), 'stable' (long cuts)
            trim_silence: Auto-remove leading/trailing silence

        Returns:
            dict with composition result
        """
        if output_path:
            self.config.output_path = output_path

        paths = [c if isinstance(c, str) else c.path for c in clips]
        names = [Path(p).name for p in paths]

        if len(paths) < 2:
            return {"success": False, "error": "Need at least 2 clips for smart composition"}

        print("\n[SmartComposer] Analyzing clips...")
        analyzed = self._analyze(paths)
        if not analyzed or len(analyzed) < 1:
            return {"success": False, "error": "Analysis failed"}

        print(f"  Analyzed {len(analyzed)} clips")

        # Build segments from analyzer data
        segments = self._build_smart_segments(analyzed, style)

        if trim_silence:
            segments = self._trim_silence(segments)
            print(f"  After silence trim: {len(segments)} segments")

        if not segments:
            return {"success": False, "error": "No segments after analysis"}

        # Determine composition mode
        has_beat_data = any(s.beat_aligned for s in segments)
        if has_beat_data:
            print(f"  Beat-aligned segments available -> dynamic cuts")
        else:
            print(f"  Using energy-based segments for cuts")

        # Build composition plan
        plan = self._build_cut_plan(segments, paths, style)

        if not plan:
            return {"success": False, "error": "Empty composition plan"}

        print(f"  Plan: {len(plan)} segments, "
              f"duration: {sum(p['duration'] for p in plan):.1f}s")

        # Render
        return self._render_cuts(plan, paths)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _analyze(self, paths: list[str]) -> list:
        """Run audio analysis on all clips."""
        try:
            from analyzer.video_analyzer import VideoAnalyzer
            analyzer = VideoAnalyzer()
            analyzed = []
            for i, p in enumerate(paths):
                print(f"  [{i+1}/{len(paths)}] {Path(p).name}")
                clip = analyzer.analyze_clip(p, full_audio=True, detect_scenes=False)
                analyzed.append(clip)
            return analyzed
        except ImportError as e:
            print(f"  [WARN] Analyzer import failed: {e}")
            return []
        except Exception as e:
            print(f"  [WARN] Analysis error: {e}")
            return []

    # ------------------------------------------------------------------
    # Segment building
    # ------------------------------------------------------------------

    def _build_smart_segments(
        self, analyzed: list, style: str
    ) -> list[SmartSegment]:
        """Build SmartSegments from analyzer data."""
        segments = []

        for clip in analyzed:
            if not clip.audio or not clip.audio.segments:
                continue

            for seg in clip.audio.segments:
                segments.append(SmartSegment(
                    clip_path=clip.path,
                    clip_name=clip.name,
                    start=seg.get("start", 0),
                    end=seg.get("end", 0),
                    segment_type=seg.get("type", "music"),
                    energy=seg.get("energy_avg", 0.5),
                    beat_aligned=seg.get("beat_aligned", False),
                    bars=seg.get("bars", 0),
                ))

        if not segments:
            return self._fallback_segments(analyzed, style)

        # Merge segments by time similarity (align clips)
        merged = self._merge_segments_across_clips(segments, style)
        return merged

    def _fallback_segments(
        self, analyzed: list, style: str
    ) -> list[SmartSegment]:
        """Create artificial segments when analysis has no segments."""
        segments = []
        for clip in analyzed:
            if clip.audio:
                duration = clip.audio.duration
                if duration <= 0:
                    continue
                chunk = 8.0 if style == "stable" else 4.0 if style == "auto" else 2.0
                t = 0.0
                while t < duration:
                    end = min(t + chunk, duration)
                    energy_idx = min(int(t), len(clip.audio.energy_envelope) - 1) if clip.audio.energy_envelope else 0
                    energy = clip.audio.energy_envelope[energy_idx] if clip.audio.energy_envelope else 0.5
                    segments.append(SmartSegment(
                        clip_path=clip.path,
                        clip_name=clip.name,
                        start=t, end=end,
                        segment_type="music",
                        energy=energy,
                    ))
                    t = end
        return segments

    def _merge_segments_across_clips(
        self, segments: list[SmartSegment], style: str
    ) -> list[SmartSegment]:
        """Merge segments from different clips by aligning time windows."""
        energy_map = {}  # { (time_window): [(clip_name, energy)] }

        for seg in segments:
            key = (round(seg.start, 1), round(seg.end, 1))
            if key not in energy_map:
                energy_map[key] = []
            energy_map[key].append((seg.clip_name, seg.energy, seg.clip_path))

        result = []
        for (start, end), candidates in sorted(energy_map.items()):
            # Pick the best candidate for this time window
            best = max(candidates, key=lambda x: x[1])  # highest energy
            is_beat = any(
                s.beat_aligned for ss in segments
                if round(ss.start, 1) == start and ss.beat_aligned
                for s in [ss]
            )
            result.append(SmartSegment(
                clip_path=best[2],
                clip_name=best[0],
                start=start, end=end,
                segment_type="music",
                energy=best[1],
                beat_aligned=is_beat,
            ))

        return result

    def _trim_silence(
        self, segments: list[SmartSegment]
    ) -> list[SmartSegment]:
        """Remove silence segments at start and end."""
        if not segments:
            return segments

        # Trim leading silence
        start_idx = 0
        for i, seg in enumerate(segments):
            if seg.segment_type != "silence" or seg.energy > 0.05:
                start_idx = i
                break

        # Trim trailing silence (work backwards)
        end_idx = len(segments) - 1
        for i in range(len(segments) - 1, -1, -1):
            if segments[i].segment_type != "silence" or segments[i].energy > 0.05:
                end_idx = i
                break

        trimmed = segments[start_idx : end_idx + 1]

        # Also remove short gaps (< 0.5s) that are silence
        filtered = []
        for seg in trimmed:
            duration = seg.end - seg.start
            if seg.segment_type == "silence" and duration < 0.5:
                continue
            filtered.append(seg)

        return filtered

    # ------------------------------------------------------------------
    # Composition plan
    # ------------------------------------------------------------------

    def _build_cut_plan(
        self, segments: list[SmartSegment],
        paths: list[str], style: str
    ) -> list[dict]:
        """Build a cut-by-cut plan: which clip at which time."""
        plan = []
        used_clips = set()

        # Filter to minimum duration based on style
        min_dur = {"dynamic": 1.0, "auto": 2.0, "stable": 4.0}.get(style, 2.0)
        valid = [s for s in segments if s.end - s.start >= min_dur]

        if not valid:
            # Use segments as-is if filtered too aggressively
            valid = segments

        # Group consecutive same-clip segments to avoid rapid cuts
        prev_clip = None
        prev_seg = None
        carry = 0.0

        for seg in valid:
            if prev_clip is None:
                prev_clip = seg.clip_name
                prev_seg = seg
                carry = seg.energy
                continue

            # Should we cut or stay?
            if seg.clip_name == prev_clip:
                # Same camera - extend
                prev_seg = seg
                carry = max(carry, seg.energy)
            else:
                # Different camera - decide if we should cut
                energy_ratio = seg.energy / max(carry, 0.01) if carry > 0 else 1.0
                should_cut = False

                if energy_ratio > 1.3:
                    # New clip is significantly more energetic - cut
                    should_cut = True
                elif seg.beat_aligned and prev_seg and prev_seg.end - prev_seg.start >= min_dur * 2:
                    # Beat boundary and enough time on current clip - cut
                    should_cut = True
                elif style == "dynamic" and prev_seg and prev_seg.end - prev_seg.start >= min_dur:
                    # Dynamic mode: cut more frequently
                    should_cut = True

                if should_cut:
                    plan.append({
                        "clip_path": prev_seg.clip_path,
                        "clip_name": prev_seg.clip_name,
                        "start": prev_seg.start,
                        "end": seg.start,
                        "duration": seg.start - prev_seg.start,
                    })
                    prev_clip = seg.clip_name
                    prev_seg = seg
                    carry = seg.energy
                    used_clips.add(seg.clip_name)
                else:
                    # Stay with previous clip, extend it
                    prev_seg = seg
                    carry = max(carry, seg.energy)

        # Final segment
        if prev_seg is not None:
            plan.append({
                "clip_path": prev_seg.clip_path,
                "clip_name": prev_seg.clip_name,
                "start": prev_seg.start,
                "end": prev_seg.end,
                "duration": prev_seg.end - prev_seg.start,
            })

        return plan

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_cuts(self, plan: list[dict], paths: list[str]) -> dict:
        """Render the cut plan as a linear video using concat."""
        Path(self.config.output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build concat list
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as f:
            concat_path = f.name

        try:
            with open(concat_path, "w") as f:
                for seg in plan:
                    f.write(f"file '{seg['clip_path']}'\n")
                    f.write(f"inpoint {seg['start']:.3f}\n")
                    f.write(f"outpoint {seg['end']:.3f}\n")

            total_duration = sum(s["duration"] for s in plan)

            cmd = [
                self.ffmpeg, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_path,
            ]

            # Audio crossfade between cuts if duration allows
            if total_duration > 10:
                cmd += ["-af", "acrossfade=d=0.1,volume=1.5"]

            cmd += [
                "-c:v", self.config.output_codec,
                "-preset", self.config.output_preset,
                "-crf", str(self.config.output_crf),
                "-c:a", "aac", "-b:a", "192k",
                self.config.output_path,
            ]

            print("  Rendering smart composition...")
            ProcessGuard.cleanup_stale()
            guard = ProcessGuard("smart_compose")

            progress_path = tempfile.NamedTemporaryFile(
                suffix=".progress", delete=False).name
            cmd.extend(["-progress", progress_path])

            process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            guard.track(process.pid, "smart_compose")

            last_pct = 0
            while process.poll() is None:
                try:
                    with open(progress_path, "r", errors="replace") as pf:
                        for line in pf.read().split("\n"):
                            if "out_time_ms=" in line:
                                ms = int(line.split("=")[1].strip())
                                if ms > 0 and total_duration > 0:
                                    pct = min(
                                        ms / (total_duration * 1_000_000) * 100,
                                        99.9,
                                    )
                                    if pct - last_pct >= 2:
                                        bar = "#" * int(pct / 5)
                                        bar += "." * (20 - int(pct / 5))
                                        print(f"\r   [{bar}] {pct:.0f}%",
                                              end="", flush=True)
                                        last_pct = pct
                except (OSError, ValueError):
                    pass
                import time
                time.sleep(0.5)

            process.wait()
            guard.untrack(process.pid)
            print(f"\r   [{"#" * 20}] 100%")

            try:
                Path(progress_path).unlink(missing_ok=True)
            except OSError:
                pass

            if process.returncode == 0:
                switch_count = sum(
                    1 for i in range(1, len(plan))
                    if plan[i]["clip_name"] != plan[i - 1]["clip_name"]
                )
                return {
                    "success": True,
                    "output_path": self.config.output_path,
                    "total_segments": len(plan),
                    "total_duration": total_duration,
                    "camera_switches": switch_count,
                    "mode": "smart",
                }
            else:
                return {
                    "success": False,
                    "error": f"FFmpeg exit code {process.returncode}",
                }

        finally:
            Path(concat_path).unlink(missing_ok=True)
