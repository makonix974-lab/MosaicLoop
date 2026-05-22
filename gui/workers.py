"""
Background workers for non-blocking pipeline execution.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PyQt6.QtCore import QObject, pyqtSignal

from pipeline import Pipeline, PipelineConfig


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
        try:
            pipeline = Pipeline(self.config)
            self.log.emit("[Pipeline] Starting...")
            self.progress.emit(0, "Initializing")

            # Override print to capture logs
            import builtins
            original_print = builtins.print

            def capture_print(*args, **kwargs):
                msg = " ".join(str(a) for a in args)
                self.log.emit(msg)
                original_print(*args, **kwargs)

            builtins.print = capture_print

            result = pipeline.run()

            builtins.print = original_print

            if self._cancelled:
                self.log.emit("[Pipeline] Cancelled by user")
                return

            if result.get("success"):
                self.progress.emit(100, "Done")
                self.log.emit(f"[OK] Finished -> {result.get('output_path', '')}")
                self.finished.emit(result)
            else:
                err = result.get("error", "Unknown error")
                self.log.emit(f"[FAIL] {err}")
                self.error.emit(err)

        except Exception as e:
            self.log.emit(f"[ERROR] {e}")
            self.error.emit(str(e))
