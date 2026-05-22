# GuitarMultiCam Studio — Project Status

## Current state (v0.2.0)

| Phase | Component | Status |
|---|---|---|
| 1 | Audio analyzer (BPM, onsets, energy, segments) | ✅ |
| 2 | Audio sync (onset cross-correlation) | ✅ — 95% test coverage |
| 3 | Video composer (grid, single-pass FFmpeg) | ✅ |
| 3b | Proxy workflow (parallel) | ✅ |
| 3c | GPU acceleration (NVENC / QSV) | ✅ |
| 4 | Session cache | ✅ |
| 5 | GUI (PyQt6) | 🔮 v0.3 (rebuild from scratch) |

## Tech stack

| Component | Library |
|---|---|
| Audio analysis | librosa |
| Numerics | numpy |
| Video processing | FFmpeg (subprocess) |
| CLI | click |
| GPU | NVENC / QSV (auto-detected) |
| Testing | pytest, pytest-cov |

Three Python deps. ~150 MB install (vs. ~400 MB in v0.1).

## Project structure

```
src/
├── pipeline.py
├── cache.py
├── models.py
├── analyzer/video_analyzer.py
├── sync/audio_sync.py
├── composer/
│   ├── video_composer.py
│   ├── proxy.py
│   ├── gpu_accel.py
│   └── process_guard.py
└── utils/ffmpeg_run.py

cli/main.py
tests/
├── conftest.py                  (auto-generates fixtures)
├── test_integration.py          (5 end-to-end tests)
├── test_sync.py
├── test_models.py
├── test_composer_filters.py
├── test_core.py
└── fixtures/_generate_fixtures.py

docs/
├── ARCHITECTURE.md
├── BASELINE.md
└── PROJECT.md (this file)

archive/v0.1/                    (smart_composer, gui, rush_sorter, ...)
archive/diagnostic_v0.1/         (morning-of-fix scripts)
archive/experiments/             (v0.1 prototypes)
```

## Roadmap

### v0.3 — GUI (planned)

Rebuild the GUI from scratch. The v0.1 GUI was a thin wrapper around the
CLI; the v0.3 target is a meaningful editor:
- Clip preview with waveform overlay
- Manual offset adjustment (override the auto-detected sync)
- Layout chooser
- Live progress

### Not on the roadmap

- "Smart" angle switching — the v0.1 implementation was based on audio
  energy, which is essentially identical across multi-cam clips. Doing
  it properly requires video-driven scoring (motion / framing /
  sharpness), which is its own R&D project.
- Built-in recording — out of scope; OBS / native cam apps already exist.
- Auto subtitles (Whisper) — out of scope.

These were promised in the v0.1 README and are explicitly removed.
