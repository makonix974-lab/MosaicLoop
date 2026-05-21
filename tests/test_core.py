"""Test suite for GuitarMultiCam Studio."""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sync.audio_sync import SyncManager
from composer.video_composer import VideoComposer, CompositionConfig
from composer.proxy import ProxyManager, ProxyConfig
from composer.gpu_accel import detect_gpu, GPU_INFO


def test_imports():
    """All modules import without error."""
    from sync import audio_sync
    from composer import video_composer, proxy, gpu_accel, process_guard
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


def test_cli_help():
    """CLI --help works."""
    result = subprocess.run(
        [sys.executable, "cli/main.py", "--help"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    assert "auto" in result.stdout
    assert "sync" in result.stdout
    assert "compose" in result.stdout
    assert "analyze" in result.stdout
    print("  [OK] CLI --help works (commands: auto, sync, compose, analyze)")


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
        test_cli_help,
        test_cli_auto_help,
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
