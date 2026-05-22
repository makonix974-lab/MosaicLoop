# GuitarMultiCam Studio

A small CLI tool that syncs and composes multi-camera video recordings of
musical performances. Drop in N camera angles, get a single grid video
with the audio aligned across all of them.

## Quick Start

```bash
# Install (Python 3.9+)
pip install -r requirements.txt
# Also requires FFmpeg in PATH: https://ffmpeg.org/download.html

# Compose a 2x2 grid from 4 camera angles
python cli/main.py auto --clips cam1.mp4 --clips cam2.mp4 --clips cam3.mp4 --clips cam4.mp4 \
                        --output final.mp4

# Social-media presets
python cli/main.py auto --clips *.mp4 --preset youtube --output yt.mp4
python cli/main.py auto --clips *.mp4 --preset instagram --output ig.mp4
python cli/main.py auto --clips *.mp4 --preset tiktok --output tt.mp4

# Step-by-step variants
python cli/main.py sync     --clips *.mp4 --output offsets.json
python cli/main.py compose  --clips *.mp4 --output grid.mp4 --layout 2x2
python cli/main.py analyze  --clips *.mp4 --output analysis.json

# Disable session cache (force full rebuild)
python cli/main.py auto --clips *.mp4 --no-cache --output final.mp4

# Or launch the minimal GUI (tkinter, ships with Python)
python gui/app.py
```

## Requirements

- Python 3.9+
- FFmpeg in PATH
- NVIDIA GPU (optional) — auto-detected for NVENC encoding

Python dependencies (see `requirements.txt`):
- `numpy`, `librosa` (audio analysis), `click` (CLI)

## What it does

| Feature | Status |
|---|---|
| Audio-based auto-sync (onset cross-correlation) | ✅ |
| Multi-cam grid composer (2×2, 2×1, 1×2, 1×1) | ✅ |
| Single-pass FFmpeg with sync padding inside `filter_complex` | ✅ |
| Parallel proxy generation | ✅ |
| GPU-accelerated encoding (NVIDIA NVENC, Intel QSV) | ✅ |
| Social presets (YouTube 16:9, Instagram 1:1, TikTok 9:16) | ✅ |
| Session cache (skip proxy + sync when inputs unchanged) | ✅ |
| Audio analysis (BPM, onsets, energy segments) | ✅ |

### What this tool does NOT do (yet)

A minimal tkinter GUI is bundled (`python gui/app.py`) — file pickers,
preset selector, log panel, no preview yet. A richer GUI (preview +
waveform + manual offset adjustment) is still on the roadmap. Built-in
recording, auto subtitles, and "smart" angle switching aren't on the
active roadmap.
The v0.1 prototypes for those are preserved under `archive/v0.1/` for
reference but aren't maintained.

## Architecture

```
src/
├── pipeline.py          Workflow orchestration (3 steps: proxy → sync → compose)
├── cache.py             Session cache (input fingerprints + cached proxies)
├── models.py            Clip + ClipMetadata dataclasses
├── analyzer/            Audio feature extraction (BPM, onsets, energy)
├── sync/                Audio sync engine (onset cross-correlation)
├── composer/            Video composition (grid, proxy, GPU detect)
└── utils/ffmpeg_run.py  Single FFmpeg helper with progress + timeout

cli/main.py              CLI entry point (click)
tests/                   Unit + integration tests (pytest)
archive/                 v0.1 modules kept for reference
```

See `docs/ARCHITECTURE.md` for the data flow.

## Pipeline

```
inputs[]
  ├─→ [1/3] proxy generation (parallel, optional, cached)
  ├─→ [2/3] audio sync (cached)
  └─→ [3/3] compose grid (single FFmpeg pass)
        └─ output.mp4
```

The third step injects per-clip time pads directly into the
`filter_complex` graph (`tpad` for video, `adelay` for audio), so there
are no intermediate "synced clip" files on disk.

## Tests

```bash
pytest tests/                                  # 40 tests
pytest tests/ --cov=src --cov-report=term      # with coverage
```

Synthetic fixtures (a click track sliced into 4 windows with known offsets)
are auto-generated on first run via `tests/conftest.py`.

## License

MIT
