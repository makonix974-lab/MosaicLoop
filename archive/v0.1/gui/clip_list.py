"""
Clip list widget with drag & drop support.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox,
)


STYLES = """
QListWidget {
    border: 2px dashed #555;
    border-radius: 8px;
    background: #1a1a1a;
    padding: 4px;
}
QListWidget[dragOver="true"] {
    border-color: #4a9eff;
    background: #1a2a3a;
}
QListWidget::item {
    padding: 8px 4px;
    border-bottom: 1px solid #333;
}
QListWidget::item:selected {
    background: #2a4a7a;
}
"""


class ClipListWidget(QWidget):
    """List of video clips with drag-drop import."""

    clips_changed = list  # signal-like: list of paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Video Clips (drag & drop)")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        layout.addWidget(header)

        self.list_widget = _DropList(self)
        self.list_widget.itemDoubleClicked.connect(self._remove_item)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        import_btn = QPushButton("+ Import")
        import_btn.clicked.connect(self._import_dialog)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    @property
    def paths(self) -> list[str]:
        return list(self._paths)

    @paths.setter
    def paths(self, value: list[str]):
        self._paths = list(value)
        self._refresh()

    def add_paths(self, new_paths: list[str]):
        existing = set(self._paths)
        for p in new_paths:
            if p not in existing:
                self._paths.append(p)
                existing.add(p)
        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        for i, p in enumerate(self._paths):
            name = Path(p).name
            size = Path(p).stat().st_size
            size_mb = size / (1024 * 1024)
            item = QListWidgetItem(f"  {i+1}. {name}  ({size_mb:.0f} MB)")
            item.setToolTip(p)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list_widget.addItem(item)

    def _import_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Video Files", "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.webm *.m4v);;All Files (*)"
        )
        if files:
            self.add_paths(files)

    def _remove_item(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path in self._paths:
            self._paths.remove(path)
            self._refresh()

    def _clear_all(self):
        self._paths.clear()
        self._refresh()


class _DropList(QListWidget):
    """QListWidget with drag-drop support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self.setStyleSheet(STYLES)
        self._drag_over = False

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drag_over = True
            self.setProperty("dragOver", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self._drag_over = False
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self._drag_over = False
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                ext = Path(path).suffix.lower()
                if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"):
                    paths.append(path)

        if paths:
            clip_widget = self.parent()
            while clip_widget and not hasattr(clip_widget, "add_paths"):
                clip_widget = clip_widget.parent()
            if clip_widget:
                clip_widget.add_paths(paths)
