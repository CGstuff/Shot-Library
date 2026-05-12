"""
SequenceTimeline - Custom timeline widget with shot markers for Sequence Review Mode

Displays shots as rectangular markers proportional to their duration,
with a playhead indicator and click-to-jump functionality.
"""

from typing import List, Dict, Optional
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics


class SequenceTimeline(QWidget):
    """
    Custom-painted timeline showing shot markers proportional to duration.

    Features:
    - Shot markers as rectangles, width proportional to duration_ms
    - Current shot highlighted with accent color
    - Shot number labels inside markers
    - Vertical playhead line showing position within current shot
    - Click on marker to jump to that shot

    Signals:
        shot_clicked(int): Emitted when a shot marker is clicked with shot index
    """

    # Signals
    shot_clicked = pyqtSignal(int)  # Index of clicked shot

    # Visual constants
    MARKER_HEIGHT = 40
    MARKER_GAP = 2
    MARKER_Y_OFFSET = 10
    PLAYHEAD_COLOR = "#ffffff"
    CURRENT_SHOT_COLOR = "#3A8FB7"
    OTHER_SHOT_COLOR = "#444444"
    HOVER_SHOT_COLOR = "#555555"
    TEXT_COLOR = "#ffffff"
    BACKGROUND_COLOR = "#1a1a1a"
    BORDER_COLOR = "#333333"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Shot data
        self._shots: List[Dict] = []
        self._current_index: int = 0
        self._playhead_position: float = 0.0  # 0.0 to 1.0 within current shot

        # Cached marker rectangles for hit testing
        self._marker_rects: List[QRect] = []

        # Hover state
        self._hover_index: int = -1

        # Setup widget
        self.setMinimumHeight(60)
        self.setFixedHeight(60)
        self.setMouseTracking(True)

        # Style
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {self.BACKGROUND_COLOR};
                border-top: 1px solid {self.BORDER_COLOR};
            }}
        """)

    def set_shots(self, shots: List[Dict]) -> None:
        """
        Set the shot list for the timeline.

        Args:
            shots: List of shot dicts with 'duration_ms' and 'shot_name' keys
        """
        self._shots = shots
        self._current_index = 0
        self._playhead_position = 0.0
        self._recalculate_markers()
        self.update()

    def set_current_shot(self, index: int, position: float = 0.0) -> None:
        """
        Update the current shot and playhead position.

        Args:
            index: Index of current shot
            position: Position within shot (0.0 to 1.0)
        """
        if 0 <= index < len(self._shots):
            self._current_index = index
            self._playhead_position = max(0.0, min(1.0, position))
            self.update()

    def get_current_shot_index(self) -> int:
        """Get the current shot index."""
        return self._current_index

    def _recalculate_markers(self) -> None:
        """Recalculate marker rectangles based on widget width and shot durations."""
        self._marker_rects = []

        if not self._shots:
            return

        # Calculate total duration
        total_ms = sum(s.get('duration_ms', 1000) for s in self._shots)
        if total_ms <= 0:
            total_ms = len(self._shots) * 1000  # Fallback to 1s per shot

        # Calculate marker widths
        available_width = self.width() - (len(self._shots) - 1) * self.MARKER_GAP
        x_offset = 0

        for shot in self._shots:
            duration = shot.get('duration_ms', 1000)
            marker_width = max(20, int((duration / total_ms) * available_width))

            rect = QRect(
                int(x_offset),
                self.MARKER_Y_OFFSET,
                marker_width,
                self.MARKER_HEIGHT
            )
            self._marker_rects.append(rect)

            x_offset += marker_width + self.MARKER_GAP

    def _calculate_playhead_x(self) -> int:
        """Calculate the X position of the playhead line."""
        if not self._marker_rects or self._current_index >= len(self._marker_rects):
            return 0

        rect = self._marker_rects[self._current_index]
        # Position within the current marker
        return int(rect.x() + self._playhead_position * rect.width())

    def paintEvent(self, event) -> None:
        """Paint the timeline with shot markers and playhead."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw background
        painter.fillRect(self.rect(), QColor(self.BACKGROUND_COLOR))

        if not self._shots or not self._marker_rects:
            # No shots - draw message
            painter.setPen(QColor("#808080"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No shots loaded")
            return

        # Setup font for labels
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        font_metrics = QFontMetrics(font)

        # Draw shot markers
        for i, (shot, rect) in enumerate(zip(self._shots, self._marker_rects)):
            is_current = (i == self._current_index)
            is_hover = (i == self._hover_index and not is_current)

            # Choose color
            if is_current:
                color = QColor(self.CURRENT_SHOT_COLOR)
            elif is_hover:
                color = QColor(self.HOVER_SHOT_COLOR)
            else:
                color = QColor(self.OTHER_SHOT_COLOR)

            # Draw marker rectangle
            painter.fillRect(rect, color)

            # Draw border for current shot
            if is_current:
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawRect(rect.adjusted(0, 0, -1, -1))

            # Draw shot number label (centered in marker)
            label = str(i + 1)
            text_width = font_metrics.horizontalAdvance(label)

            # Only draw label if it fits
            if text_width + 4 < rect.width():
                painter.setPen(QColor(self.TEXT_COLOR))
                text_x = rect.x() + (rect.width() - text_width) // 2
                text_y = rect.y() + (rect.height() + font_metrics.ascent() - font_metrics.descent()) // 2
                painter.drawText(text_x, text_y, label)

        # Draw playhead line
        playhead_x = self._calculate_playhead_x()
        painter.setPen(QPen(QColor(self.PLAYHEAD_COLOR), 2))
        painter.drawLine(playhead_x, 0, playhead_x, self.height())

    def resizeEvent(self, event) -> None:
        """Handle resize - recalculate marker positions."""
        super().resizeEvent(event)
        self._recalculate_markers()

    def mousePressEvent(self, event) -> None:
        """Handle mouse click - detect shot marker clicks."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            clicked_index = self._hit_test(pos)

            if clicked_index >= 0:
                self.shot_clicked.emit(clicked_index)

    def mouseMoveEvent(self, event) -> None:
        """Handle mouse move - update hover state."""
        pos = event.position().toPoint()
        hover_index = self._hit_test(pos)

        if hover_index != self._hover_index:
            self._hover_index = hover_index
            self.update()

            # Update cursor
            if hover_index >= 0:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:
        """Handle mouse leave - clear hover state."""
        self._hover_index = -1
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def _hit_test(self, pos: QPoint) -> int:
        """
        Test which shot marker contains the given point.

        Args:
            pos: Point to test

        Returns:
            Shot index or -1 if no hit
        """
        for i, rect in enumerate(self._marker_rects):
            if rect.contains(pos):
                return i
        return -1

    @property
    def shot_count(self) -> int:
        """Get the number of shots in the timeline."""
        return len(self._shots)


__all__ = ['SequenceTimeline']
