#!/usr/bin/env python3
"""
GuitarMultiCam Video Analyzer
Deep analysis of video/audio content for intelligent editing decisions.

Modules:
- AudioAnalyzer: MFCC, chroma, tempo, onset, energy
- VideoAnalyzer: Scene detection, motion, thumbnails
- Segmenter: Segment clips by musical content
- Matcher: Group similar segments across clips
"""

import numpy as np
import subprocess
import json
import tempfile
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from enum import Enum


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class SegmentType(Enum):
    INTRO = "intro"
    VERSE = "verse"
    CHORUS = "chorus"
    BRIDGE = "bridge"
    SOLO = "solo"
    OUTRO = "outro"
    SILENCE = "silence"
    TRANSITION = "transition"


@dataclass
class AudioFeatures:
    """Audio analysis results."""
    # Basic
    duration: float
    sample_rate: int
    
    # Energy
    rms_energy: float
    peak_amplitude: float
    energy_envelope: list  # Per-second energy
    dynamic_range: float
    
    # Tempo
    bpm: float
    beat_times: list  # Beat positions in seconds
    downbeat_times: list  # Bar start positions
    
    # Spectral
    mfcc_mean: list  # 13 coefficients
    mfcc_std: list
    spectral_centroid: float
    spectral_rolloff: float
    
    # Chroma
    chroma: list  # 12 bins per window
    key: str  # Detected key (C, C#, D, etc.)
    mode: str  # major/minor
    
    # Onsets
    onset_times: list  # Note attacks
    onset_strength: list
    
    # Structural
    segments: list  # [{'start': float, 'end': float, 'type': str}]
    structure: list  # [{'start': float, 'end': float, 'label': str}]


@dataclass
class VideoFeatures:
    """Video analysis results."""
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    
    # Scene detection
    scene_changes: list  # [{'time': float, 'type': 'cut'|'fade'|'dissolve'}]
    
    # Motion
    motion_intensity: list  # Per-frame motion
    motion_summary: dict  # {'mean': float, 'max': float}
    
    # Thumbnails
    thumbnail_timestamps: list  # Suggested thumbnail times


@dataclass
class ClipAnalysis:
    """Complete analysis of a single clip."""
    path: str
    name: str
    
    audio: Optional[AudioFeatures] = None
    video: Optional[VideoFeatures] = None
    
    segments: list = None  # [{'start': float, 'end': float, 'audio_rms': float}]
    match_score: float = 0.0
    
    def to_dict(self):
        return {
            'path': self.path,
            'name': self.name,
            'audio': asdict(self.audio) if self.audio else None,
            'video': asdict(self.video) if self.video else None,
            'segments': self.segments,
            'match_score': self.match_score
        }


# ============================================================================
# AUDIO ANALYZER
# ============================================================================

