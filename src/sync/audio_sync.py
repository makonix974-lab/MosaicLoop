#!/usr/bin/env python3
"""
Sync Manager — Multi-cam audio alignment via onset envelope cross-correlation.

Stratégie :
1. Extraire l'audio WAV de chaque clip (FFmpeg)
2. Calculer l'enveloppe d'onset (librosa onset_strength)
   -> capture le rythme, pas le timbre -> robuste à des micros différents
3. Cross-corrélation entre toutes les paires -> matrice d'offsets
4. Choisir le clip référence (meilleur score de confiance)
5. Aligner tous les clips sur la référence
6. Appliquer les offsets (trim/pad via FFmpeg)
"""

import subprocess
import tempfile
import json
from pathlib import Path
import numpy as np
from dataclasses import dataclass, asdict


@dataclass
class AlignmentResult:
    """Result of aligning clips."""
    offsets: dict  # {source_id: offset_seconds}
    confidence: float  # Average confidence
    reference_id: str  # Which clip was used as reference


class SyncManager:
    """
    Align multiple video clips by their audio content.
    Uses onset strength cross-correlation for robust sync.
    """
    
    def __init__(self):
        self.ffmpeg = 'ffmpeg'
        # librosa is a hard dependency (see requirements.txt); imported lazily
        # at first use so the rest of the package can be imported without it.
        self.librosa = None

    def _import_librosa(self):
        """Lazy import — librosa is in requirements.txt."""
        if self.librosa is None:
            import librosa
            self.librosa = librosa
    
    def extract_audio(self, video_path: str, start: float = 0, 
                      duration: float = None) -> tuple:
        """
        Extract audio from video as numpy array.
        Returns (audio_array, sample_rate).
        """
        self._import_librosa()
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            wav_path = f.name
        
        try:
            cmd = [self.ffmpeg, '-y', '-i', video_path]
            if start > 0:
                cmd.extend(['-ss', str(start)])
            if duration:
                cmd.extend(['-t', str(duration)])
            cmd.extend(['-vn', '-acodec', 'pcm_s16le', 
                       '-ar', '22050', '-ac', '1', wav_path])
            
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            y, sr = self.librosa.load(wav_path, sr=None)
            return y, sr
        
        finally:
            Path(wav_path).unlink(missing_ok=True)
    
    def compute_onset_envelope(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """
        Compute onset strength envelope.
        Captures rythm (note attacks), not timbre.
        This is what makes it robust to different microphones.
        """
        self._import_librosa()
        return self.librosa.onset.onset_strength(y=audio, sr=sr)
    
    def find_offset(self, env1: np.ndarray, env2: np.ndarray, sr: int,
                    max_offset: float = 10.0) -> dict:
        """
        Find offset between two onset envelopes.
        
        Args:
            env1: Reference onset envelope
            env2: Clip onset envelope (to align TO reference)
            sr: Sample rate of the onset analysis
            max_offset: Maximum expected offset in seconds
        
        Returns:
            dict with offset_seconds and confidence
        """
        # Cross-correlation
        corr = np.correlate(env1, env2, mode='full')
        
        # Limit search range to ±max_offset
        center = len(env1) - 1
        search_range = int(max_offset * sr / 512)  # librosa hop_length default
        start = max(0, center - search_range)
        end = min(len(corr), center + search_range)
        
        if start >= end:
            start = 0
            end = len(corr)
        
        search_corr = corr[start:end]
        peak_idx = np.argmax(search_corr) + start
        lag = peak_idx - center
        
        # Convert lag to seconds
        # onset_strength uses hop_length=512 by default
        hop_length = 512
        offset_seconds = lag * hop_length / sr
        
        # Confidence: peak correlation / RMS of correlation
        rms = np.sqrt(np.mean(corr ** 2))
        confidence = float(min(corr[peak_idx] / (rms + 1e-10), 1.0))
        
        return {
            'offset_samples': int(lag),
            'offset_seconds': float(offset_seconds),
            'confidence': confidence
        }
    
    def align_clips(self, clip_paths: list[str], 
                    reference_idx: int = None,
                    max_offset: float = 10.0) -> AlignmentResult:
        """
        Align multiple clips to a reference.
        
        Args:
            clip_paths: List of video paths to align
            reference_idx: Index of reference clip (None = auto-pick best)
            max_offset: Maximum offset to search (seconds)
        
        Returns:
            AlignmentResult with offsets and confidence
        """
        print(f"[Sync] Alignement de {len(clip_paths)} clips...")
        
        # Extract audio + compute onset envelopes
        envelopes = []
        for i, path in enumerate(clip_paths):
            print(f"   Analyse [{i+1}/{len(clip_paths)}] {Path(path).name}")
            audio, sr = self.extract_audio(path)
            env = self.compute_onset_envelope(audio, sr)
            envelopes.append({
                'path': path,
                'env': env,
                'sr': sr,
                'name': Path(path).name
            })
        
        # If no reference specified, use the clip with highest energy
        if reference_idx is None:
            energies = [np.sum(e['env']) for e in envelopes]
            reference_idx = int(np.argmax(energies))
        
        ref_name = envelopes[reference_idx]['name']
        print(f"   Référence: {ref_name}")
        
        # Find offset for each clip vs reference
        offsets = {}
        confidences = []
        ref_env = envelopes[reference_idx]['env']
        ref_sr = envelopes[reference_idx]['sr']
        
        for i, e in enumerate(envelopes):
            name = e['name']
            if i == reference_idx:
                offsets[name] = 0.0
                confidences.append(1.0)
                continue
            
            result = self.find_offset(ref_env, e['env'], ref_sr, max_offset)
            offsets[name] = result['offset_seconds']
            confidences.append(result['confidence'])
            
            status = "[OK]" if result['confidence'] > 0.3 else "[WARN]"
            print(f"   {status} {name}: offset={result['offset_seconds']:.3f}s "
                  f"conf={result['confidence']:.0%}")
        
        avg_confidence = float(np.mean(confidences))
        
        return AlignmentResult(
            offsets=offsets,
            confidence=avg_confidence,
            reference_id=ref_name
        )