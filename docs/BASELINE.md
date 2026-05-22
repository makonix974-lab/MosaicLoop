# Baseline Metrics — v0.1 (start of refactor)

Captured: start of `refactor/v0.2-slim` branch
Branch base: `master` @ `4e49d87` (with morning fixes: apply_offsets timeouts, stderr deadlock in compose_grid, FPS lock at output)

---

## Pipeline runtime — synthetic fixtures (4 clips, 5s @ 320x240)

| Metric | v0.1 | Target v0.2 |
|---|---|---|
| Total runtime | **3.67 s** | < 2.5 s |
| Output size | 1.91 MB | unchanged |
| Intermediate files | **4** | **0** |
| Intermediate size | 0.23 MB | 0 |

Captured via `python tests/_baseline_capture.py`.

## Pipeline runtime — real rushes (4 clips, ~200s @ 1080p)

| Metric | v0.1 | Target v0.2 |
|---|---|---|
| Total runtime | **~11 s** (with proxies cached) | < 6 s |
| Final output | 1920x1080, 200s, h264+aac | unchanged |
| Intermediate (proxies + synced) | ~50 MB | proxies only |

## Code metrics

| Area | LOC v0.1 | Target v0.2 |
|---|---|---|
| `src/sync` | 290 | 290 (untouched) |
| `src/composer` | 1657 | ~600 (drop smart_composer, slim proxy) |
| `src/analyzer` | 1143 | ~250 (audio essentials only) |
| `src/pipeline.py` | 293 | ~200 |
| `cli` | 545 | ~350 |
| `gui` | 556 | archived (rebuild in v0.3) |
| `tests` | 459 | 600+ (real coverage) |
| **Total active src+cli** | **~3700** | **< 1800** |

## Bug surface

| Issue | Count v0.1 | Target v0.2 |
|---|---|---|
| `stderr=subprocess.PIPE` callsites in long-running FFmpeg Popen | **3** (proxy.py:105, video_composer.py:278, smart_composer.py:390) | 0 |
| Inline `class ClipWrap` definitions | **3** (pipeline.py:292, cli/main.py:195, cli/test_full_pipeline.py:78) | 0 (single `Clip` model) |
| Progress-monitoring loop duplications | 4 | 1 (helper) |

## Test integrity

| Metric | v0.1 | Target v0.2 |
|---|---|---|
| Real integration tests | 0 | ≥ 4 |
| Coverage on `sync/audio_sync.py` | unknown | ≥ 90% |
| Overall coverage | unknown | ≥ 60% |

## Test fixtures

Synthetic clips at `tests/fixtures/`:
- `clip_a.mp4` — window 0.0s–5.0s of common click track (reference)
- `clip_b.mp4` — window 1.5s–6.5s (expected offset: +1.500s)
- `clip_c.mp4` — window 0.7s–5.7s (expected offset: +0.700s)
- `clip_d.mp4` — window 2.2s–7.2s (expected offset: +2.200s)
- `offsets.json` — ground truth + tolerance (±100ms)

Common track: 10s of irregular click pulses (decaying 880Hz sines) at
[0.43, 1.27, 2.81, 3.55, 5.12, 6.04, 7.39, 8.66, 9.18] seconds.

Regenerate with: `python tests/fixtures/_generate_fixtures.py`

## Integration tests passing on baseline

```
tests/test_integration.py::test_sync_offsets_within_tolerance PASSED
tests/test_integration.py::test_pipeline_2clips_grid_2x1     PASSED
tests/test_integration.py::test_pipeline_4clips_grid_2x2     PASSED
3 passed in 6.05s
```

These three tests are the **safety net**. Every refactor phase must keep
them green before commit.