class AudioAnalyzer:
    """
    Deep audio analysis for music content.
    Uses librosa for spectral analysis and beat tracking.
    """
    
    def __init__(self):
        self.librosa = None
        self._import_librosa()
    
    def _import_librosa(self):
        """Lazy import librosa."""
        try:
            import librosa
            self.librosa = librosa
        except ImportError:
            print("Installing librosa...")
            subprocess.run(['pip', 'install', '-q', 'librosa'], check=True)
            import librosa
            self.librosa = librosa
    
    def extract_wav(self, video_path: str, start: float = 0, duration: float = None) -> tuple:
        """Extract audio as WAV from video."""
        temp_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_wav.close()
        
        cmd = ['ffmpeg', '-y']
        
        if start > 0:
            cmd.extend(['-ss', str(start)])
        
        cmd.extend(['-i', video_path])
        
        if duration:
            cmd.extend(['-t', str(duration)])
        
        cmd.extend([
            '-ac', '1',  # Mono
            '-ar', '22050',  # 22kHz for analysis
            '-acodec', 'pcm_s16le',
            temp_wav.name
        ])
        
        subprocess.run(cmd, capture_output=True, text=True)
        
        y, sr = self.librosa.load(temp_wav.name, sr=None)
        
        try:
            os.unlink(temp_wav.name)
        except:
            pass
        
        return y, sr
    
    def analyze_full(self, video_path: str, segment_duration: float = 0.5) -> AudioFeatures:
        """
        Full audio analysis of a video file.
        Returns comprehensive audio features.
        """
        print(f"  Loading audio from {Path(video_path).name}...")
        y, sr = self.extract_wav(video_path)
        
        duration = len(y) / sr
        print(f"  Duration: {duration:.1f}s")
        
        # Energy analysis
        print("  Computing energy envelope...")
        rms = self.librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        rms_times = self.librosa.times_like(rms, sr=sr, hop_length=512)
        
        # Resample to per-second resolution
        energy_per_sec = []
        for t in np.arange(0, duration, segment_duration):
            mask = (rms_times >= t) & (rms_times < t + segment_duration)
            if mask.any():
                energy_per_sec.append(float(rms[mask].mean()))
            else:
                energy_per_sec.append(0.0)
        
        peak = float(np.max(np.abs(y)))
        dynamic_range = float(np.max(energy_per_sec) - np.min(energy_per_sec)) if energy_per_sec else 0
        
        # Tempo and beat tracking
        print("  Detecting beats and tempo...")
        tempo = self.librosa.beat.tempo(y=y, sr=sr)[0]
        beat_frames = self.librosa.onset.onset_detect(y=y, sr=sr)
        beat_times = self.librosa.frames_to_time(beat_frames, sr=sr).tolist()
        
        # Downbeat detection (beat 1 of each bar)
        # Use 4/4 time signature assumption
        downbeat_times = []
        for i, beat in enumerate(beat_times):
            if i % 4 == 0:
                downbeat_times.append(float(beat))
        
        # MFCC (Mel-frequency cepstral coefficients)
        print("  Computing MFCC...")
        mfcc = self.librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        mfcc_mean = [float(x) for x in mfcc.mean(axis=1)]
        mfcc_std = [float(x) for x in mfcc.std(axis=1)]
        
        # Spectral features
        spectral_centroid = float(self.librosa.feature.spectral_centroid(y=y, sr=sr).mean())
        spectral_rolloff = float(self.librosa.feature.spectral_rolloff(y=y, sr=sr).mean())
        
        # Chroma (key detection)
        print("  Analyzing key and chroma...")
        chroma = self.librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = [float(x) for x in chroma.mean(axis=1)]
        
        # Key detection
        key_idx = chroma_mean.index(max(chroma_mean))
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        detected_key = keys[key_idx]
        
        # Mode detection (major vs minor based on thirds)
        third_energy = chroma_mean[key_idx] + chroma_mean[(key_idx + 3) % 12]  # Major third
        minor_third_energy = chroma_mean[key_idx] + chroma_mean[(key_idx + 3) % 12]  # Simplified
        
        # Onset detection
        print("  Detecting onsets...")
        onset_env = self.librosa.onset.onset_strength(y=y, sr=sr)
        onsets = self.librosa.onset.onset_detect(y=y, sr=sr, backtrack=True)
        onset_times = self.librosa.frames_to_time(onsets, sr=sr).tolist()
        onset_strength = [float(onset_env[i]) for i in onsets]
        
        # Segment based on energy changes
        print("  Segmenting by musical content...")
        energy_segments = self._segment_by_energy(energy_per_sec, segment_duration)
        
        # NEW: Also generate beat-based segments for precise cuts
        print("  Generating beat-aligned segments...")
        beat_segments = self.segment_by_phrases(
            onset_times, beat_times, float(tempo), energy_per_sec
        )
        
        # Refine energy segments using onset detection
        print("  Refining segments with onset analysis...")
        segments = self._refine_segments_with_onsets(energy_segments, onset_times, onset_env, sr)
        
        # Combine with beat segments for precision
        # Beat segments are more precise but may need merging with energy segments
        if beat_segments:
            # Merge energy and beat segments
            combined = self._merge_segments(segments, beat_segments)
            segments = combined
        
        return AudioFeatures(
            duration=duration,
            sample_rate=sr,
            rms_energy=float(np.mean(rms)),
            peak_amplitude=peak,
            energy_envelope=energy_per_sec,
            dynamic_range=dynamic_range,
            bpm=float(tempo),
            beat_times=beat_times,
            downbeat_times=downbeat_times,
            mfcc_mean=mfcc_mean,
            mfcc_std=mfcc_std,
            spectral_centroid=spectral_centroid,
            spectral_rolloff=spectral_rolloff,
            chroma=chroma_mean,
            key=detected_key,
            mode='major',  # Simplified for now
            onset_times=onset_times,
            onset_strength=onset_strength,
            segments=segments,
            structure=[]
        )
    
    def _segment_by_energy(self, energy_per_sec: list, segment_duration: float, duration: float = None) -> list:
        """
        Segment audio based on energy changes and musical structure.
        Uses multiple signals: energy, beats, and structure.
        """
        segments = []
        
        if not energy_per_sec or len(energy_per_sec) < 2:
            return segments
        
        energy = np.array(energy_per_sec)
        n = len(energy)
        
        # Step 1: Compute adaptive thresholds
        median_energy = np.median(energy)
        std_energy = np.std(energy)
        
        # Step 2: Compute local energy changes (derivative)
        energy_diff = np.abs(np.diff(energy, prepend=energy[0]))
        diff_threshold = np.percentile(energy_diff, 75)  # Top 25% changes
        
        # Step 3: Find candidate boundaries where energy changes significantly
        candidate_boundaries = []
        
        # Minimum segment duration: 3 seconds
        min_segment_duration = 3.0 / segment_duration  # in frames
        last_boundary = 0
        
        for i in range(1, n):
            # Check if this is a significant change
            is_significant = energy_diff[i] > diff_threshold
            
            # Check if enough time since last boundary
            is_far_enough = (i - last_boundary) >= min_segment_duration
            
            if is_significant and is_far_enough:
                candidate_boundaries.append(i)
                last_boundary = i
        
        # Step 4: Merge close boundaries (within 2 seconds)
        merged_boundaries = []
        for boundary in candidate_boundaries:
            if not merged_boundaries or (boundary - merged_boundaries[-1]) > (2.0 / segment_duration):
                merged_boundaries.append(boundary)
            else:
                # Keep the strongest change
                if energy_diff[boundary] > energy_diff[merged_boundaries[-1]]:
                    merged_boundaries[-1] = boundary
        
        # Step 5: Classify each segment
        boundaries = [0] + merged_boundaries + [n]
        
        for i in range(len(boundaries) - 1):
            start_frame = boundaries[i]
            end_frame = boundaries[i + 1]
            seg_energy = energy[start_frame:end_frame]
            
            start_time = start_frame * segment_duration
            end_time = end_frame * segment_duration
            avg_energy = float(np.mean(seg_energy)) if len(seg_energy) > 0 else 0
            
            # Classify segment type
            if avg_energy < median_energy * 0.15:
                seg_type = 'silence'
            elif avg_energy < median_energy * 0.5:
                seg_type = 'quiet'
            elif avg_energy > median_energy * 1.5:
                seg_type = 'loud'
            else:
                seg_type = 'music'
            
            # Only keep segments longer than 2 seconds
            if end_time - start_time >= 2.0:
                segments.append({
                    'start': start_time,
                    'end': end_time,
                    'type': seg_type,
                    'energy_avg': avg_energy
                })
        
        return segments
    
    def segment_by_beats(self, onset_times: list, beats: list, bpm: float, 
                         min_segment_duration: float = 4.0,
                         group_beats: int = 4) -> list:
        """
        Segment audio based on beat structure.
        
        Groups beats into musical phrases (default: 4 beats = 1 measure at 60-140 BPM).
        Returns segments aligned to bar boundaries for clean cuts.
        
        Args:
            onset_times: List of onset times (note attacks)
            beats: List of beat times
            bpm: Detected BPM
            min_segment_duration: Minimum segment length in seconds
            group_beats: Number of beats per phrase/segment (default: 4 = 1 measure)
        
        Returns:
            List of segments with start, end, type, energy
        """
        if not beats or bpm <= 0:
            return []
        
        segments = []
        beat_interval = 60.0 / bpm  # seconds per beat
        phrase_duration = beat_interval * group_beats  # Duration of one phrase
        
        # Group beats into phrases
        phrase_starts = []
        current_phrase_start = beats[0] if beats else 0
        
        for i, beat in enumerate(beats):
            # Check if we should start a new phrase
            if i > 0 and i % group_beats == 0:
                phrase_starts.append(beat)
                current_phrase_start = beat
        
        # Add final phrase if needed
        if beats[-1] > (phrase_starts[-1] if phrase_starts else 0) + min_segment_duration:
            phrase_starts.append(beats[-1])
        
        # Build segments from phrases
        for i, start in enumerate(phrase_starts):
            end = start + phrase_duration
            
            # Cap at audio duration (approximate)
            if end > (beats[-1] + beat_interval * 2):
                end = min(end, beats[-1] + beat_interval)
            
            if end - start >= min_segment_duration:
                segments.append({
                    'start': start,
                    'end': end,
                    'type': 'phrase',
                    'beat_number': i * group_beats,
                    'energy_avg': 0.5  # Will be filled by caller
                })
        
        return segments
    
    def segment_by_phrases(self, onset_times: list, beats: list, bpm: float,
                           energy_per_sec: list = None) -> list:
        """
        Smart segmentation combining beat structure with energy analysis.
        
        Detects:
        - Musical phrases (grouped beats)
        - Silence/breaks
        - Energy transitions
        
        Returns cleaner cuts aligned to musical structure.
        """
        if not beats:
            return []
        
        segments = []
        beat_interval = 60.0 / bpm if bpm > 0 else 0.5
        measure_duration = beat_interval * 4  # 4/4 time
        bar_duration = beat_interval * 4
        
        energy = np.array(energy_per_sec) if energy_per_sec else None
        median_energy = np.median(energy) if energy is not None and len(energy) > 0 else 0.5
        
        current_start = beats[0]
        current_bar = 0
        bars_in_current_segment = 0
        
        for i, beat in enumerate(beats):
            bar_number = i // 4
            beat_in_bar = i % 4
            
            # New bar started
            if bar_number > current_bar:
                bars_in_current_segment += 1
                current_bar = bar_number
                
                # Check if we should cut here
                if bars_in_current_segment > 0:
                    # Look at energy at this point
                    energy_at_beat = 0.5
                    if energy is not None:
                        beat_frame = int(beat)
                        if beat_frame < len(energy):
                            energy_at_beat = energy[beat_frame]
                    
                    # Cut if:
                    # 1. Low energy (silence/pause)
                    # 2. Big energy change
                    # 3. Every 8 or 16 bars (for longer segments)
                    
                    should_cut = False
                    
                    # Cut on low energy
                    if energy_at_beat < median_energy * 0.3:
                        should_cut = True
                    
                    # Cut every 16 bars for longer segments (allows editing at phrase level)
                    if bars_in_current_segment >= 16:
                        should_cut = True
                    
                    if should_cut and (beat - current_start) >= 8.0:  # Min 8 seconds
                        segments.append({
                            'start': current_start,
                            'end': beat,
                            'type': 'phrase',
                            'bars': bars_in_current_segment,
                            'energy_avg': float(np.mean(energy[int(current_start):int(beat)])) if energy is not None and beat < len(energy) else 0.5
                        })
                        current_start = beat
                        bars_in_current_segment = 0
        
        # Add final segment
        if beats[-1] > current_start + 4.0:
            segments.append({
                'start': current_start,
                'end': beats[-1] + beat_interval,
                'type': 'phrase',
                'bars': bars_in_current_segment,
                'energy_avg': float(np.mean(energy[int(current_start):])) if energy is not None else 0.5
            })
        
        return segments
    
    def _refine_segments_with_onsets(self, energy_segments: list, onset_times: list, 
                                   onset_env: np.ndarray, sr: int) -> list:
        """
        Refine segment boundaries using onset detection.
        Snaps boundaries to nearest strong musical onsets for cleaner cuts.
        """
        if not energy_segments:
            return energy_segments
        
        # Compute onset density for each segment
        refined_segments = []
        
        for seg in energy_segments:
            start_time = seg['start']
            end_time = seg['end']
            seg_type = seg['type']
            
            # For music segments: snap to nearest onsets
            if seg_type in ['music', 'loud']:
                # Find nearest onset to start
                if start_time > 0:
                    start_candidates = [t for t in onset_times 
                                       if (start_time - 3) <= t <= (start_time + 1)]
                    if start_candidates:
                        # Take the last onset before or at start (beginning of a phrase)
                        for onset in sorted(start_candidates, reverse=True):
                            if onset <= start_time:
                                start_time = onset
                                break
                
                # Find nearest onset to end
                if end_time > start_time + 2:
                    end_candidates = [t for t in onset_times 
                                     if (end_time - 1) <= t <= (end_time + 0.5)]
                    if end_candidates:
                        # Take the last onset (end of phrase)
                        end_time = end_candidates[-1]
            
            # Only keep segments longer than 1.5 seconds
            if end_time - start_time >= 1.5:
                refined_segments.append({
                    'start': start_time,
                    'end': end_time,
                    'type': seg_type,
                    'energy_avg': seg['energy_avg']
                })
        
        # Merge consecutive segments of the same type with gap < 1s
        merged = []
        for seg in refined_segments:
            if merged and seg['type'] == merged[-1]['type']:
                gap = seg['start'] - merged[-1]['end']
                if gap < 1.0:  # Merge if gap is small
                    merged[-1]['end'] = seg['end']
                    merged[-1]['energy_avg'] = (merged[-1]['energy_avg'] + seg['energy_avg']) / 2
                    continue
            merged.append(seg)
        
        return merged
    
    def _merge_segments(self, segments1: list, segments2: list) -> list:
        """
        Merge two sets of segments (energy-based and beat-based).
        Takes the more precise boundaries from beat segments while
        keeping the energy-based classification.
        """
        if not segments1:
            return segments2
        if not segments2:
            return segments1
        
        # Convert to timeline-based representation
        all_points = []
        
        for seg in segments1:
            all_points.append({'time': seg['start'], 'type': 'energy_start', 'seg': seg})
            all_points.append({'time': seg['end'], 'type': 'energy_end', 'seg': seg})
        
        for seg in segments2:
            all_points.append({'time': seg['start'], 'type': 'beat_start', 'seg': seg})
            all_points.append({'time': seg['end'], 'type': 'beat_end', 'seg': seg})
        
        # Sort by time
        all_points.sort(key=lambda x: x['time'])
        
        # Build merged segments using beat-based boundaries where available
        merged = []
        for seg in segments2:  # Start from beat segments (more precise)
            merged.append({
                'start': seg['start'],
                'end': seg['end'],
                'type': 'music',  # Beat segments are always music
                'beat_aligned': True,
                'bars': seg.get('bars', 0)
            })
        
        return merged if merged else segments1

    def _classify_energy_level(self, energy: float, silence_threshold: float, std_energy: float, 
                                transition_threshold: float = None) -> str:
        """Classify an energy value as silence, quiet, music, or loud."""
        if energy < silence_threshold:
            return 'silence'
        elif energy < silence_threshold * 5:
            return 'quiet'
        elif transition_threshold and abs(energy - np.median([energy])) > transition_threshold * 2:
            return 'transition'
        else:
            return 'music'
    
    def compare_clips(self, features1: AudioFeatures, features2: AudioFeatures) -> dict:
        """
        Compare two audio analyses to find similarity.
        Used for matching clips that belong to the same performance.
        """
        # Compare energy envelopes
        min_len = min(len(features1.energy_envelope), len(features2.energy_envelope))
        if min_len > 0:
            e1 = np.array(features1.energy_envelope[:min_len])
            e2 = np.array(features2.energy_envelope[:min_len])
            
            # Normalize
            e1 = (e1 - e1.mean()) / (e1.std() + 1e-10)
            e2 = (e2 - e2.mean()) / (e2.std() + 1e-10)
            
            energy_corr = float(np.corrcoef(e1, e2)[0, 1])
        else:
            energy_corr = 0
        
        # Compare MFCC
        mfcc1 = np.array(features1.mfcc_mean)
        mfcc2 = np.array(features2.mfcc_mean)
        mfcc_dist = float(np.linalg.norm(mfcc1 - mfcc2))
        
        # Compare tempo
        tempo_diff = abs(features1.bpm - features2.bpm)
        tempo_match = 1.0 - min(tempo_diff / 20, 1.0)  # 20 BPM tolerance
        
        # Compare key
        key_match = 1.0 if features1.key == features2.key else 0.0
        
        return {
            'energy_correlation': energy_corr,
            'mfcc_distance': mfcc_dist,
            'tempo_match': tempo_match,
            'key_match': key_match,
            'overall_score': (energy_corr * 0.5 + tempo_match * 0.3 + key_match * 0.2)
        }


