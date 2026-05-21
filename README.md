# GuitarMultiCam Studio

**Auto-edit tool for musicians** — Record, sync, and compose multi-cam videos with AI assistance.

## Quick Start

```bash
# Install
pip install -r requirements.txt

# One-shot: sync + compose 4 clips into a 2x2 grid
python cli/main.py auto --clips cam1.mp4 cam2.mp4 cam3.mp4 cam4.mp4 --output final.mp4

# With preset for social media
python cli/main.py auto --clips *.mp4 --preset youtube --output youtube.mp4
python cli/main.py auto --clips *.mp4 --preset tiktok --output tiktok.mp4

# Just analyze (preview metadata)
python cli/main.py analyze --clips *.mp4 --output analysis.json

# Just sync (get offsets)
python cli/main.py sync --clips *.mp4 --output offsets.json

# Just compose (pre-synced clips)
python cli/main.py compose --clips *.mp4 --output grid.mp4 --layout 2x2
```

## Requirements

- **Python 3.9+**
- **FFmpeg** (in PATH) — [Download](https://ffmpeg.org/download.html)
- **CUDA** (optional) — for GPU-accelerated encoding

## Features

| Feature | Status |
|---------|--------|
| Audio-based auto-sync (onset cross-correlation) | ✅ |
| Multi-cam grid composer (2x2, 2x1, 1x2) | ✅ |
| Video/audio analysis (BPM, key, segmentation) | ✅ |
| Proxy workflow (fast editing → final render) | ✅ |
| GPU acceleration (NVIDIA NVENC) | ✅ |
| Social export presets (YouTube, Instagram, TikTok) | ✅ |
| Smart angle switching (beat-aware) | 🚧 |
| GUI (PyQt6) | 🔮 Planned |
| Built-in recording | 🔮 Planned |
| Auto subtitles (Whisper) | 🔮 Planned |

## Architecture

```
src/
├── pipeline.py       # Workflow orchestration
├── analyzer/         # Audio/video analysis (librosa, scenedetect)
├── sync/             # Audio sync engine (onset cross-correlation)
└── composer/         # Video composition (grid, proxy, GPU)
    ├── video_composer.py
    ├── proxy.py
    ├── gpu_accel.py
    └── process_guard.py

cli/
└── main.py           # CLI entry point (click)

archive/
└── experiments/      # Archived experimental scripts
```

## Why GuitarMultiCam?

- **Fast** — Go from raw footage to final video in minutes
- **Smart** — Beat-aware editing cuts on musical transitions
- **Simple** — One command does everything
- **Free** — Open source, no subscriptions

## License

MIT
