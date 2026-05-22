"""
GuitarMultiCam Studio — Main application window.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtGui import QAction, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QProgressBar, QTextEdit, QLabel,
    QMessageBox, QFileDialog, QMenu, QMenuBar, QStatusBar,
    QFrame,
)

from pipeline import PipelineConfig
from .clip_list import ClipListWidget
from .settings_panel import SettingsPanel
from .workers import PipelineWorker


APP_STYLE = """
QMainWindow { background: #121212; }
QWidget { color: #ddd; font-size: 13px; }
QGroupBox {
    font-weight: bold; border: 1px solid #333;
    border-radius: 6px; margin-top: 10px; padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
}
QPushButton {
    background: #2a5a8a; color: white; border: none;
    padding: 8px 18px; border-radius: 5px; font-weight: bold;
}
QPushButton:hover { background: #3a7aba; }
QPushButton:pressed { background: #1a4a7a; }
QPushButton:disabled { background: #333; color: #666; }
QPushButton#run_btn { background: #2a8a4a; font-size: 15px; }
QPushButton#run_btn:hover { background: #3a9a5a; }
QPushButton#run_btn:disabled { background: #333; color: #666; }
QPushButton#stop_btn { background: #8a2a2a; }
QPushButton#stop_btn:hover { background: #aa3a3a; }
QProgressBar {
    border: 1px solid #333; border-radius: 4px;
    text-align: center; color: white; background: #1a1a1a;
    height: 22px;
}
QProgressBar::chunk { background: #2a8a4a; border-radius: 3px; }
QTextEdit {
    background: #0a0a0a; color: #8f8; border: 1px solid #333;
    border-radius: 4px; font-family: 'Consolas', monospace; font-size: 12px;
}
QComboBox, QSpinBox {
    background: #1a1a1a; color: #ddd; border: 1px solid #444;
    border-radius: 3px; padding: 3px 6px; min-height: 24px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #1a1a1a; color: #ddd; selection-background-color: #2a5a8a;
}
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #555;
    border-radius: 3px; background: #1a1a1a;
}
QCheckBox::indicator:checked { background: #2a8a4a; border-color: #2a8a4a; }
QSplitter::handle { background: #333; width: 2px; }
"""


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self._worker = None
        self._thread = None
        self._setup_ui()
        self._setup_menu()

    def _setup_ui(self):
        self.setWindowTitle("GuitarMultiCam Studio")
        self.setMinimumSize(900, 650)
        self.resize(1100, 750)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)

        # -- Splitter: clips | settings --
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.clip_list = ClipListWidget()
        splitter.addWidget(self.clip_list)

        self.settings = SettingsPanel()
        self.settings.setMaximumWidth(350)
        splitter.addWidget(self.settings)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)

        # -- Run button --
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.run_btn = QPushButton("Run Pipeline")
        self.run_btn.setObjectName("run_btn")
        self.run_btn.setMinimumWidth(200)
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self._run_pipeline)
        btn_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_pipeline)
        btn_row.addWidget(self.stop_btn)

        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        # -- Progress bar --
        self.progress = QProgressBar()
        self.progress.setValue(0)
        main_layout.addWidget(self.progress)

        # -- Log output --
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(180)
        self.log.setPlaceholderText("Pipeline output will appear here...")
        main_layout.addWidget(self.log)

        # -- Status bar --
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        import_action = QAction("&Import Clips...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._menu_import)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        export_action = QAction("&Export...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._menu_export)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        tools_menu = menubar.addMenu("&Tools")
        clean_action = QAction("&Clean Zombie Processes", self)
        clean_action.triggered.connect(self._menu_clean)
        tools_menu.addAction(clean_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._menu_about)
        help_menu.addAction(about_action)

    # -- Menu handlers --

    def _menu_import(self):
        self.clip_list._import_dialog()

    def _menu_export(self):
        if not self.clip_list.paths:
            QMessageBox.warning(self, "No Clips", "Import clips first.")
            return
        self._run_pipeline()

    def _menu_clean(self):
        from composer.process_guard import ProcessGuard
        ProcessGuard.cleanup_stale()
        self._log("[Clean] Zombie processes cleaned")

    def _menu_about(self):
        QMessageBox.about(
            self, "About GuitarMultiCam Studio",
            "GuitarMultiCam Studio v0.1.0\n\n"
            "Auto-edit tool for musicians.\n"
            "Record, sync, and compose multi-cam videos with AI assistance.\n\n"
            "https://github.com/marc/guitarmulticam"
        )

    # -- Pipeline execution --

    def _build_config(self) -> PipelineConfig | None:
        paths = self.clip_list.paths
        if len(paths) < 2:
            QMessageBox.warning(self, "Need More Clips",
                                "Import at least 2 video clips.")
            return None

        settings = self.settings.get_config()
        output = Path(__file__).parent.parent / "output" / "gui_output.mp4"

        return PipelineConfig(
            clips=paths,
            output_path=str(output),
            **settings,
        )

    def _run_pipeline(self):
        config = self._build_config()
        if config is None:
            return

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        self.log.clear()
        self.status.showMessage("Running...")

        self._thread = QThread()
        self._worker = PipelineWorker(config)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.log.connect(self._log)

        self._worker.finished.connect(self._cleanup_thread)
        self._worker.error.connect(self._cleanup_thread)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _stop_pipeline(self):
        if self._worker:
            self._worker.cancel()
            self._log("[Pipeline] Cancelling...")

    def _cleanup_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)

        self._worker = None
        self._thread = None
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.showMessage("Ready")

    def _on_finished(self, result):
        self._log(f"\n[OK] Pipeline completed successfully!")
        self.progress.setValue(100)
        self.status.showMessage("Completed")

        output = result.get("output_path", "")
        if output:
            reply = QMessageBox.question(
                self, "Pipeline Complete",
                f"Video saved to:\n{output}\n\nOpen output folder?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                import subprocess, os
                folder = os.path.dirname(output)
                subprocess.Popen(["explorer", "/select,", os.path.abspath(output)])

    def _on_error(self, msg):
        self._log(f"\n[FAIL] {msg}")
        self.progress.setValue(0)
        self.status.showMessage("Failed")
        QMessageBox.critical(self, "Pipeline Error", msg)

    def _log(self, msg: str):
        self.log.append(msg)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(cursor)


def run_gui():
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
