"""
ShotVideoPreviewWidget - Hover-to-play video preview for shot cards

Implements tasks T082-T086:
- T082: VideoPreviewWidget for hover-to-play
- T083: 500ms hover delay before starting preview
- T084: Video playback on hover enter using MediaEngine
- T085: Video stop on hover leave
- T086: Handle shots with no playblast (show placeholder/thumbnail)
"""

from typing import Optional, Callable
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage

from ..config import Config
from ..services.media_engine import MediaEngine, FrameResult
from ..themes.fonts import Fonts, get_font_stylesheet


class ShotVideoPreviewWidget(QWidget):
    """
    Hover-to-play video preview widget for shot cards.

    Features:
    - 500ms hover delay before starting preview (T083)
    - Video playback using MediaEngine (T084)
    - Stop on hover leave (T085)
    - Placeholder for shots without playblast (T086)
    - 16:9 aspect ratio display
    - Looping playback
    - FPS capped at 30 for performance

    Usage:
        preview = ShotVideoPreviewWidget()
        preview.show_preview(playblast_path, position)
        preview.hide_preview()
    """

    # Signals
    preview_started = pyqtSignal(str)  # playblast_path
    preview_stopped = pyqtSignal()
    preview_error = pyqtSignal(str, str)  # playblast_path, error_message

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Window flags for popup behavior
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # Doesn't appear in taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Preview state
        self._current_path: Optional[Path] = None
        self._is_showing = False

        # Media engine for video playback
        self._media_engine = MediaEngine(target_fps=Config.MEDIA_ENGINE_TARGET_FPS)

        # Hover delay timer (T083: 500ms delay before starting preview)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)
        self._pending_path: Optional[Path] = None
        self._pending_position: Optional[QPoint] = None

        # Preview size (16:9 aspect ratio)
        self._preview_width = Config.HOVER_VIDEO_SIZE
        self._preview_height = int(self._preview_width / Config.SHOT_CARD_ASPECT_RATIO)

        # Setup UI
        self._setup_ui()

        # Connect media engine signals
        self._media_engine.frame_ready.connect(self._on_frame_ready)
        self._media_engine.playback_error.connect(self._on_playback_error)

    def _setup_ui(self):
        """Setup widget UI with 16:9 display area."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video display label
        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setFixedSize(self._preview_width, self._preview_height)
        self._video_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                border: 2px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
        """)
        layout.addWidget(self._video_label)

        # Set fixed size (16:9)
        self.setFixedSize(self._preview_width, self._preview_height)

    def start_hover_preview(self, playblast_path: Path, position: QPoint):
        """
        Start hover timer for preview. Preview shows after 500ms delay.

        This implements T083: 500ms hover delay before starting preview.

        Args:
            playblast_path: Path to playblast MP4 file
            position: Screen position to show preview
        """
        # Store pending preview info
        self._pending_path = playblast_path
        self._pending_position = position

        # Start hover timer (500ms delay per config)
        self._hover_timer.start(Config.HOVER_VIDEO_DELAY_MS)

    def cancel_hover_preview(self):
        """Cancel pending hover preview (mouse left before timeout)."""
        self._hover_timer.stop()
        self._pending_path = None
        self._pending_position = None

    def show_preview(self, playblast_path: Path, position: QPoint):
        """
        Immediately show video preview at position.

        Implements T084: Video playback on hover enter.

        Args:
            playblast_path: Path to playblast MP4 file
            position: Screen position to show preview
        """
        # Cancel any pending preview
        self._hover_timer.stop()

        # Check if already showing this video
        if self._current_path == playblast_path and self._is_showing:
            # Just update position
            self.move(position)
            return

        # Close previous video if any
        self._media_engine.close_video()
        self._current_path = playblast_path

        # Try to open video
        if not playblast_path.exists():
            self._show_placeholder("File not found")
            return

        video_info = self._media_engine.open_video(playblast_path)
        if video_info is None:
            self._show_placeholder("Cannot open video")
            return

        # Position and show widget
        self.move(position)
        self.show()
        self.raise_()
        self._is_showing = True

        # Start playback
        self._media_engine.start_playback(
            on_frame=self._on_frame_callback,
            loop=True
        )

        self.preview_started.emit(str(playblast_path))

    def hide_preview(self):
        """
        Hide preview and stop playback.

        Implements T085: Video stop on hover leave.
        """
        # Cancel any pending preview
        self.cancel_hover_preview()

        # Stop playback
        self._media_engine.stop_playback()
        self._media_engine.close_video()

        # Hide widget
        self.hide()
        self._is_showing = False
        self._current_path = None

        self.preview_stopped.emit()

    def show_placeholder(self, shot_name: str = ""):
        """
        Show placeholder for shots without playblast.

        Implements T086: Handle shots with no playblast.

        Args:
            shot_name: Shot name to display in placeholder
        """
        self._show_placeholder(f"No playblast\n{shot_name}" if shot_name else "No playblast")

    def _show_placeholder(self, text: str):
        """Display placeholder text."""
        self._video_label.clear()
        self._video_label.setText(text)
        self._video_label.setStyleSheet(f"""
            QLabel {{
                background-color: #1a1a1a;
                border: 2px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                color: #808080;
                {get_font_stylesheet(Fonts.DEFAULT)}
            }}
        """)

    def _on_hover_timeout(self):
        """Handle hover timer timeout - show preview after delay."""
        if self._pending_path and self._pending_position:
            self.show_preview(self._pending_path, self._pending_position)
            self._pending_path = None
            self._pending_position = None

    def _on_frame_callback(self, result: FrameResult):
        """Callback from MediaEngine for each frame."""
        # Update display with new frame
        if result and result.image:
            self._display_frame(result.image)

    def _on_frame_ready(self, result: FrameResult):
        """Handle frame ready signal from MediaEngine."""
        if result and result.image:
            self._display_frame(result.image)

    def _display_frame(self, image: QImage):
        """Display a frame in the video label."""
        # Scale to fit 16:9 display area
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self._preview_width,
            self._preview_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self._video_label.setPixmap(scaled)
        self._video_label.setStyleSheet("""
            QLabel {
                background-color: #000000;
                border: 2px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
        """)

    def _on_playback_error(self, path, error):
        """Handle playback error from MediaEngine."""
        self._show_placeholder("Playback error")
        self.preview_error.emit(str(path), str(error))

    def update_position(self, position: QPoint):
        """Update preview position (for follow-mouse behavior)."""
        if self._is_showing:
            self.move(position)

    def set_size(self, width: int):
        """
        Set preview size maintaining 16:9 aspect ratio.

        Args:
            width: Preview width in pixels
        """
        self._preview_width = width
        self._preview_height = int(width / Config.SHOT_CARD_ASPECT_RATIO)
        self._video_label.setFixedSize(self._preview_width, self._preview_height)
        self.setFixedSize(self._preview_width, self._preview_height)

    @property
    def is_showing(self) -> bool:
        """Check if preview is currently visible."""
        return self._is_showing

    @property
    def current_path(self) -> Optional[Path]:
        """Get current playblast path being previewed."""
        return self._current_path

    def closeEvent(self, event):
        """Clean up resources on close."""
        self._media_engine.close_video()
        self._hover_timer.stop()
        super().closeEvent(event)


__all__ = ['ShotVideoPreviewWidget']
