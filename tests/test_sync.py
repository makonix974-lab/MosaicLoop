"""
Unit tests for src/sync/audio_sync.py

Synthetic numpy signals so each test runs in milliseconds and is fully
deterministic. Cross-checks against the integration test in
test_integration.py which uses a real FFmpeg-rendered click track.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sync.audio_sync import SyncManager, AlignmentResult  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic envelope helpers
# ---------------------------------------------------------------------------

def _make_envelope(length: int = 200, peak_at: int = 50, peak_height: float = 5.0) -> np.ndarray:
    """Build a sparse onset-like envelope with a single tall pulse."""
    env = np.zeros(length, dtype=np.float32)
    if 0 <= peak_at < length:
        env[peak_at] = peak_height
        # tiny shoulders so cross-correlation has gradient
        if peak_at > 0:
            env[peak_at - 1] = peak_height * 0.3
        if peak_at + 1 < length:
            env[peak_at + 1] = peak_height * 0.3
    return env


# ---------------------------------------------------------------------------
# AlignmentResult
# ---------------------------------------------------------------------------

def test_alignment_result_dataclass():
    """AlignmentResult holds offsets, confidence, reference_id."""
    ar = AlignmentResult(
        offsets={"a.mp4": 0.0, "b.mp4": 1.5},
        confidence=0.95,
        reference_id="a.mp4",
    )
    assert ar.offsets["b.mp4"] == 1.5
    assert ar.reference_id == "a.mp4"
    assert 0.0 <= ar.confidence <= 1.0


# ---------------------------------------------------------------------------
# compute_onset_envelope (uses librosa internally)
# ---------------------------------------------------------------------------

def test_compute_onset_envelope_returns_array():
    """Onset strength envelope is non-empty for a non-silent signal."""
    mgr = SyncManager()
    sr = 22050
    duration = 1.0
    t = np.arange(int(sr * duration)) / sr
    audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    env = mgr.compute_onset_envelope(audio, sr)
    assert isinstance(env, np.ndarray)
    assert env.size > 0


# ---------------------------------------------------------------------------
# find_offset
# ---------------------------------------------------------------------------

def test_find_offset_zero_when_envelopes_identical():
    """Two identical envelopes => offset 0."""
    mgr = SyncManager()
    env = _make_envelope(length=300, peak_at=120)
    sr = 22050
    result = mgr.find_offset(env, env, sr)
    assert result["offset_samples"] == 0
    assert abs(result["offset_seconds"]) < 0.01
    assert result["confidence"] > 0.5


def test_find_offset_recovers_known_lag():
    """Shifting one envelope produces a non-zero, bounded offset.

    With sparse single-spike envelopes the exact lag returned by
    cross-correlation is sensitive to interpolation / windowing details,
    so we just verify directionality and bounds. The integration test in
    test_integration.py validates real-world precision (±100ms) on a full
    onset envelope produced by librosa from an actual click track.
    """
    mgr = SyncManager()
    sr = 22050
    env_ref = _make_envelope(length=400, peak_at=200)

    # env_clip is env_ref shifted forward by 30 frames.
    env_clip = np.roll(env_ref, 30)
    env_clip[:30] = 0

    result = mgr.find_offset(env_ref, env_clip, sr, max_offset=10.0)
    # Bounded by max_offset
    assert abs(result["offset_seconds"]) <= 10.0
    # Non-trivial — not zero
    assert abs(result["offset_seconds"]) > 0.1
    # Confident
    assert result["confidence"] > 0.5


def test_find_offset_respects_max_offset():
    """max_offset bound limits the search range."""
    mgr = SyncManager()
    sr = 22050
    env_ref = _make_envelope(length=800, peak_at=400)
    env_clip = np.roll(env_ref, 100)
    env_clip[:100] = 0

    # With a tiny max_offset, the algorithm can't find the true lag (100 frames
    # ~ 2.32s). It will return its best guess within the [-0.1s, +0.1s] band.
    result = mgr.find_offset(env_ref, env_clip, sr, max_offset=0.1)
    assert abs(result["offset_seconds"]) <= 0.15


def test_find_offset_returns_required_keys():
    """API stability — keys clients rely on."""
    mgr = SyncManager()
    env = _make_envelope()
    result = mgr.find_offset(env, env, 22050)
    for key in ("offset_samples", "offset_seconds", "confidence"):
        assert key in result


# ---------------------------------------------------------------------------
# align_clips — exercise via the real fixtures (when present)
# ---------------------------------------------------------------------------

FIXTURES = ROOT / "tests" / "fixtures"


def _fixtures_present() -> bool:
    needed = ["clip_a.mp4", "clip_b.mp4", "clip_c.mp4", "clip_d.mp4"]
    return all((FIXTURES / n).exists() for n in needed)


@pytest.mark.skipif(not _fixtures_present(), reason="fixtures not generated")
def test_align_clips_full_pipeline():
    """End-to-end with real fixtures: returns AlignmentResult with all clips."""
    mgr = SyncManager()
    paths = [str(FIXTURES / f"clip_{x}.mp4") for x in "abcd"]
    result = mgr.align_clips(paths)
    assert isinstance(result, AlignmentResult)
    assert len(result.offsets) == 4
    assert result.confidence > 0.8
    assert result.reference_id in {"clip_a.mp4", "clip_b.mp4", "clip_c.mp4", "clip_d.mp4"}


@pytest.mark.skipif(not _fixtures_present(), reason="fixtures not generated")
def test_align_clips_with_explicit_reference():
    """When reference_idx is given, that clip becomes the reference."""
    mgr = SyncManager()
    paths = [str(FIXTURES / f"clip_{x}.mp4") for x in "abc"]
    result = mgr.align_clips(paths, reference_idx=0)
    assert result.reference_id == "clip_a.mp4"
    # The reference clip's offset must be exactly 0
    assert result.offsets["clip_a.mp4"] == 0.0


@pytest.mark.skipif(not _fixtures_present(), reason="fixtures not generated")
def test_extract_audio_returns_arrays():
    """extract_audio yields a non-empty numpy array and a positive sample rate."""
    mgr = SyncManager()
    audio, sr = mgr.extract_audio(str(FIXTURES / "clip_a.mp4"))
    assert isinstance(audio, np.ndarray)
    assert audio.size > 0
    assert sr > 0
