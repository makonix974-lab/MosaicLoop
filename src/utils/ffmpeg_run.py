"""
Unified FFmpeg invocation helper.

One canonical way to spawn FFmpeg with:
- Optional progress bar driven by FFmpeg's `-progress` file output (no pipes)
- Stderr captured to a temp file (avoids the classic stderr=PIPE deadlock)
- Hard timeout to prevent indefinite hangs
- Cleanup of temp files on every exit path

Replaces the four near-duplicate progress-monitoring loops scattered across
proxy.py, video_composer.py (two), and smart_composer.py in v0.1.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FFmpegResult:
    """Outcome of an FFmpeg run."""
    success: bool
    returncode: int
    stderr: str       # populated only when success is False
    elapsed: float    # wall-clock seconds

    @property
    def short_error(self) -> str:
        """One-line error summary (last meaningful stderr line)."""
        if not self.stderr:
            return f"FFmpeg exit code {self.returncode}"
        for line in reversed(self.stderr.strip().split("\n")):
            line = line.strip()
            if line and "Stream mapping" not in line and "Output #" not in line:
                return line[:200]
        return f"FFmpeg exit code {self.returncode}"


def run_ffmpeg(
    cmd: list[str],
    *,
    total_duration: Optional[float] = None,
    show_progress: bool = True,
    timeout: float = 600.0,
) -> FFmpegResult:
    """
    Run an FFmpeg command safely with optional progress bar.

    Args:
        cmd: FFmpeg command list (without `-progress` flag — added automatically
             when show_progress is True).
        total_duration: Expected output duration in seconds. Required for the
             progress bar to compute percentage. If None or 0, no progress is
             shown even if show_progress is True.
        show_progress: When True, prints a 20-segment ASCII progress bar to
             stdout, refreshed up to twice per second.
        timeout: Hard timeout in seconds. The process is killed if exceeded.

    Returns:
        FFmpegResult. Check `.success` and read `.stderr` only on failure.
    """
    started = time.time()

    # Decide whether we actually want a progress bar
    enable_progress = bool(show_progress and total_duration and total_duration > 0)

    progress_path: Optional[str] = None
    stderr_path: str
    final_cmd = list(cmd)

    if enable_progress:
        progress_path = tempfile.NamedTemporaryFile(
            suffix=".progress", delete=False
        ).name
        final_cmd.extend(["-progress", progress_path])

    stderr_path = tempfile.NamedTemporaryFile(
        suffix=".stderr", delete=False
    ).name

    stderr_handle = open(stderr_path, "w", encoding="utf-8", errors="replace")

    try:
        process = subprocess.Popen(
            final_cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
        )

        if enable_progress:
            _poll_progress_until_done(
                process, progress_path, total_duration, timeout
            )
        else:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        # Drain remaining I/O
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        finally:
            stderr_handle.close()

        returncode = process.returncode
        success = returncode == 0

        stderr_text = ""
        if not success:
            try:
                stderr_text = Path(stderr_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                pass

        return FFmpegResult(
            success=success,
            returncode=returncode,
            stderr=stderr_text,
            elapsed=round(time.time() - started, 2),
        )

    finally:
        if not stderr_handle.closed:
            stderr_handle.close()
        for p in (progress_path, stderr_path):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass


def _poll_progress_until_done(
    process: subprocess.Popen,
    progress_path: str,
    total_duration: float,
    timeout: float,
) -> None:
    """
    Poll the FFmpeg `-progress` file and render an ASCII bar to stdout.
    Returns when the process exits or when timeout is reached.
    """
    started = time.time()
    last_pct = 0.0
    poll_interval = 0.5

    while process.poll() is None:
        if (time.time() - started) > timeout:
            process.kill()
            return

        try:
            content = Path(progress_path).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            content = ""

        # FFmpeg writes blocks separated by `progress=continue|end`. Look for
        # the most recent `out_time_ms=` line.
        latest_ms = None
        for line in content.split("\n"):
            if line.startswith("out_time_ms="):
                try:
                    latest_ms = int(line.split("=", 1)[1].strip())
                except (ValueError, IndexError):
                    pass

        if latest_ms and latest_ms > 0:
            pct = min(latest_ms / (total_duration * 1_000_000) * 100, 99.9)
            if pct - last_pct >= 2:
                _draw_bar(pct)
                last_pct = pct

        time.sleep(poll_interval)

    # Final bar at 100%
    _draw_bar(100.0)
    print()  # newline after the in-place bar


def _draw_bar(pct: float) -> None:
    filled = int(pct / 5)
    bar = "#" * filled + "." * (20 - filled)
    print(f"\r   [{bar}] {pct:.0f}%", end="", flush=True)
