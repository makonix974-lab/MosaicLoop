#!/usr/bin/env python3
"""
Generate synthetic test fixtures for integration tests.

Strategy: render ONE common click-track WAV, then trim 5s windows out of it
for each clip. Each clip's video is a unique testsrc pattern (so we can
visually distinguish them in a grid), but the audio comes from the same
underlying source — only the start position differs.

Outputs:
  tests/fixtures/clip_a.mp4   (window: 0.0s..5.0s of common track)
  tests/fixtures/clip_b.mp4   (window: 1.5s..6.5s of common track)
  tests/fixtures/clip_c.mp4   (window: 0.7s..5.7s of common track)
  tests/fixtures/offsets.json (ground truth)

Expected sync result (when clip_a is reference):
  clip_a: 0.000s
  clip_b: -1.500s   (clip_b is 1.5s ahead = its content "starts later" in shared timeline)
  clip_c: -0.700s
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).parent
CLIP_DURATION = 5.0
COMMON_DURATION = 10.0
SAMPLE_RATE = 48000

# Click times in seconds (within the common track) — IRREGULAR pattern
# so cross-correlation has a unique peak (regular spacing produces multiple
# equal peaks at the click period and breaks the sync algorithm).
CLICK_TIMES = [0.43, 1.27, 2.81, 3.55, 5.12, 6.04, 7.39, 8.66, 9.18]

# (name, window_start_in_common_track, expected_offset_relative_to_clip_a)
# Sign convention (matches SyncManager.align_clips output):
#   positive offset = this clip's content starts LATER in the common timeline,
#   so it needs to be DELAYED (pre-padded) to align with the reference.
# clip_b's window starts 1.5s into the common track => offset = +1.5s
CLIPS = [
    ("clip_a.mp4", 0.0, 0.0),
    ("clip_b.mp4", 1.5, 1.5),
    ("clip_c.mp4", 0.7, 0.7),
    ("clip_d.mp4", 2.2, 2.2),
]


def ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def render_common_track(out_wav: Path) -> None:
    """Render 10s WAV with 6 decaying click pulses at known times. Uses numpy."""
    import numpy as np
    import wave

    n_samples = int(COMMON_DURATION * SAMPLE_RATE)
    t = np.arange(n_samples) / SAMPLE_RATE
    audio = np.zeros(n_samples, dtype=np.float64)

    for t0 in CLICK_TIMES:
        # Decaying sine starting at t0
        mask = t >= t0
        local_t = t[mask] - t0
        audio[mask] += np.sin(2 * np.pi * 880 * t[mask]) * np.exp(-30 * local_t)

    # Normalize to int16 range
    audio = audio / max(np.max(np.abs(audio)), 1e-9) * 0.7
    audio_i16 = (audio * 32767).astype(np.int16)

    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio_i16.tobytes())


def render_clip(common_wav: Path, out_path: Path, window_start: float, label: str) -> None:
    """Build clip: testsrc video + window_start..window_start+5 of common audio."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        # Unique video pattern with label overlay
        "-f", "lavfi",
        "-i", f"testsrc=size=320x240:rate=30:duration={CLIP_DURATION}",
        # Audio window from the common track
        "-ss", f"{window_start}",
        "-t", f"{CLIP_DURATION}",
        "-i", str(common_wav),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "30",
        "-t", f"{CLIP_DURATION}",  # hard cap
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    if not ffmpeg_ok():
        print("[ERROR] ffmpeg not found in PATH", file=sys.stderr)
        return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)

    print("[Fixtures] Rendering common click-track...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        common_wav = Path(tmp.name)
    try:
        render_common_track(common_wav)
        print(f"  [+] common track ({COMMON_DURATION}s, clicks at {CLICK_TIMES})")

        print("[Fixtures] Rendering clips...")
        for name, window, _expected in CLIPS:
            out = FIXTURES / name
            if out.exists():
                out.unlink()
            print(f"  [+] {name} (window: {window:.1f}s..{window + CLIP_DURATION:.1f}s)")
            render_clip(common_wav, out, window, name)
    finally:
        common_wav.unlink(missing_ok=True)

    # Ground truth
    ground_truth = {
        "description": "Synthetic fixtures with known sync offsets vs clip_a",
        "common_track": {
            "duration": COMMON_DURATION,
            "click_times": CLICK_TIMES,
            "click_freq_hz": 880,
        },
        "clip_duration": CLIP_DURATION,
        "expected_offsets_vs_clip_a": {
            name: expected for name, _w, expected in CLIPS
        },
        "tolerance_seconds": 0.10,
    }
    (FIXTURES / "offsets.json").write_text(
        json.dumps(ground_truth, indent=2), encoding="utf-8"
    )
    print(f"  [+] offsets.json (ground truth)")
    print("[OK] Fixtures generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
