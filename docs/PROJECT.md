# GuitarMultiCam Studio — Project

## Status

| Phase | Component | Status | Notes |
|-------|-----------|--------|-------|
| 1 | Video Analyzer | ✅ Complete | MFCC, BPM, onset, segmentation |
| 2 | Audio Sync | ✅ Complete | Onset cross-correlation alignment |
| 3 | Video Composer | 🟡 Partial | Grid works, smart features WIP |
| 3b | Proxy Workflow | ✅ Complete | Parallel proxy generation |
| 3c | GPU Acceleration | ✅ Complete | NVIDIA NVENC, Intel QSV |
| 4 | GUI (PyQt6) | 🔮 Planned | Module scaffolded |
| 5 | Record Module | 🔮 Planned | Module scaffolded |
| 6 | Export Pipeline | 🔮 Planned | Module scaffolded |

## Current State (v0.1.0)

Working features:
- [x] Audio extraction & deep analysis (librosa)
- [x] Multi-clip sync by onset cross-correlation
- [x] 2x2 grid composition with FFmpeg
- [x] Parallel proxy generation (4x speedup)
- [x] GPU-accelerated encoding (NVENC/QSV)
- [x] Process guard (zombie FFmpeg cleanup)
- [x] CLI with 4 commands: auto, sync, compose, analyze
- [x] Social presets (YouTube, Instagram, TikTok)

WIP features:
- [ ] Smart angle switching from analyzer data
- [ ] Beat-synced transitions
- [ ] Audio normalization presets

## Tech Stack

| Component | Library |
|-----------|---------|
| Audio analysis | librosa, scipy, numpy |
| Video processing | FFmpeg (subprocess) |
| Scene detection | PySceneDetect |
| CLI | click |
| Progress | tqdm |
| GPU | NVENC / QSV (auto-detect) |
| GUI (future) | PyQt6 |

## Project Structure

```
guitarmulticam/
├── src/
│   ├── pipeline.py         # Workflow orchestration
│   ├── analyzer/           # Video/audio analysis
│   ├── sync/               # Audio sync engine
│   └── composer/           # Video composition + proxy + GPU
│       ├── video_composer.py
│       ├── proxy.py
│       ├── gpu_accel.py
│       └── process_guard.py
├── cli/main.py             # CLI entry point
├── tests/                  # Unit tests (TODO)
├── docs/                   # Documentation
└── archive/experiments/    # Archived prototypes
```
