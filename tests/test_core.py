"""Test suite for GuitarMultiCam Studio."""

import json
import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sync.audio_sync import SyncManager
from composer.video_composer import VideoComposer, CompositionConfig
from composer.smart_composer import SmartComposer, SmartSegment
from composer.proxy import ProxyManager, ProxyConfig
from composer.gpu_accel import detect_gpu, GPU_INFO
from pipeline import Pipeline, PipelineConfig, load_config


def test_imports():
    """All modules import without error."""
    from sync import audio_sync
    from composer import video_composer, smart_composer, proxy, gpu_accel, process_guard
    from analyzer import video_analyzer
    print("  [OK] All modules imported")


def test_gpu_detect():
    """GPU detection returns consistent result."""
    info = detect_gpu()
    assert "available" in info
    assert "name" in info
    assert info["available"] == GPU_INFO["available"]
    print(f"  [OK] GPU: {info['name']} (avail={info['available']})")


def test_proxy_config():
    """ProxyConfig defaults are sensible."""
    cfg = ProxyConfig()
    assert cfg.proxy_width == 960
    assert cfg.proxy_height == 540
    assert cfg.proxy_crf == 28
    print("  [OK] ProxyConfig defaults OK")


def test_composition_config():
    """CompositionConfig defaults are sensible."""
    cfg = CompositionConfig()
    assert cfg.output_width == 1920
    assert cfg.output_height == 1080
    assert cfg.grid_cols == 2
    assert cfg.grid_rows == 2
    print("  [OK] CompositionConfig defaults OK")


def test_sync_manager_init():
    """SyncManager initializes without error."""
    mgr = SyncManager()
    assert mgr is not None
    print("  [OK] SyncManager init OK")


def test_composer_init():
    """VideoComposer initializes without error."""
    composer = VideoComposer()
    assert composer is not None
    print("  [OK] VideoComposer init OK")


def test_smart_composer_init():
    """SmartComposer initializes without error."""
    composer = SmartComposer()
    assert composer is not None
    assert composer.config is not None
    print("  [OK] SmartComposer init OK")


def test_smart_segment():
    """SmartSegment dataclass works."""
    seg = SmartSegment(
        clip_path="/test/clip.mp4",
        clip_name="clip.mp4",
        start=0.0,
        end=10.0,
        segment_type="music",
        energy=0.8,
        beat_aligned=True,
        bars=4,
    )
    assert seg.clip_name == "clip.mp4"
    assert seg.end - seg.start == 10.0
    print("  [OK] SmartSegment works")


def test_pipeline_config_defaults():
    """PipelineConfig defaults are sensible."""
    cfg = PipelineConfig()
    assert cfg.smart is False
    assert cfg.style == "auto"
    assert cfg.trim_silence is True
    assert cfg.layout == "2x2"
    print("  [OK] PipelineConfig defaults OK")


def test_pipeline_config_merge():
    """Pipeline merges config from dict."""
    cfg = PipelineConfig()
    pipeline = Pipeline(cfg)
    pipeline._merge_config({"smart": True, "style": "dynamic", "preset": "youtube"})
    assert cfg.smart is True
    assert cfg.style == "dynamic"
    assert cfg.preset == "youtube"
    print("  [OK] Pipeline config merge OK")


def test_load_json_config():
    """load_config reads JSON files."""
    data = {"smart": True, "style": "dynamic", "output_width": 1920}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    result = load_config(path)
    Path(path).unlink(missing_ok=True)
    assert result.get("smart") is True
    assert result.get("style") == "dynamic"
    print("  [OK] load_config JSON works")


def test_cli_help():
    """CLI --help works."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "--help"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    for cmd in ["auto", "smart", "sync", "compose", "analyze", "config", "clean"]:
        assert cmd in result.stdout
    print("  [OK] CLI --help shows all commands")


def test_cli_auto_help():
    """CLI auto --help shows options."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "auto", "--help"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    assert "--clips" in result.stdout
    assert "--preset" in result.stdout
    print("  [OK] CLI auto --help works")


def test_cli_smart_help():
    """CLI smart --help shows options."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "smart", "--help"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    assert "--style" in result.stdout
    assert "--trim-silence" in result.stdout
    print("  [OK] CLI smart --help works")


def test_cli_config_template():
    """CLI config --template prints template."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "config", "--template"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    assert "output_path" in result.stdout
    assert "layout" in result.stdout
    assert "clips" in result.stdout
    print("  [OK] CLI config --template works")


if __name__ == "__main__":
    print("=" * 50)
    print("GuitarMultiCam Studio - Test Suite")
    print("=" * 50)

    tests = [
        test_imports,
        test_gpu_detect,
        test_proxy_config,
        test_composition_config,
        test_sync_manager_init,
        test_composer_init,
        test_smart_composer_init,
        test_smart_segment,
        test_pipeline_config_defaults,
        test_pipeline_config_merge,
        test_load_json_config,
        test_cli_help,
        test_cli_auto_help,
        test_cli_smart_help,
        test_cli_config_template,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'=' * 50}")
