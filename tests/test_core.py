"""Unit tests for v0.2 — pruned to active modules only.

Module-level imports + config defaults + CLI help. Heavy integration
behavior lives in tests/test_integration.py.
"""

import json
import sys
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def test_imports():
    """All active modules import without error."""
    from sync import audio_sync  # noqa: F401
    from composer import video_composer, proxy, gpu_accel, process_guard  # noqa: F401
    from analyzer import video_analyzer  # noqa: F401
    from utils import ffmpeg_run  # noqa: F401


def test_gpu_detect():
    """GPU detection returns a dict with required keys."""
    from composer.gpu_accel import detect_gpu, GPU_INFO
    info = detect_gpu()
    assert "available" in info
    assert "name" in info
    assert info["available"] == GPU_INFO["available"]


def test_proxy_config_defaults():
    """ProxyConfig defaults are sensible."""
    from composer.proxy import ProxyConfig
    cfg = ProxyConfig()
    assert cfg.proxy_width == 960
    assert cfg.proxy_height == 540
    assert cfg.proxy_crf == 28


def test_composition_config_defaults():
    """CompositionConfig defaults are sensible."""
    from composer.video_composer import CompositionConfig
    cfg = CompositionConfig()
    assert cfg.output_width == 1920
    assert cfg.output_height == 1080
    assert cfg.grid_cols == 2
    assert cfg.grid_rows == 2


def test_pipeline_config_defaults():
    """PipelineConfig defaults are sensible (post-P3: no smart fields)."""
    from pipeline import PipelineConfig
    cfg = PipelineConfig()
    assert cfg.layout == "2x2"
    assert cfg.use_proxy is True
    assert not hasattr(cfg, "smart")
    assert not hasattr(cfg, "style")


def test_pipeline_config_merge():
    """Pipeline merges config from dict."""
    from pipeline import Pipeline, PipelineConfig
    cfg = PipelineConfig()
    pipeline = Pipeline(cfg)
    pipeline._merge_config({"preset": "youtube", "output_fps": 60})
    assert cfg.preset == "youtube"
    assert cfg.output_fps == 60


def test_load_json_config():
    """load_config reads JSON files."""
    from pipeline import load_config
    data = {"preset": "youtube", "output_width": 1920}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        result = load_config(path)
        assert result.get("preset") == "youtube"
    finally:
        Path(path).unlink(missing_ok=True)


def test_cli_help():
    """CLI --help works and lists active commands only (no smart, no gui)."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "--help"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0
    for cmd in ["auto", "sync", "compose", "analyze", "config", "clean"]:
        assert cmd in result.stdout, f"missing command: {cmd}"
    # Removed in P3
    assert "smart" not in result.stdout
    assert "gui " not in result.stdout


def test_cli_auto_help():
    """CLI auto --help shows --clips and --preset."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "auto", "--help"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0
    assert "--clips" in result.stdout
    assert "--preset" in result.stdout


def test_cli_config_template():
    """CLI config --template prints template."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "config", "--template"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0
    assert "output_path" in result.stdout
    assert "layout" in result.stdout
    # smart fields should be gone
    assert "smart:" not in result.stdout
    assert "style:" not in result.stdout


def test_ffmpeg_run_helper_exists():
    """The unified FFmpeg runner is importable and exposes the public API."""
    from utils.ffmpeg_run import run_ffmpeg, FFmpegResult
    assert callable(run_ffmpeg)
    r = FFmpegResult(success=True, returncode=0, stderr="", elapsed=0.1)
    assert r.success is True