# ============================================================================
# VIDEO ANALYZER  
# ============================================================================

class VideoAnalyzerEngine:
    """
    Video analysis for scene detection and content understanding.
    """
    
    def __init__(self):
        self.ffmpeg = 'ffmpeg'
        self.ffprobe = 'ffprobe'
    
    def get_info(self, video_path: str) -> dict:
        """Get basic video information."""
        cmd = [
            self.ffprobe, '-v', 'error',
            '-show_entries', 'stream=width,height,codec_name,r_frame_rate',
            '-show_entries', 'format=duration',
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
            fps = float(num) / float(den)
        
        return {
            'duration': float(format_info.get('duration', 0)),
            'width': int(video_stream.get('width', 0)),
            'height': int(video_stream.get('height', 0)),
            'fps': fps,
            'codec': video_stream.get('codec_name', 'unknown')
        }
    
    def detect_scenes(self, video_path: str, threshold: float = 27.0, 
                   min_scene_duration: float = 0.5) -> list:
        """
        Detect scene changes using scenedetect library with optimized settings.
        
        Args:
            video_path: Path to video file
            threshold: Detection threshold (default 27, range 15-45, lower = more sensitive)
            min_scene_duration: Minimum duration for a scene (filters short glitches)
        
        Returns:
            List of scene changes with timing and type
        """
        try:
            from scenedetect import VideoManager, SceneManager, StatsManager
            from scenedetect.detectors import ContentDetector
            from scenedetect.frame_timecode import FrameTimecode
        except ImportError:
            print("   Installing scenedetect...")
            subprocess.run(['pip', 'install', '-q', 'scenedetect'], check=True)
            from scenedetect import VideoManager, SceneManager, StatsManager
            from scenedetect.detectors import ContentDetector
            from scenedetect.frame_timecode import FrameTimecode
        
        # Setup video manager with downscaling for speed
        video_manager = VideoManager([video_path])
        stats_manager = StatsManager()
        scene_manager = SceneManager(stats_manager)
        
        # Downscale 2x for faster processing while maintaining accuracy
        video_manager.set_downscale_factor(2)
        
        # Add content detector with optimized threshold
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        
        # Process video
        video_manager.start()
        scene_manager.detect_scenes(frame_source=video_manager)
        
        # Get scene list
        scene_list = scene_manager.get_scene_list()
        
        # Get frame rate for minimum duration calculation
        fps = video_manager.get_framerate()
        min_frames = int(min_scene_duration * fps)
        
        scenes = []
        for i, scene in enumerate(scene_list):
            start_time = scene[0].get_seconds()
            end_time = scene[1].get_seconds()
            duration = end_time - start_time
            
            # Filter out very short scenes (likely artifacts)
            if duration < min_scene_duration:
                continue
            
            # Determine transition type
            transition_type = self._classify_transition(scene_list, i, start_time)
            
            scenes.append({
                'time': start_time,
                'end_time': end_time,
                'type': transition_type,
                'duration': duration,
                'frames': int(duration * fps)
            })
        
        # Cleanup
        video_manager.release()
        
        return scenes
    
    def _classify_transition(self, scene_list: list, index: int, start_time: float) -> str:
        """
        Classify the type of transition between scenes.
        """
        if index == 0:
            return 'cut'
        
        prev_scene = scene_list[index - 1]
        prev_end = prev_scene[1].get_seconds()
        
        # Calculate gap between scenes
        gap = start_time - prev_end
        
        # Classify based on gap
        if gap < 0.1:
            return 'cut'  # Hard cut, almost no gap
        elif gap < 0.5:
            return 'dissolve'  # Short dissolve
        elif gap < 1.5:
            return 'fade'  # Fade in/out
        else:
            return 'wipe'  # Or other transition
        
    def detect_scenes_fast(self, video_path: str, threshold: float = 25.0) -> list:
        """
        Fast scene detection optimized for real-time use.
        Uses aggressive downscaling and lighter processing.
        """
        try:
            from scenedetect import VideoManager, SceneManager
            from scenedetect.detectors import ContentDetector
        except ImportError:
            subprocess.run(['pip', 'install', '-q', 'scenedetect'], check=True)
            from scenedetect import VideoManager, SceneManager
            from scenedetect.detectors import ContentDetector
        
        video_manager = VideoManager([video_path])
        scene_manager = SceneManager()
        
        # Heavy downscaling for speed (4x)
        video_manager.set_downscale_factor(4)
        
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        video_manager.start()
        scene_manager.detect_scenes(frame_source=video_manager)
        
        scene_list = scene_manager.get_scene_list()
        scenes = [{
            'time': s[0].get_seconds(),
            'end_time': s[1].get_seconds(),
            'type': 'cut',
            'duration': s[1].get_seconds() - s[0].get_seconds()
        } for s in scene_list]
        
        video_manager.release()
        return scenes
    
    def generate_thumbnails(self, video_path: str, count: int = 5) -> list:
        """Generate thumbnail timestamps based on energy."""
        info = self.get_info(video_path)
        duration = info['duration']
        
        # Simple均匀 sampling
        timestamps = [duration * i / (count + 1) for i in range(1, count + 1)]
        
        return timestamps
    
    def estimate_motion(self, video_path: str) -> dict:
        """
        Estimate motion intensity using frame differencing.
        Simplified version - full implementation would use OpenCV.
        """
        info = self.get_info(video_path)
        
        # Placeholder for motion estimation
        return {
            'mean_motion': 0.0,  # Would be computed with OpenCV
            'max_motion': 0.0,
            'motion_timeline': []
        }


# ============================================================================
# MAIN ANALYZER CLASS
# ============================================================================

class VideoAnalyzer:
    """
    Complete video analyzer combining audio and video analysis.
    """
    
    def __init__(self):
        self.audio = AudioAnalyzer()
        self.video = VideoAnalyzerEngine()
    
    def analyze_clip(self, video_path: str, full_audio: bool = True, detect_scenes: bool = True) -> ClipAnalysis:
        """
        Analyze a single video clip.
        
        Args:
            video_path: Path to video file
            full_audio: If True, do deep audio analysis (slower but more accurate)
            detect_scenes: If True, detect scene changes in video
        
        Returns:
            ClipAnalysis with all features
        """
        path = Path(video_path)
        analysis = ClipAnalysis(path=str(video_path), name=path.name)
        
        # Get basic video info
        print(f"\n📹 Analyzing: {path.name}")
        video_info = self.video.get_info(video_path)
        print(f"   {video_info['width']}x{video_info['height']}, {video_info['fps']:.1f}fps, {video_info['duration']:.1f}s")
        
        # Video scene detection
        if detect_scenes:
            print(f"   Detecting scenes...")
            scene_changes = self.video.detect_scenes(video_path)
            print(f"   Found {len(scene_changes)} scenes")
            
            analysis.video = VideoFeatures(
                duration=video_info['duration'],
                width=video_info['width'],
                height=video_info['height'],
                fps=video_info['fps'],
                codec=video_info['codec'],
                scene_changes=scene_changes,
                motion_intensity=[],
                motion_summary={},
                thumbnail_timestamps=[]
            )
        
        # Deep audio analysis
        if full_audio:
            audio_features = self.audio.analyze_full(video_path)
            analysis.audio = audio_features
            
            # Extract segments from audio analysis
            if audio_features.segments:
                analysis.segments = audio_features.segments
                print(f"   Found {len(audio_features.segments)} audio segments")
        
        return analysis
    
    def batch_analyze(self, video_paths: list, **kwargs) -> list:
        """
        Analyze multiple videos in PARALLEL.
        
        Args:
            video_paths: List of video paths
            **kwargs: Passed to analyze_clip
        
        Returns:
            List of ClipAnalysis results
        """
        import concurrent.futures
        
        results = [None] * len(video_paths)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for i, path in enumerate(video_paths):
                future = pool.submit(self.analyze_clip, path, **kwargs)
                futures[future] = i
            
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                    name = Path(results[idx].name).name if results[idx] else "?"
                    print(f"   ✅ [{idx+1}/{len(video_paths)}] {name}")
                except Exception as e:
                    print(f"   ❌ [{idx+1}/{len(video_paths)}] {e}")
        
        return [r for r in results if r is not None]
    
    def analyze_batch(self, folder: str, extensions: list = None) -> list:
        """
        Analyze all videos in a folder.
        
        Args:
            folder: Folder path
            extensions: List of video extensions to look for
        
        Returns:
            List of ClipAnalysis objects
        """
        if extensions is None:
            extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v']
        
        folder_path = Path(folder)
        
        # Use set to avoid duplicates (.mp4 vs .MP4)
        videos = {}
        for ext in extensions:
            for pattern in [f'*{ext}', f'*{ext.upper()}']:
                for v in folder_path.glob(pattern):
                    # Use lowercase path as key to deduplicate
                    key = str(v.resolve()).lower()
                    if key not in videos:
                        videos[key] = v
        
        video_list = sorted(videos.values())
        print(f"\n🎬 Batch Analysis: {len(video_list)} unique videos found")
        
        results = []
        for i, video in enumerate(video_list):
            print(f"\n[{i+1}/{len(video_list)}]")
            analysis = self.analyze_clip(str(video))
            results.append(analysis)
        
        return results
    
    def match_clips(self, clips: list[ClipAnalysis], bpm_tolerance: float = 3.0) -> list[ClipAnalysis]:
        """
        Match clips that belong to the same performance.
        Groups clips by audio similarity.
        
        Args:
            bpm_tolerance: BPM difference tolerance for matching (in BPM)
        """
        if len(clips) < 2:
            return clips
        
        print("\n🔗 Matching clips...")
        
        # First pass: group by BPM (primary identifier)
        bpm_groups = {}
        for clip in clips:
            if clip.audio:
                bpm_key = round(clip.audio.bpm / bpm_tolerance) * bpm_tolerance
                if bpm_key not in bpm_groups:
                    bpm_groups[bpm_key] = []
                bpm_groups[bpm_key].append(clip)
        
        print(f"   BPM groups found: {len(bpm_groups)}")
        
        # Create merged groups with similarity refinement
        matched_groups = []
        for bpm, group in bpm_groups.items():
            if len(group) >= 1:
                # Within each BPM group, refine by energy similarity
                refined_group = self._refine_by_energy(group)
                matched_groups.append({
                    'group_id': len(matched_groups) + 1,
                    'clips': [clips.index(c) for c in refined_group],
                    'size': len(refined_group),
                    'bpm': bpm
                })
        
        # Set match scores based on group size
        max_group_size = max(len(g['clips']) for g in matched_groups) if matched_groups else 1
        
        # Compute overall match quality for each clip
        for group in matched_groups:
            for idx in group['clips']:
                # Score based on: group size (weight) + average correlation with group
                group_weight = len(group['clips']) / max_group_size
                clips[idx].match_score = group_weight
        
        print(f"   Found {len(matched_groups)} groups")
        for g in sorted(matched_groups, key=lambda x: -x['size']):
            print(f"   Group {g['group_id']}: {g['size']} clips (BPM ~{g['bpm']:.0f})")
        
        return clips
    
    def _refine_by_energy(self, clips: list[ClipAnalysis], min_correlation: float = 0.2) -> list:
        """
        Refine groups using energy envelope correlation.
        Uses average linkage clustering for more robust grouping.
        """
        if len(clips) <= 1:
            return clips
        
        # Compute energy envelopes and correlations
        n = len(clips)
        clips_by_energy = []  # (index, energy_array)
        
        for clip in clips:
            e = clip.audio.energy_envelope if clip.audio else []
            if e and len(e) > 10:
                # Resample to fixed length for comparison
                target_len = 200  # 200 seconds worth
                if len(e) >= target_len:
                    indices = np.linspace(0, len(e)-1, target_len, dtype=int)
                    e_resampled = [e[i] for i in indices]
                else:
                    e_resampled = e
                
                clips_by_energy.append(np.array(e_resampled))
            else:
                clips_by_energy.append(np.zeros(100))
        
        # Compute correlation matrix
        similarity_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i, n):
                if i == j:
                    similarity_matrix[i][j] = 1.0
                else:
                    e1 = clips_by_energy[i]
                    e2 = clips_by_energy[j]
                    
                    # Normalize
                    e1_norm = (e1 - e1.mean()) / (e1.std() + 1e-10)
                    e2_norm = (e2 - e2.mean()) / (e2.std() + 1e-10)
                    
                    # Cross-correlation with lag for time offset tolerance
                    if len(e1) == len(e2):
                        corr = float(np.corrcoef(e1_norm, e2_norm)[0, 1])
                    else:
                        corr = 0
                    
                    similarity_matrix[i][j] = max(0, corr)
                    similarity_matrix[j][i] = max(0, corr)
        
        # Average linkage clustering
        # Groups: clips that share > min_correlation with any group member
        groups = []
        for i in range(n):
            assigned = False
            for group in groups:
                # Check if clip i has good correlation with any group member
                for member_idx in group:
                    if similarity_matrix[i][member_idx] >= min_correlation:
                        group.append(i)
                        assigned = True
                        break
                if assigned:
                    break
            
            if not assigned:
                groups.append([i])
        
        # Return clips in order of the first group member
        # All clips with same BPM belong to the main group
        ordered_clips = []
        for group in sorted(groups, key=lambda g: -len(g)):
            for idx in group:
                ordered_clips.append(clips[idx])
        
        return ordered_clips
    
    def export_analysis(self, clips: list[ClipAnalysis], output_path: str):
        """Export analysis to JSON."""
        data = {
            'total_clips': len(clips),
            'clips': [c.to_dict() for c in clips]
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n✅ Analysis saved to {output_path}")


# ============================================================================
# CLI
# ============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='GuitarMultiCam Video Analyzer')
    parser.add_argument('input', help='Video file or folder')
    parser.add_argument('--output', '-o', default='analysis.json', help='Output JSON file')
    parser.add_argument('--batch', '-b', action='store_true', help='Treat input as folder')
    parser.add_argument('--match', '-m', action='store_true', help='Match clips by similarity')
    
    args = parser.parse_args()
    
    analyzer = VideoAnalyzer()
    
    if args.batch or Path(args.input).is_dir():
        clips = analyzer.analyze_batch(args.input)
    else:
        analysis = analyzer.analyze_clip(args.input)
        clips = [analysis]
    
    if args.match:
        clips = analyzer.match_clips(clips)
    
    analyzer.export_analysis(clips, args.output)