#!/usr/bin/env python3
"""
Audio analyzer — slim version (v0.2).

What v0.1 had and we DROPPED:
- MFCC, chroma, spectral centroid/rolloff, key/mode detection
  (academically interesting, never used in the actual pipeline)
- Scene detection via PySceneDetect
  (irrelevant for static-camera music performances; cost ~250 MB of deps)
- Motion estimation, thumbnail timestamps
- compare_clips, match_clips, _refine_by_energy
  (a different product: rush grouping by similarity; out of scope)
- segment_by_phrases / segment_by_beats with hardcoded 4/4
  (the smart_composer that consumed this is archived)

What we KEEP:
- WAV extraction via FFmpeg
- Energy envelope (per-second RMS)
- BPM + beat times via librosa
- Onset detection
- Simple energy-based segmentation (silence/quiet/music/loud)

Public API (used by pipeline.analyze() and cli analyze command):
    analyzer = VideoAnalyzer()
    clips = analyzer.batch_analyze(["a.mp4", "b.mp4"])
    for c in clips:
        c.to_dict()  # JSON-serializable
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AudioFeatures:
    """Audio analysis output for one clip."""
    duration: float
    sample_rate: int
    rms_energy: float           # mean RMS across the whole clip
    peak_amplitude: float       # max absolute sample value
    energy_envelope: list       # per-segment_duration RMS values
    bpm: float
    beat_times: list            # seconds, librosa beat tracking
    onset_times: list           # seconds, note attacks
    segments: list              # [{start, end, type, energy_avg}]


@dataclass
class ClipAnalysis:
    """Complete analysis of one clip."""
    path: str
    name: str
    audio: Optional[AudioFeatures] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "audio": asdict(self.audio) if self.audio else None,
        }


# ---------------------------------------------------------------------------
# Audio extraction + analysis
# ---------------------------------------------------------------------------

def _extract_wav(video_path: str, sample_rate: int = 22050) -> tuple[np.ndarray, int]:
    """Extract mono audio from a video file as a numpy float array."""
    import librosa  # lazy
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", video_path,
            "-ac", "1",
            "-ar", str(sample_rate),
            "-acodec", "pcm_s16le",
            wav_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        y, sr = librosa.load(wav_path, sr=None)
        return y, sr
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def _energy_envelope(audio: np.ndarray, sr: int, segment_duration: float = 0.5) -> list[float]:
    """Per-segment RMS energy."""
    import librosa
    rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.times_like(rms, sr=sr, hop_length=512)

    duration = len(audio) / sr
    envelope: list[float] = []
    t = 0.0
    while t < duration:
        mask = (rms_times >= t) & (rms_times < t + segment_duration)
        envelope.append(float(rms[mask].mean()) if mask.any() else 0.0)
        t += segment_duration
    return envelope


def _segment_by_energy(envelope: list[float], segment_duration: float) -> list[dict]:
    """
    Boundary-detect segments where energy changes significantly.
    Classifies each segment as silence/quiet/music/loud relative to the median.
    Drops segments shorter than 2 seconds.
    """
    if len(envelope) < 2:
        return []

    energy = np.array(envelope)
    median = np.median(energy)
    diff = np.abs(np.diff(energy, prepend=energy[0]))
    threshold = np.percentile(diff, 75)

    min_frames = max(1, int(3.0 / segment_duration))
    last = 0
    boundaries: list[int] = []
    for i in range(1, len(energy)):
        if diff[i] > threshold and (i - last) >= min_frames:
            boundaries.append(i)
            last = i

    edges = [0, *boundaries, len(energy)]
    out: list[dict] = []
    for i in range(len(edges) - 1):
        s, e = edges[i], edges[i + 1]
        if e <= s:
            continue
        avg = float(energy[s:e].mean())
        start_t, end_t = s * segment_duration, e * segment_duration
        if end_t - start_t < 2.0:
            continue
        if avg < median * 0.15:
            seg_type = "silence"
        elif avg < median * 0.5:
            seg_type = "quiet"
        elif avg > median * 1.5:
            seg_type = "loud"
        else:
            seg_type = "music"
        out.append({
            "start": round(start_t, 3),
            "end": round(end_t, 3),
            "type": seg_type,
            "energy_avg": round(avg, 6),
        })
    return out


def _analyze_audio(video_path: str) -> AudioFeatures:
    """Full audio analysis of one clip — keeps only features actually used."""
    import librosa
    y, sr = _extract_wav(video_path)
    duration = len(y) / sr

    envelope = _energy_envelope(y, sr, segment_duration=0.5)

    rms_full = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_mean = float(np.mean(rms_full))
    peak = float(np.max(np.abs(y)))

    # BPM + beat times
    try:
        tempo_arr = librosa.beat.tempo(y=y, sr=sr)
        bpm = float(tempo_arr[0]) if len(tempo_arr) else 0.0
    except Exception:
        bpm = 0.0

    try:
        beat_frames = librosa.onset.onset_detect(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    except Exception:
        beat_times = []

    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, backtrack=True)
        onset_times = librosa.frames_to_time(onsets, sr=sr).tolist()
    except Exception:
        onset_times = []

    segments = _segment_by_energy(envelope, segment_duration=0.5)

    return AudioFeatures(
        duration=round(duration, 3),
        sample_rate=int(sr),
        rms_energy=round(rms_mean, 6),
        peak_amplitude=round(peak, 6),
        energy_envelope=envelope,
        bpm=round(bpm, 2),
        beat_times=[round(t, 3) for t in beat_times],
        onset_times=[round(t, 3) for t in onset_times],
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class VideoAnalyzer:
    """Top-level analyzer used by the CLI `analyze` command."""

    def analyze_clip(self, video_path: str) -> ClipAnalysis:
        """Analyze a single clip. Audio-only, no scene detection."""
        path = Path(video_path)
        result = ClipAnalysis(path=str(path), name=path.name)
        try:
            result.audio = _analyze_audio(str(path))
        except Exception as e:
            print(f"   [WARN] {path.name}: audio analysis failed ({e})")
        return result

    def batch_analyze(self, video_paths: list[str], max_workers: int = 4) -> list[ClipAnalysis]:
        """Parallel analysis. Returns results in input order."""
        results: list[Optional[ClipAnalysis]] = [None] * len(video_paths)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self.analyze_clip, p): i
                for i, p in enumerate(video_paths)
            }
            for fut in concurrent.futures.as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                    name = Path(video_paths[idx]).name
                    print(f"   [OK] [{idx + 1}/{len(video_paths)}] {name}")
                except Exception as e:
                    print(f"   [FAIL] [{idx + 1}/{len(video_paths)}] {e}")
        return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# CLI fallback (rare — usually invoked via the top-level guitarcam CLI)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Audio analyzer (slim)")
    p.add_argument("inputs", nargs="+", help="Video files to analyze")
    p.add_argument("--output", "-o", default="analysis.json", help="Output JSON")
    args = p.parse_args()

    analyzer = VideoAnalyzer()
    clips = analyzer.batch_analyze(args.inputs)
    Path(args.output).write_text(
        json.dumps([c.to_dict() for c in clips], indent=2),
        encoding="utf-8",
    )
    print(f"\n[OK] {len(clips)} clip(s) analyzed -> {args.output}")
