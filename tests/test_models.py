"""Unit tests for src/models.py — Clip + ClipMetadata."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from models import Clip, ClipMetadata, _AudioShim, _probe_metadata  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _fixtures_present() -> bool:
    return (FIXTURES / "clip_a.mp4").exists()


def test_clip_basic_attributes():
    c = Clip(path="/some/dir/example.mp4")
    assert c.name == "example.mp4"
    assert c.render_path == "/some/dir/example.mp4"
    assert c.proxy_path is None
    assert c.duration == 0.0
    assert c.metadata is None


def test_clip_render_path_uses_proxy_when_set():
    c = Clip(path="/orig/big.mp4", proxy_path="/proxy/small.mp4")
    assert c.render_path == "/proxy/small.mp4"
    # Source path is still preserved
    assert c.path == "/orig/big.mp4"
    # Name comes from the original
    assert c.name == "big.mp4"


def test_clip_duration_reads_from_metadata():
    md = ClipMetadata(duration=42.5, fps=30.0, width=1920, height=1080)
    c = Clip(path="x.mp4", metadata=md)
    assert c.duration == 42.5
    assert c.metadata.fps == 30.0


def test_clip_from_path_without_probe_skips_metadata():
    """from_path with probe=False does no FFmpeg work."""
    c = Clip.from_path("nonexistent.mp4")  # probe defaults to False
    assert c.metadata is None
    assert c.path.endswith("nonexistent.mp4")


@pytest.mark.skipif(not _fixtures_present(), reason="fixtures not generated")
def test_clip_from_path_with_probe_populates_metadata():
    c = Clip.from_path(str(FIXTURES / "clip_a.mp4"), probe=True)
    assert c.metadata is not None
    assert c.metadata.duration > 0
    assert c.metadata.width == 320
    assert c.metadata.height == 240
    assert c.metadata.fps > 0
    assert c.metadata.codec == "h264"
    # Audio shim is populated
    assert c.audio is not None
    assert c.audio.duration == c.metadata.duration


def test_audio_shim_holds_duration():
    s = _AudioShim(12.34)
    assert s.duration == 12.34


def test_probe_metadata_on_missing_file_returns_empty():
    """Bad path should return zeroed ClipMetadata, not raise."""
    md = _probe_metadata("/this/does/not/exist.mp4")
    assert md.duration == 0.0
    assert md.width == 0
    assert md.height == 0
    assert md.codec == ""


def test_clip_metadata_dataclass_defaults():
    md = ClipMetadata()
    assert md.duration == 0.0
    assert md.fps == 0.0
    assert md.width == 0
    assert md.height == 0
    assert md.codec == ""
