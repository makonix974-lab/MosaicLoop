"""
Pytest configuration — auto-generates synthetic fixtures if missing
so the integration tests are runnable from a fresh clone without
manual setup.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"
GENERATOR = FIXTURES_DIR / "_generate_fixtures.py"
REQUIRED_FILES = ["clip_a.mp4", "clip_b.mp4", "clip_c.mp4", "clip_d.mp4", "offsets.json"]


def _fixtures_present() -> bool:
    return all((FIXTURES_DIR / f).exists() for f in REQUIRED_FILES)


def pytest_configure(config):
    """Generate synthetic fixtures on first run if missing."""
    if _fixtures_present():
        return
    print("\n[conftest] Fixtures missing, generating...")
    result = subprocess.run(
        [sys.executable, str(GENERATOR)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"[conftest] Fixture generation failed:\n{result.stderr}")
    else:
        print("[conftest] Fixtures ready")
