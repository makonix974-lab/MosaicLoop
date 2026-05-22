"""
Background workers for non-blocking pipeline execution.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PyQt6.QtCore import QObject, pyqtSignal

from pipeline import Pipeline, PipelineConfig
from composer.process_guard import ProcessGuard


class CaptureStdout(io.StringIO):
    """Redirects stdout writes to a Qt signal."""

    def __init__(self, signal):
        super().__init__()
        self._signal = signal

    def write(self, text):
        if text.strip():
            self._signal.emit(text.rstrip())
        super().write(text)


class PipelineWorker(QObject):
    """Runs the pipeline in a background thread."""

    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, config: PipelineConfig):
        super().__init__()
        self.config = config
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        old_stdout = sys.stdout
        try:
            ProcessGuard.cleanup_stale()
            self.log.emit("[Pipeline] Starting...")

            pipeline = Pipeline(self.config)
            sys.stdout = CaptureStdout(self.log)

            result = pipeline.run()

            if self._cancelled:
                self.log.emit("[Pipeline] Cancelled by user")
                return

            if result.get("success"):
                self.progress.emit(100, "Done")
                path = result.get("output_path", "")
                self.log.emit(f"[OK] Finished -> {path}")
                self.finished.emit(result)
            else:
                err = result.get("error", "Unknown error")
                self.log.emit(f"[FAIL] {err}")
                self.error.emit(err)

        except Exception as e:
            self.log.emit(f"[ERROR] {e}")
            self.error.emit(str(e))
        finally:
            sys.stdout = old_stdout
