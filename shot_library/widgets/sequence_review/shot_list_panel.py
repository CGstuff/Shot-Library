"""
Shot List Panel

Collapsible panel showing list of shots for easy navigation.
Extracted from SequenceReviewDialog for better modularity.
"""

from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from ...themes.fonts import Fonts, get_font_stylesheet


class ShotListPanel(QWidget):
    """
    Collapsible panel showing list of shots for easy navigation.

    Features:
    - Scrollable list of shots with shot number and name
    - Current shot highlighted
    - Click to jump to shot
    - Collapse/expand toggle (L key)

    Signals:
        shot_clicked: Emitted when user clicks a shot (int: index)
    """

    shot_clicked = pyqtSignal(int)  # index

    # Visual constants
    PANEL_WIDTH = 250
    COLLAPSED_WIDTH = 0

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._shots: List[Dict] = []
        self._current_index: int = 0
        self._is_collapsed: bool = False
        self._duration_labels: List[QLabel] = []

        self._setup_ui()

    def _setup_ui(self):
        """Create the panel layout."""
        self.setFixedWidth(self.PANEL_WIDTH)
        self.setStyleSheet("""
            ShotListPanel {
                background-color: #1a1a1a;
                border-right: 1px solid #333;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)

        # Header with toggle button
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(4)

        self._header_label = QLabel("SHOTS")
        self._header_label.setStyleSheet(f"""
            QLabel {{
                color: #888;
                {get_font_stylesheet(Fonts.SHOT_LIST_HEADER)}
                letter-spacing: 1px;
            }}
        """)
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()

        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setText("\u2261")  # Hamburger menu icon
        self._toggle_btn.setToolTip("Hide shot list (L)")
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                color: #fff;
            }
        """)
        self._toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self._toggle_btn)

        layout.addWidget(header)

        # Shot list
        self._shot_list = QListWidget()
        self._shot_list.setSpacing(0)
        self._shot_list.setStyleSheet(f"""
            QListWidget {{
                background-color: #1a1a1a;
                border: none;
                color: #ccc;
                {get_font_stylesheet(Fonts.SHOT_LIST_NAME)}
                outline: none;
            }}
            QListWidget::item {{
                padding: 0;
                margin: 0;
                border: 1px solid transparent;
                border-bottom: 1px solid #2a2a2a;
            }}
            QListWidget::item:hover {{
                background-color: #252525;
            }}
            QListWidget::item:selected {{
                background-color: #2a3a4a;
                border: 1px solid #3A8FB7;
            }}
        """)
        self._shot_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._shot_list, 1)

    def set_shots(self, shots: List[Dict]) -> None:
        """
        Set the list of shots to display.

        Args:
            shots: List of shot dictionaries
        """
        self._shots = shots
        self._duration_labels = []
        self._shot_list.clear()

        for i, shot in enumerate(shots):
            shot_name = shot.get('shot_name', shot.get('name', f'Shot {i + 1}'))
            display_name = shot_name if len(shot_name) <= 24 else shot_name[:21] + '...'

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setToolTip(shot_name)

            # Two-line widget: name + duration
            widget = QWidget()
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            wl = QVBoxLayout(widget)
            wl.setContentsMargins(8, 4, 8, 4)
            wl.setSpacing(2)

            name_label = QLabel(f"{i + 1}. {display_name}")
            name_label.setStyleSheet(f"color: #ccc; {get_font_stylesheet(Fonts.SHOT_LIST_NAME)} background: transparent;")
            wl.addWidget(name_label)

            dur_label = QLabel("")
            dur_label.setStyleSheet(f"color: #ccc; {get_font_stylesheet(Fonts.SHOT_LIST_DURATION)} background: transparent; padding-left: 16px;")
            wl.addWidget(dur_label)
            self._duration_labels.append(dur_label)

            item.setSizeHint(QSize(self.PANEL_WIDTH - 8, 44))
            self._shot_list.addItem(item)
            self._shot_list.setItemWidget(item, widget)

    def set_shot_durations(self, durations: List[float]) -> None:
        """
        Set duration display for each shot.

        Args:
            durations: List of durations in seconds
        """
        for i, dur in enumerate(durations):
            if i < len(self._duration_labels):
                self._duration_labels[i].setText(f"{dur:.1f}s")

    def set_current_shot(self, index: int) -> None:
        """
        Highlight the current shot in the list.

        Args:
            index: Shot index to highlight
        """
        self._current_index = index
        if 0 <= index < self._shot_list.count():
            self._shot_list.setCurrentRow(index)
            # Ensure visible
            self._shot_list.scrollToItem(self._shot_list.item(index))

    def get_current_index(self) -> int:
        """Get the currently selected shot index."""
        return self._current_index

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Handle shot item click."""
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and index != self._current_index:
            self.shot_clicked.emit(index)

    def toggle_collapse(self) -> None:
        """Toggle between visible and fully hidden."""
        self._is_collapsed = not self._is_collapsed
        self.setVisible(not self._is_collapsed)

    @property
    def is_collapsed(self) -> bool:
        """Check if panel is collapsed."""
        return self._is_collapsed

    def collapse(self) -> None:
        """Collapse the panel."""
        if not self._is_collapsed:
            self.toggle_collapse()

    def expand(self) -> None:
        """Expand the panel."""
        if self._is_collapsed:
            self.toggle_collapse()


__all__ = ['ShotListPanel']
