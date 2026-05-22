"""
Unit tests for the new VideoComposer behaviors introduced in P5:
- filter_complex generation with per-clip padding
- audio pad chain
- compose_grid honoring pad_seconds end-to-end
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from composer.video_composer import VideoComposer, CompositionConfig  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _fixtures_present() -> bool:
    return (FIXTURES / "clip_a.mp4").exists()


# ---------------------------------------------------------------------------
# Filter builder — string contracts
# ---------------------------------------------------------------------------

class _FakeClip:
    def __init__(self, path: str) -> None:
        self.path = path


def _composer(rows: int = 2, cols: int = 2) -> VideoComposer:
    return VideoComposer(CompositionConfig(
        grid_cols=cols, grid_rows=rows,
        grid_cell_width=320, grid_cell_height=240,
    ))


def test_filter_complex_no_pads_2x2():
    """4 clips in 2x2 with no padding — pure scale + crop + hstack + vstack."""
    clips = [_FakeClip(f"x{i}.mp4") for i in range(4)]
    f = _composer(2, 2)._build_grid_filter_with_pads(clips, [0.0] * 4)
    # No tpad anywhere
    assert "tpad" not in f
    # Every input is scaled
    for i in range(4):
        assert f"[{i}:v]" in f
        assert f"[v{i}]" in f
    # Two hstacks (one per row), then vstack
    assert "hstack=inputs=2" in f
    assert "vstack=inputs=2" in f
    assert "[grid]" in f


def test_filter_complex_with_pads_inserts_tpad():
    clips = [_FakeClip(f"x{i}.mp4") for i in range(4)]
    f = _composer(2, 2)._build_grid_filter_with_pads(clips, [0.0, 1.5, 0.0, 0.7])
    # tpad appears for clips 1 and 3 only (pads > 0.05)
    assert f.count("tpad=start_duration=1.500") == 1
    assert f.count("tpad=start_duration=0.700") == 1
    # Clip 0 has pad 0 -> no tpad on its chain
    assert "[0:v]tpad" not in f


def test_filter_complex_2x1_layout():
    """2 clips in a 2x1 grid -> single hstack, single 'row' label, copied to grid."""
    clips = [_FakeClip("a.mp4"), _FakeClip("b.mp4")]
    f = _composer(rows=1, cols=2)._build_grid_filter_with_pads(clips, [0.0, 0.0])
    assert "hstack=inputs=2" in f
    # Single row -> copy[grid], no vstack
    assert "vstack" not in f
    assert "[row0]copy[grid]" in f


def test_filter_complex_pad_below_threshold_ignored():
    """Pads under 0.05s should NOT trigger tpad (avoid noisy reencodes)."""
    clips = [_FakeClip("a.mp4"), _FakeClip("b.mp4")]
    f = _composer(rows=1, cols=2)._build_grid_filter_with_pads(clips, [0.0, 0.04])
    assert "tpad" not in f


def test_audio_pad_chain_format():
    """[<src>:a]adelay=ms|ms[aout] for stereo padding."""
    chain = VideoComposer._audio_pad_chain(audio_source=2, pad_seconds=1.234)
    assert chain == "[2:a]adelay=1234|1234[aout]"


def test_audio_pad_chain_zero_seconds():
    """0s pad still produces a well-formed chain (caller decides whether to use it)."""
    chain = VideoComposer._audio_pad_chain(audio_source=0, pad_seconds=0.0)
    assert chain == "[0:a]adelay=0|0[aout]"


# ---------------------------------------------------------------------------
# compose_grid integration — pad_seconds is honored
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _fixtures_present(), reason="fixtures not generated")
def test_compose_grid_pad_seconds_extends_duration(tmp_path):
    """
    Padding the audio source by 1s should make the output ~1s longer than
    the longest input.
    """
    out = tmp_path / "padded_grid.mp4"
    cfg = CompositionConfig(
        output_path=str(out),
        output_width=640, output_height=360,
        grid_cols=2, grid_rows=1,
        grid_cell_width=320, grid_cell_height=360,
        output_fps=30,
    )
    comp = VideoComposer(cfg)

    class _Wrap:
        def __init__(self, p: str) -> None:
            self.path = p

    clips = [_Wrap(str(FIXTURES / "clip_a.mp4")), _Wrap(str(FIXTURES / "clip_b.mp4"))]
    result = comp.compose_grid(
        clips, show_progress=False, audio_source=0,
        pad_seconds=[1.0, 0.0],
    )
    assert result["success"], result.get("error")

    import subprocess
    import json
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(out)],
        capture_output=True, text=True, timeout=10,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    # clip_a is 5s, padded by 1s -> longest of [6.0, 5.0] = 6.0s
    assert 5.5 < duration < 7.0, f"unexpected duration: {duration}s"
