#!/usr/bin/env python3
"""
GPU detection and acceleration for FFmpeg.
Détecte NVIDIA/Intel GPU et active l'accélération matérielle.
"""

import subprocess
import os
import json


def detect_gpu() -> dict:
    """
    Detect available GPU and return FFmpeg optimal params.
    
    Returns:
        dict with:
        - 'available': bool
        - 'name': str (GPU name)
        - 'decoder': str (hwaccel method)
        - 'encoder': str (video codec)
        - 'encoder_preset': str
        - 'scale_filter': str (GPU-accelerated scale filter)
    """
    result = {
        'available': False,
        'name': 'CPU',
        'decoder': 'none',
        'encoder': 'libx264',
        'encoder_preset': 'medium',
        'scale_filter': 'scale',
        'reason': ''
    }
    
    # Check NVIDIA
    try:
        nv = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=5
        )
        if nv.returncode == 0 and nv.stdout.strip():
            gpu_name = nv.stdout.strip().split(',')[0].strip()
            result['available'] = True
            result['name'] = f"NVIDIA {gpu_name}"
            result['decoder'] = 'cuda'
            result['encoder'] = 'h264_nvenc'
            result['encoder_preset'] = 'p7'  # Best quality NVENC preset (Turing+)
            result['scale_filter'] = 'scale_cuda'
            result['reason'] = f"NVIDIA GPU détecté ({gpu_name})"
            
            # Verify FFmpeg has NVENC support
            check = subprocess.run(
                ['ffmpeg', '-encoders'], capture_output=True, text=True, timeout=5
            )
            if 'h264_nvenc' not in check.stdout:
                result['available'] = False
                result['reason'] = "FFmpeg sans support NVENC"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Check Intel QuickSync
    try:
        check = subprocess.run(
            ['ffmpeg', '-encoders'], capture_output=True, text=True, timeout=5
        )
        if 'h264_qsv' in check.stdout:
            result['available'] = True
            result['name'] = 'Intel QSV'
            result['decoder'] = 'qsv'
            result['encoder'] = 'h264_qsv'
            result['encoder_preset'] = 'medium'
            result['scale_filter'] = 'scale_qsv'
            result['reason'] = "Intel QuickSync détecté"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    result['reason'] = 'Aucun GPU compatible trouvé'
    return result


def gpu_available() -> bool:
    """Quick check if GPU acceleration is available."""
    info = detect_gpu()
    return info['available']


def add_hwaccel(cmd: list, gpu_info: dict, input_index: int = 0) -> list:
    """
    Add hardware acceleration flags to an FFmpeg command.
    
    Args:
        cmd: FFmpeg command list
        gpu_info: Result from detect_gpu()
        input_index: Index of input to accelerate
    
    Returns:
        Modified command with hwaccel flags
    """
    if not gpu_info['available'] or gpu_info['decoder'] == 'none':
        return cmd
    
    dec = gpu_info['decoder']
    
    if dec == 'cuda':
        # Insert hwaccel after -i flags
        new_cmd = cmd[:2]  # ffmpeg -y
        new_cmd += ['-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda']
        new_cmd += cmd[2:]  # rest of command
        return new_cmd
    elif dec == 'qsv':
        new_cmd = cmd[:2]
        new_cmd += ['-hwaccel', 'qsv', '-hwaccel_output_format', 'qsv']
        new_cmd += cmd[2:]
        return new_cmd
    
    return cmd


# Auto-detect at module load
GPU_INFO = detect_gpu()
if GPU_INFO['available']:
    print(f"   🚀 GPU: {GPU_INFO['name']} — {GPU_INFO['encoder']} disponible")
else:
    print(f"   💻 CPU mode: {GPU_INFO['reason']}")


if __name__ == "__main__":
    info = detect_gpu()
    print(f"GPU: {info['name']}")
    print(f"Disponible: {info['available']}")
    print(f"Encodeur: {info['encoder']}")
    print(f"Preset: {info['encoder_preset']}")
    print(f"Décodeur: {info['decoder']}")
    print(f"Filtre scale: {info['scale_filter']}")
