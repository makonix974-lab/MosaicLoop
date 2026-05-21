# GuitarMultiCam Studio

**Auto-edit tool for musicians** — Record, sync, and compose multi-cam videos with AI assistance.

## Features

- 🎸 **Audio-based auto-sync** — Align clips by audio fingerprinting
- 🎬 **Multi-cam composer** — Grid layouts (2x2, side-by-side, PIP, custom)
- 🎤 **Built-in recording** — Countdown + clap for perfect sync (future)
- 📝 **Auto subtitles** — Whisper integration
- 📱 **Cross-platform** — Desktop (Windows/Linux/macOS), Android later

## Architecture

```
src/
├── sync/        # Audio sync engine (cross-correlation)
├── composer/    # Video grid builder (FFmpeg)
├── record/      # Capture module (future)
└── export/       # Render pipeline

cli/             # Command-line tools
gui/             # PyQt6 interface (future)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Sync clips to master audio
python cli/sync.py --master track.wav --clips cam1.mp4 cam2.mp4

# Compose grid
python cli/compose.py --clips cam1.mp4 cam2.mp4 --layout 2x2 --output final.mp4
```

## Requirements

- Python 3.9+
- FFmpeg (in PATH or bundled)
- CUDA (optional, for faster processing)

## License

TBD — Opensource planned
