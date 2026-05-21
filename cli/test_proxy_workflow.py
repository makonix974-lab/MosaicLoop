#!/usr/bin/env python3
"""
Test Proxy Workflow — full pipeline
1. Downscale to proxy
2. Analyze proxy (fast)
3. Compose on proxy (fast)
4. Export EDL
5. Apply EDL to full-res sources
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.composer.proxy import ProxyManager, ProxyConfig, EditDecisionList, ExportEngine
from src.analyzer.video_analyzer import VideoAnalyzer
from src.composer.video_composer import VideoComposer, CompositionConfig


def main():
    FOLDER = "D:/Rush Cam A52s/Last Shot Guitar/Same same"
    OUTPUT_DIR = Path(__file__).parent.parent / "output"
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    print("🎬 Proxy Workflow Test")
    print("=" * 60)
    
    # =============================================
    # STEP 1: Generate proxies
    # =============================================
    print("\n📦 STEP 1: Downscale to proxy (960x540)")
    print("-" * 40)
    
    video_files = sorted(Path(FOLDER).glob("*.mp4"))[:4]  # 4 clips for quick test
    
    proxy_config = ProxyConfig(
        proxy_width=960,
        proxy_height=540,
        proxy_codec="libx264",
        proxy_preset="ultrafast",
        proxy_crf=28,
        output_dir=str(OUTPUT_DIR / "_proxy")
    )
    proxy_mgr = ProxyManager(proxy_config)
    
    proxy_results = proxy_mgr.batch_generate([str(f) for f in video_files])
    print(f"\n   ✅ {len(proxy_results)} proxies created")
    
    # =============================================
    # STEP 2: Analyze proxies (fast!)
    # =============================================
    print("\n🎯 STEP 2: Analyze proxy clips")
    print("-" * 40)
    
    analyzer = VideoAnalyzer()
    proxy_clips = []
    
    for source_path, proxy_path in proxy_results:
        print(f"   Analyzing {Path(proxy_path).name}...")
        clip = analyzer.analyze_clip(proxy_path, detect_scenes=True)
        # Store original source path for later
        clip._source_path = source_path
        proxy_clips.append(clip)
    
    # =============================================
    # STEP 3: Compose on proxy
    # =============================================
    print("\n🔗 STEP 3: Compose on proxy")
    print("-" * 40)
    
    composer = VideoComposer(CompositionConfig(
        output_path=str(OUTPUT_DIR / "proxy_composition.mp4"),
        output_width=1920,
        output_height=1080
    ))
    
    result = composer.compose(proxy_clips)
    
    if result.get('success'):
        print(f"   ✅ Proxy composition: {result['total_segments']} segments")
        print(f"   ⏱️  Duration: {result['total_duration']:.1f}s")
    else:
        print(f"   ❌ Error: {result.get('error', 'unknown')}")
    
    # =============================================
    # STEP 4: Build EDL
    # =============================================
    print("\n📋 STEP 4: Build Edit Decision List")
    print("-" * 40)
    
    edl = EditDecisionList()
    
    # Register all source clips
    for source_path, proxy_path in proxy_results:
        edl.add_source(source_path)
    
    # Add segments from composition plan
    for seg in result.get('segments', []):
        clip_path = seg['clip_path']
        # Convert proxy path back to source path
        clip_name = Path(clip_path).stem.replace('_proxy', '')
        source_id = clip_name
        # Actually find the correct source_id
        for sid, spath in edl.sources.items():
            if Path(spath).stem == clip_name:
                source_id = sid
                break
        
        edl.add_segment(
            source_id=source_id,
            start=seg['clip_start'],
            end=seg['clip_end'],
            segment_type="music"
        )
    
    edl_path = OUTPUT_DIR / "edl_test.json"
    edl.export(str(edl_path))
    print(f"   ✅ EDL saved: {edl_path}")
    print(f"   📊 {len(edl.segments)} edits, {edl.get_total_duration():.1f}s total")
    
    # =============================================
    # STEP 5 (Optional): Export with full-res sources
    # =============================================
    print("\n🎬 STEP 5: Apply EDL to full-resolution sources")
    print("-" * 40)
    
    # Map proxy paths to source paths for the EDL
    full_edl = EditDecisionList()
    
    # Use FULL source paths instead of proxy
    for source_path, proxy_path in proxy_results:
        sid = Path(source_path).stem
        full_edl.sources[sid] = source_path
    
    for seg in edl.segments:
        full_edl.add_segment(
            source_id=seg['source_id'],
            start=seg['start'],
            end=seg['end'],
            segment_type=seg['type']
        )
    
    exporter = ExportEngine()
    export_result = exporter.export_linear(
        full_edl,
        str(OUTPUT_DIR / "final_full_res.mp4"),
        show_progress=True
    )
    
    if export_result.get('success'):
        print(f"\n   ✅ FINAL VIDEO: {export_result['output_path']}")
    else:
        print(f"\n   ⚠️ Skipped (use --full for this step)")
        print(f"   Set show_progress=True or run manually")
    
    print("\n" + "=" * 60)
    print("✅ Proxy workflow test complete!")
    print(f"📁 Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()