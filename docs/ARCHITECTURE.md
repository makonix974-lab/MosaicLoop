# Architecture

## Data flow

```
                  ┌──────────────────────┐
   inputs[].mp4 ──┤   PipelineConfig     │
                  └──────────────────────┘
                            │
                            ▼
                  ┌──────────────────────┐
                  │   SessionCache load  │     ← <output_dir>/.session.json
                  │   (fingerprints)     │
                  └──────────┬───────────┘
                             │
              ┌──────────────┴───────────────┐
              │                              │
        cache miss                       cache hit
              │                              │
              ▼                              ▼
    ┌──────────────────┐            ┌──────────────────┐
    │ [1/3] Proxy      │            │ Reuse proxies    │
    │  ProxyManager    │            └──────────────────┘
    │  parallel,       │                       │
    │  GPU-accel       │                       │
    └────────┬─────────┘                       │
             │                                 │
             └────────────┬────────────────────┘
                          │
                          ▼
                ┌──────────────────┐
                │ [2/3] Audio Sync │
                │  SyncManager     │
                │  (onset xcorr)   │
                └────────┬─────────┘
                         │
                         ▼
                ┌────────────────────┐
                │  Save SessionCache │
                └──────────┬─────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ [3/3] Compose Grid   │
                │  VideoComposer       │
                │  filter_complex:     │
                │   tpad + adelay      │
                │   scale + crop       │
                │   hstack + vstack    │
                │  Single FFmpeg pass  │
                └──────────┬───────────┘
                           │
                           ▼
                       output.mp4
```

## Module responsibilities

| Module | Purpose |
|---|---|
| `pipeline.py` | Orchestrates the 3 steps, owns SessionCache lifecycle |
| `cache.py` | Persists input fingerprints (size + mtime) + proxies + sync result |
| `models.py` | `Clip`, `ClipMetadata` — single canonical data type |
| `sync/audio_sync.py` | `SyncManager.align_clips` — onset envelope cross-correlation |
| `composer/proxy.py` | `ProxyManager` — parallel low-res transcode, GPU-aware |
| `composer/video_composer.py` | `VideoComposer.compose_grid(pad_seconds=...)` — single-pass grid render |
| `composer/gpu_accel.py` | NVENC / QSV detection at module load |
| `composer/process_guard.py` | Stale FFmpeg cleanup at startup |
| `utils/ffmpeg_run.py` | Single canonical `run_ffmpeg(...)` with progress, timeout, stderr-to-tempfile |
| `analyzer/video_analyzer.py` | Audio feature extraction (BPM, onsets, energy) — used only by `analyze` CLI |

## Why a single FFmpeg pass for the grid

In v0.1 the pipeline had four steps:
1. proxy
2. sync
3. **apply_offsets** — produced per-clip MP4s in `output/_synced/`
4. compose_grid

Step 3 was responsible for adding leading pad to align the clips. It used
`filter_complex` with `concat`, which:
- created intermediate files (up to 1.7 GB on real rushes)
- doubled the encoding work (encode pad+clip, then re-encode in step 4)
- was prone to FFmpeg hangs (the bug that triggered this refactor)

In v0.2, padding lives inside the grid's `filter_complex`:
```
[0:v]tpad=start_duration=0.700:start_mode=add:color=black,scale=...,crop=...[v0]
[1:v]                                          scale=...,crop=...[v1]
[v0][v1]hstack=inputs=2[row0]
[row0]copy[grid]
[0:a]adelay=700|700[aout]    # only when audio source is padded
```

One FFmpeg invocation. Zero intermediate files on disk. ~30% faster on
synthetic fixtures, ~50% faster on long real-world rushes.

## Cache strategy

`<output_dir>/.session.json`:
```json
{
  "version": 1,
  "fingerprints": {
    "cam1.mp4": {"name": "cam1.mp4", "size": 1234567, "mtime": 1700000000.123}
  },
  "proxies": { "cam1.mp4": "/path/to/_proxy/cam1_proxy.mp4" },
  "alignment": {
    "offsets": {"cam1.mp4": 0.0, "cam2.mp4": 1.509},
    "confidence": 1.0,
    "reference_id": "cam1.mp4"
  }
}
```

Cache is invalidated when:
- Input list size changes
- Any input file's size or mtime differs (>1 ms)
- Schema version mismatch
- Cache file missing or unparseable
- Any cached proxy file missing or under 1 KB

## Stderr deadlock fix (the v0.1 hang)

v0.1 had four `subprocess.Popen(..., stderr=subprocess.PIPE, ...)` callsites
that never drained stderr until after the process exited. Once FFmpeg
filled the OS pipe buffer (~64 KB), it blocked. The Python loop was
waiting on `process.poll()`, which never went non-`None`. Classic deadlock.

v0.2 redirects stderr to a tempfile via the unified `run_ffmpeg` helper.
Stderr is read only when `returncode != 0`. Files are cleaned up in `finally`.
