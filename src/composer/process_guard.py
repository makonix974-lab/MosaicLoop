#!/usr/bin/env python3
"""
Process Guard — track & kill orphaned encoding processes.
Évite les zombies FFmpeg qui traînent après un kill.
"""

import os
import signal
import json
import subprocess
import atexit
from pathlib import Path

LOCK_DIR = Path(__file__).parent.parent / ".process_guard"
LOCK_DIR.mkdir(exist_ok=True)
LOCK_FILE = LOCK_DIR / "active_pids.json"


class ProcessGuard:
    """
    Track encoding processes so we can clean them up.
    Use as a context manager or decorator.
    """
    
    def __init__(self, name: str = "encoding"):
        self.name = name
        self._pids = []
    
    @staticmethod
    def load_pids() -> dict:
        """Load tracked PIDs from lock file."""
        if LOCK_FILE.exists():
            try:
                with open(LOCK_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}
    
    @staticmethod
    def save_pids(pids: dict):
        """Save tracked PIDs to lock file."""
        LOCK_FILE.parent.mkdir(exist_ok=True)
        with open(LOCK_FILE, 'w') as f:
            json.dump(pids, f, indent=2)
    
    @staticmethod
    def is_pid_alive(pid: int) -> bool:
        """Check if a PID is still running (Windows-compatible)."""
        if os.name == 'nt':
            try:
                result = subprocess.run(
                    ['tasklist', '//FI', f'PID eq {pid}', '//FO', 'CSV'],
                    capture_output=True, text=True, timeout=5, errors='replace'
                )
                # If tasklist returns a line with the PID, it's alive
                return str(pid) in (result.stdout or '')
            except (subprocess.TimeoutExpired, OSError):
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    
    @staticmethod
    def cleanup_stale():
        """
        Find and kill all stale encoding processes.
        Hunt both by PID (tracked) and by process name (FFmpeg).
        
        Returns: list of killed PIDs
        """
        killed = []
        
        # 1. Kill tracked PIDs
        pids = ProcessGuard.load_pids()
        for name, pid in pids.items():
            if ProcessGuard.is_pid_alive(pid):
                print(f"   ⚠️  Zombie: {name} (PID {pid}) — kill...")
                ProcessGuard.kill_pid(pid, force=True)
                killed.append((name, pid))
        
        # 2. Hunt down any remaining FFmpeg processes
        if os.name == 'nt':
            try:
                result = subprocess.run(
                    ['tasklist', '/FO', 'CSV', '//FI', 'IMAGENAME eq ffmpeg.exe'],
                    capture_output=True, text=True, timeout=10, errors='replace'
                )
                out = result.stdout or ''
                for line in out.split('\n')[1:]:
                    if 'ffmpeg' in line.lower():
                        parts = line.split(',')
                        if len(parts) >= 2:
                            pid_str = parts[1].strip().strip('"')
                            if pid_str.isdigit():
                                pid = int(pid_str)
                                print(f"   ⚠️  FFmpeg errant: PID {pid} — kill...")
                                ProcessGuard.kill_pid(pid, force=True)
                                killed.append(('ffmpeg', pid))
            except (subprocess.TimeoutExpired, OSError):
                pass
        else:
            try:
                result = subprocess.run(
                    ['pgrep', 'ffmpeg'], capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.strip().split('\n'):
                    if line.strip().isdigit():
                        pid = int(line.strip())
                        print(f"   ⚠️  FFmpeg errant: PID {pid} — kill...")
                        ProcessGuard.kill_pid(pid, force=True)
                        killed.append(('ffmpeg', pid))
            except (subprocess.TimeoutExpired, OSError):
                pass
        
        if killed:
            print(f"   ✅ {len(killed)} processus nettoyé(s)")
        else:
            print("   ✅ Aucun zombie")
        
        # Clear lock file
        ProcessGuard.save_pids({})
        return killed

    @staticmethod
    def kill_pid(pid: int, force: bool = False):
        """Kill a process by PID - kills entire tree on Windows."""
        try:
            if os.name == 'nt':  # Windows
                flags = '/F' if force else '/T'
                subprocess.run(
                    ['taskkill', flags, '/T', '/PID', str(pid)],  # /T kills tree
                    capture_output=True, timeout=5
                )
            else:
                sig = signal.SIGKILL if force else signal.SIGTERM
                # Kill process group
                os.killpg(os.getpgid(pid), sig)
        except (OSError, subprocess.TimeoutExpired, ProcessLookupError):
            pass
    
    def track(self, pid: int, name: str = None):
        """Track a new process."""
        name = name or self.name
        pids = self.load_pids()
        pids[name] = pid
        self.save_pids(pids)
        self._pids.append(pid)
        return pid
    
    def untrack(self, pid: int):
        """Remove a process from tracking (when it finishes normally)."""
        pids = self.load_pids()
        to_remove = [k for k, v in pids.items() if v == pid]
        for k in to_remove:
            del pids[k]
        self.save_pids(pids)
    
    def run_ffmpeg(self, cmd: list, name: str = None, **kwargs) -> subprocess.Popen:
        """
        Run FFmpeg with process tracking.
        Simple: track PID, let caller handle wait/untrack.
        """
        process = subprocess.Popen(cmd, **kwargs)
        self.track(process.pid, name or "ffmpeg")
        return process


# Auto-cleanup on Python exit
@atexit.register
def _cleanup_on_exit():
    """Cleanup when Python exits normally or via SIGTERM."""
    pids = ProcessGuard.load_pids()
    for name, pid in pids.items():
        if ProcessGuard.is_pid_alive(pid):
            ProcessGuard.kill_pid(pid, force=True)


def signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT by cleaning up children first."""
    print(f"\n   ⚠️  Signal {signum} reçu, nettoyage...")
    ProcessGuard.cleanup_stale()
    exit(128 + signum)


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# =============================================
# Simple CLI for manual cleanup
# =============================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        print("🔍 Nettoyage des processus zombies...")
        killed = ProcessGuard.cleanup_stale()
        
        # Also look for any ffmpeg processes
        import subprocess
        if os.name == 'nt':
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq ffmpeg.exe', '/FO', 'CSV'],
                capture_output=True, text=True
            )
            out = result.stdout or ''
            if 'ffmpeg' in out.lower():
                print("   🧟 FFmpeg processes still running:")
                for line in out.split('\n')[1:]:
                    if 'ffmpeg' in line.lower():
                        print(f"      {line.strip()}")
                print("   Run: taskkill /F /IM ffmpeg.exe")
        else:
            result = subprocess.run(
                ['pgrep', '-a', 'ffmpeg'], capture_output=True, text=True
            )
            if result.stdout.strip():
                print(f"   🧟 FFmpeg encore en vie:\n{result.stdout}")
        
        if not killed:
            print("   ✅ Rien à nettoyer")
    else:
        print("Usage: python process_guard.py clean")