"""
Settings panel for pipeline configuration.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QSpinBox, QCheckBox, QLabel, QPushButton,
)


class SettingsPanel(QWidget):
    """Configuration panel for the pipeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # -- Mode group --
        mode_group = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_group)

        self.smart_check = QCheckBox("Smart editing (AI-driven camera switching)")
        self.smart_check.setToolTip("Analyze audio and switch cameras intelligently")
        mode_layout.addWidget(self.smart_check)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["auto", "dynamic", "stable"])
        self.style_combo.setToolTip("auto=balanced, dynamic=frequent cuts, stable=long takes")
        style_row.addWidget(self.style_combo, 1)
        style_row.addStretch()
        mode_layout.addLayout(style_row)

        layout.addWidget(mode_group)

        # -- Layout group --
        layout_group = QGroupBox("Layout & Presets")
        form = QFormLayout(layout_group)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Custom", "youtube", "instagram", "tiktok"])
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        form.addRow("Preset:", self.preset_combo)

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["2x2", "1x1", "2x1", "1x2"])
        form.addRow("Grid:", self.layout_combo)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(640, 3840)
        self.width_spin.setValue(1920)
        self.width_spin.setSingleStep(2)
        form.addRow("Width:", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(480, 2160)
        self.height_spin.setValue(1080)
        self.height_spin.setSingleStep(2)
        form.addRow("Height:", self.height_spin)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(24, 60)
        self.fps_spin.setValue(30)
        form.addRow("FPS:", self.fps_spin)

        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 51)
        self.crf_spin.setValue(23)
        self.crf_spin.setToolTip("Quality (lower=better, 18-28)")
        form.addRow("CRF:", self.crf_spin)

        layout.addWidget(layout_group)

        # -- Audio group --
        audio_group = QGroupBox("Audio")
        audio_form = QFormLayout(audio_group)

        self.audio_source_spin = QSpinBox()
        self.audio_source_spin.setRange(0, 10)
        self.audio_source_spin.setValue(0)
        self.audio_source_spin.setToolTip("Index of clip to use as audio source")
        audio_form.addRow("Source clip:", self.audio_source_spin)

        self.trim_check = QCheckBox("Auto-trim silence")
        self.trim_check.setChecked(True)
        audio_form.addRow(self.trim_check)

        layout.addWidget(audio_group)

        # -- Performance group --
        perf_group = QGroupBox("Performance")
        perf_form = QFormLayout(perf_group)

        self.proxy_check = QCheckBox("Use proxy (faster, lower quality preview)")
        self.proxy_check.setChecked(True)
        perf_form.addRow(self.proxy_check)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 8)
        self.workers_spin.setValue(4)
        perf_form.addRow("Workers:", self.workers_spin)

        layout.addWidget(perf_group)
        layout.addStretch()

    def _on_preset(self, preset: str):
        """Apply preset dimensions."""
        presets = {
            "youtube": (1920, 1080, 30),
            "instagram": (1080, 1080, 30),
            "tiktok": (1080, 1920, 30),
        }
        if preset in presets:
            w, h, fps = presets[preset]
            self.width_spin.setValue(w)
            self.height_spin.setValue(h)
            self.fps_spin.setValue(fps)

    def get_config(self) -> dict:
        """Extract settings as a config dict."""
        return {
            "layout": self.layout_combo.currentText(),
            "preset": "" if self.preset_combo.currentText() == "Custom"
                      else self.preset_combo.currentText(),
            "output_width": self.width_spin.value(),
            "output_height": self.height_spin.value(),
            "output_fps": self.fps_spin.value(),
            "output_crf": self.crf_spin.value(),
            "audio_source": self.audio_source_spin.value(),
            "smart": self.smart_check.isChecked(),
            "style": self.style_combo.currentText(),
            "trim_silence": self.trim_check.isChecked(),
            "use_proxy": self.proxy_check.isChecked(),
            "max_workers": self.workers_spin.value(),
        }
