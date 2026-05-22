"""
Unified data model for video clips.

Single source of truth replacing the v0.1 zoo:
- ClipWrap (defined inline in pipeline.py, cli/main.py, archived test files)
- SimpleClip (archived experiments)
- ClipAnalysis (analyzer/video_analyzer.py — kept there for API stability,
  but conceptually `Clip` is the canonical reference for the pipeline)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ClipMetadata:
    """Optional ffprobe-derived metadata for a clip."""
    duration: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""


@dataclass
class Clip:
    """
    A video clip used by the pipeline.

    Two paths track the source and an optional proxy. The composer always
    uses `proxy_path or path` so a Clip can flow through the pipeline before
    a proxy exists.
    """
    path: str                    # absolute or relative source path
    proxy_path: Optional[str] = None
    metadata: Optional[ClipMetadata] = None
    # Audio shim used by VideoComposer for duration estimation. Kept for
    # backward compatibility with the existing composer code that does
    # `c.audio.duration`. Populated from metadata.duration on demand.
    audio: Optional[object] = field(default=None, repr=False)

    @property
    def name(self) -> str:
        """Filename component of the source path."""
        return Path(self.path).name

    @property
    def render_path(self) -> str:
        """Path the composer should feed to FFmpeg (proxy when present)."""
        return self.proxy_path or self.path

    @property
    def duration(self) -> float:
        """Convenience accessor — 0 if metadata not loaded."""
        return self.metadata.duration if self.metadata else 0.0

    @classmethod
    def from_path(cls, path: str, *, probe: bool = False) -> "Clip":
        """
        Build a Clip from a path. With probe=True, populates metadata via
        ffprobe (one subprocess call). Cheap to skip when only the path is
        needed downstream.
        """
        clip = cls(path=str(path))
        if probe:
            clip.metadata = _probe_metadata(str(path))
            # Populate the legacy `.audio.duration` shim
            clip.audio = _AudioShim(clip.metadata.duration)
        return clip


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _AudioShim:
    """Tiny stand-in for ClipAnalysis.audio so VideoComposer can keep using
    `c.audio.duration` until that interface is also slimmed down."""
    __slots__ = ("duration",)

    def __init__(self, duration: float) -> None:
        self.duration = duration


def _probe_metadata(path: str) -> ClipMetadata:
    """Read duration / video stream info from a media file via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout) if result.stdout else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return ClipMetadata()

    duration = float(data.get("format", {}).get("duration", 0) or 0)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    fps = video_stream.get("r_frame_rate", "0/1")
    if "/" in fps:
        try:
            num, den = fps.split("/")
            fps_val = float(num) / float(den) if float(den) > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            fps_val = 0.0
    else:
        try:
            fps_val = float(fps)
        except ValueError:
            fps_val = 0.0

    return ClipMetadata(
        duration=duration,
        fps=fps_val,
        width=int(video_stream.get("width", 0) or 0),
        height=int(video_stream.get("height", 0) or 0),
        codec=video_stream.get("codec_name", "") or "",
    )
