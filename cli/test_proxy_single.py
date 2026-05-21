#!/usr/bin/env python3
"""Debug proxy downscale only"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.composer.proxy import ProxyManager, ProxyConfig

FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
proxy_mgr = ProxyManager(ProxyConfig(
    proxy_width=960, proxy_height=540,
    proxy_preset="ultrafast", proxy_crf=28
))

# Test single file first
test_file = f"{FOLDER}/20251109_172852.mp4"
print(f"Testing proxy generation for: {test_file}")
result = proxy_mgr.generate_proxy(test_file)
print(f"Result: {result}")
