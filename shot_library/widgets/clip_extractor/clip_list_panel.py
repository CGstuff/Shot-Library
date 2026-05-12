"""Clip List Panel — left sidebar listing exported clips."""

from pathlib import Path
from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton,
)
from PyQt6.QtCore import Qt, QUrl, QSize, pyqtSignal
from PyQt6.QtGui import QDesktopServices

from ...themes.fonts import Fonts, get_font_stylesheet

from ...utils import IconLoader, colorize_white_svg
from .state import ExportedClip


class ClipListPanel(QWidget):
    """Left panel showing exported clips (hidable with L key)."""

    clip_clicked = pyqtSignal(int)  # index

    PANEL_WIDTH = 220
    COLLAPSED_WIDTH = 0

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._clips: List[ExportedClip] = []
        self._collapsed = False
        self._output_folder: Optional[Path] = None

        self.setFixedWidth(self.PANEL_WIDTH)
        self.setStyleSheet("background-color: #1e1e1e;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header row with title + open-folder button
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("background-color: #252525;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        header_layout.setSpacing(0)

        title = QLabel("CLIPS")
        title.setStyleSheet("color: #999; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self._open_folder_btn = QPushButton()
        self._open_folder_btn.setIcon(
            colorize_white_svg(IconLoader.get("folder_open"), "#aaaaaa")
        )
        self._open_folder_btn.setIconSize(QSize(16, 16))
        self._open_folder_btn.setFixedSize(24, 22)
        self._open_folder_btn.setStyleSheet(
            "QPushButton { background:#333; border:1px solid #555; border-radius:2px; }"
            "QPushButton:hover { background:#444; }"
        )
        self._open_folder_btn.setToolTip("Open export folder in file explorer")
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        self._open_folder_btn.setVisible(False)  # shown after first export
        header_layout.addWidget(self._open_folder_btn)

        layout.addWidget(header)

        # List
        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                border: none;
                outline: none;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #2a2a2a;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #3A8FB7;
            }
        """)
        self._list.currentRowChanged.connect(self.clip_clicked.emit)
        layout.addWidget(self._list)

    def set_output_folder(self, folder: Path):
        """Set the export output folder and show the Open Folder button."""
        self._output_folder = folder
        self._open_folder_btn.setVisible(True)

    def _open_output_folder(self):
        """Open the export folder in the system file explorer."""
        if self._output_folder and self._output_folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_folder)))

    def add_clip(self, clip: ExportedClip):
        """Append a new exported clip to the list."""
        self._clips.append(clip)
        # Auto-set output folder from the first clip
        if self._output_folder is None:
            self.set_output_folder(clip.path.parent)

        item = QListWidgetItem()
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(4, 2, 4, 2)
        widget_layout.setSpacing(1)

        name_label = QLabel(clip.filename)
        name_label.setStyleSheet("color: #e0e0e0; font-size: 11px;")

        dur_label = QLabel(f"{clip.duration_seconds:.1f}s")
        dur_label.setStyleSheet("color: #888; font-size: 10px;")

        widget_layout.addWidget(name_label)
        widget_layout.addWidget(dur_label)

        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, len(self._clips) - 1)

        self._list.addItem(item)
        self._list.setItemWidget(item, widget)
        self._list.scrollToBottom()

    def toggle_collapse(self):
        """Toggle panel visibility."""
        self._collapsed = not self._collapsed
        self.setVisible(not self._collapsed)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

