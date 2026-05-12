"""
Sequence Review Dialog

Fullscreen dialog for reviewing all shots in sequence.
Refactored to use extracted components for better maintainability.

Original: ~1500 lines
Refactored: ~450 lines (orchestration only)
"""

import logging
from typing import List, Dict, Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSizePolicy, QCheckBox, QMenu, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent

from ...config import Config
from ...services.media_engine import MediaEngine, FrameResult
from ...utils import IconLoader, colorize_white_svg, frame_to_timecode
from ...utils.video_resolver import ShotVideoResolver
from ...themes.theme_manager import get_theme_manager
from ..frame_ruler_timeline import FrameRulerTimeline

from .state import PlaybackState, TimelineState, PreloadState, DisplayState
from .timeline_manager import SequenceTimelineManager
from .export_manager import SequenceExportManager
from .shot_list_panel import ShotListPanel
from .preload_worker import PreloadManager
from ...themes.fonts import Fonts, get_font_stylesheet

logger = logging.getLogger(__name__)


class SequenceReviewDialog(QDialog):
    """
    Fullscreen dialog for sequence review mode.

    Features:
    - Large video display area (16:9 aspect ratio)
    - Shot list panel on left for navigation (collapsible with L key)
    - Frame ruler with timecode/frame display (toggle with T key)
    - Auto-play all shots in succession
    - Export to MP4 (current shot or full sequence)
    - Keyboard shortcuts: Space (play/pause), Left/Right (prev/next), Escape (exit)
    - Uses current view: Reviews exactly what's visible in ShotView (filtered shots)

    Args:
        shots: List of shot dicts from proxy model (filtered, editorial order)
        current_index: Index of shot to start with
        parent: Parent widget
    """

    # Signals
    shot_changed = pyqtSignal(int, dict)  # index, shot_data

    # Visual constants
    BACKGROUND_COLOR = "#0a0a0a"
    ACCENT_COLOR = "#3A8FB7"
    CONTROL_HEIGHT = 50

    def __init__(
        self,
        shots: List[Dict],
        current_index: int = 0,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        # Data
        self._shots = shots
        self._current_index = max(0, min(current_index, len(shots) - 1)) if shots else 0

        # State objects (grouped from 45+ variables)
        self._playback = PlaybackState()
        self._timeline_state = TimelineState()
        self._preload_state = PreloadState()
        self._display = DisplayState()

        # Managers
        self._timeline_manager = SequenceTimelineManager()
        self._export_manager = SequenceExportManager()
        self._preload_manager = PreloadManager()

        # Media engines (double-buffering for seamless transitions)
        self._active_engine = MediaEngine(target_fps=30)
        self._active_engine.set_preview_scale(False)
        self._preload_engine = MediaEngine(target_fps=30)
        self._preload_engine.set_preview_scale(False)
        
        # Timer for auto-advance (so we can cancel it on manual navigation)
        self._advance_timer: Optional[QTimer] = None

        # Theme
        self._theme_manager = get_theme_manager()

        # Setup
        self._setup_window()
        self._setup_ui()
        self._connect_signals()

        # Initialize timeline
        if self._shots:
            QTimer.singleShot(100, self._init_sequence_timeline)

    def _setup_window(self):
        """Configure window for fullscreen review."""
        self.setWindowTitle("Sequence Review - Shot Library")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.showMaximized()

        self.setStyleSheet(f"""
            QDialog {{ background-color: {self.BACKGROUND_COLOR}; }}
            QLabel {{ color: white; }}
            QPushButton {{
                background-color: #333333; color: white;
                border: none; border-radius: 4px;
                padding: 8px 16px; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #444444; }}
            QPushButton:pressed {{ background-color: #555555; }}
            QPushButton:checked {{ background-color: {self.ACCENT_COLOR}; }}
            QCheckBox {{ color: white; spacing: 8px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid #555;
                border-radius: 0px;
                background-color: #333;
            }}
            QCheckBox::indicator:checked {{
                background-color: {self.ACCENT_COLOR};
                border-color: {self.ACCENT_COLOR};
            }}
            QCheckBox::indicator:hover {{
                border-color: {self.ACCENT_COLOR};
            }}
        """)

    def _setup_ui(self):
        """Create the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        layout.addWidget(self._create_header())

        # Main content (shot list + video + ruler)
        layout.addWidget(self._create_content(), 1)

        # Control bar
        layout.addWidget(self._create_controls())

    def _create_header(self) -> QWidget:
        """Create header bar with shot info and export button."""
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333;")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        self._shot_label = QLabel("Loading...")
        self._shot_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self._shot_label)

        self._counter_label = QLabel("")
        self._counter_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self._counter_label)

        layout.addStretch()

        self._export_btn = QPushButton("Export")
        self._export_btn.setFixedSize(80, 32)
        self._export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_btn)

        layout.addSpacing(10)

        close_btn = QPushButton("Close")
        close_btn.setFixedSize(80, 32)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return header

    def _create_content(self) -> QWidget:
        """Create main content area with shot list, video, and ruler."""
        content = QWidget()
        content.setStyleSheet("background-color: #000000;")
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Shot list panel
        self._shot_list_panel = ShotListPanel()
        self._shot_list_panel.set_shots(self._shots)
        self._shot_list_panel.shot_clicked.connect(self._on_shot_list_clicked)
        layout.addWidget(self._shot_list_panel)

        # Video + ruler container
        video_container = QWidget()
        video_container.setStyleSheet("background-color: #000000;")
        video_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        video_layout = QVBoxLayout(video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)

        # Video display
        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setStyleSheet("background-color: #000000;")
        self._video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video_label.setMinimumSize(400, 225)
        video_layout.addWidget(self._video_label, 1)

        # Frame ruler row
        video_layout.addWidget(self._create_frame_ruler())

        layout.addWidget(video_container, 1)
        return content

    def _create_frame_ruler(self) -> QWidget:
        """Create frame ruler row with timecode toggle and display."""
        row = QWidget()
        row.setFixedHeight(50)
        row.setStyleSheet("background-color: #1a1a1a;")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # TC/Frame toggle
        self._timecode_btn = QPushButton()
        self._timecode_btn.setFixedSize(28, 28)
        self._timecode_btn.setCheckable(True)
        self._timecode_btn.setChecked(True)
        self._timecode_btn.setToolTip("Toggle Timecode/Frame display (T)")
        self._set_timecode_button_icon(True)
        self._timecode_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 1px solid #444;
            }
            QPushButton:checked {
                background-color: #3A8FB7;
                border: 1px solid #3A8FB7;
            }
            QPushButton:hover { border-color: #3A8FB7; }
        """)
        self._timecode_btn.clicked.connect(self._toggle_timecode_mode)
        layout.addWidget(self._timecode_btn)

        # Frame ruler
        self._frame_ruler = FrameRulerTimeline()
        self._frame_ruler.frame_clicked.connect(self._on_ruler_frame_clicked)
        self._frame_ruler.frame_dragged.connect(self._on_ruler_frame_clicked)
        layout.addWidget(self._frame_ruler, 1)

        # Time display
        self._time_display = QLabel("00:00:00:00")
        self._time_display.setFixedWidth(110)
        self._time_display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._time_display.setStyleSheet(f"""
            QLabel {{
                color: #e0e0e0;
                {get_font_stylesheet(Fonts.TIMECODE)}
                background-color: #252525; border: 1px solid #333;
                padding: 4px 8px;
            }}
        """)
        layout.addWidget(self._time_display)

        return row

    def _create_controls(self) -> QWidget:
        """Create bottom control bar."""
        controls = QWidget()
        controls.setFixedHeight(self.CONTROL_HEIGHT)
        controls.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333;")

        layout = QHBoxLayout(controls)
        layout.setContentsMargins(20, 5, 20, 5)
        layout.setSpacing(10)

        # Navigation buttons (transparent, icon-only)
        nav_btn_style = """
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """

        self._prev_btn = QPushButton()
        self._prev_btn.setFixedSize(40, 40)
        self._prev_btn.setToolTip("Previous Shot (Left Arrow)")
        self._prev_btn.setStyleSheet(nav_btn_style)
        self._set_button_icon(self._prev_btn, "arrow_left")
        self._prev_btn.clicked.connect(self._prev_shot)
        layout.addWidget(self._prev_btn)

        self._play_btn = QPushButton()
        self._play_btn.setFixedSize(50, 40)
        self._play_btn.setToolTip("Play/Pause (Space)")
        self._play_btn.setStyleSheet(nav_btn_style)
        self._set_button_icon(self._play_btn, "play")
        self._play_btn.clicked.connect(self._toggle_playback)
        layout.addWidget(self._play_btn)

        self._next_btn = QPushButton()
        self._next_btn.setFixedSize(40, 40)
        self._next_btn.setToolTip("Next Shot (Right Arrow)")
        self._next_btn.setStyleSheet(nav_btn_style)
        self._set_button_icon(self._next_btn, "arrow_right")
        self._next_btn.clicked.connect(self._next_shot)
        layout.addWidget(self._next_btn)

        layout.addSpacing(20)

        # Auto-advance
        self._auto_advance_cb = QCheckBox("Auto-advance")
        self._auto_advance_cb.setChecked(True)
        self._auto_advance_cb.toggled.connect(lambda c: setattr(self._playback, 'auto_advance', c))
        layout.addWidget(self._auto_advance_cb)

        layout.addStretch()

        self._playback_label = QLabel("")
        self._playback_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._playback_label)

        return controls

    def _set_button_icon(self, button: QPushButton, icon_name: str):
        """Set icon on button with fallback to text."""
        try:
            icon_path = IconLoader.get(icon_name)
            icon = colorize_white_svg(icon_path, "#ffffff")
            button.setIcon(icon)
            button.setIconSize(QSize(20, 20))
        except KeyError:
            fallback = {"play": "Play", "pause": "||", "arrow_left": "<<", "arrow_right": ">>"}
            button.setText(fallback.get(icon_name, icon_name))

    def _set_timecode_button_icon(self, is_timecode: bool):
        """Set icon for timecode/frame toggle button."""
        try:
            icon_name = "timecode" if is_timecode else "frame_number"
            icon_path = IconLoader.get(icon_name)
            icon = colorize_white_svg(icon_path, "#ffffff")
            if icon.isNull():
                raise ValueError("Icon is null")
            self._timecode_btn.setIcon(icon)
            self._timecode_btn.setIconSize(QSize(18, 18))
            self._timecode_btn.setText("")  # Clear any existing text
        except Exception:
            # Fallback to text
            self._timecode_btn.setText("TC" if is_timecode else "F")

    def _connect_signals(self):
        """Connect engine signals."""
        self._active_engine.playback_complete.connect(self._on_video_complete)
        self._active_engine.playback_error.connect(self._on_playback_error)
        self._preload_engine.playback_complete.connect(self._on_video_complete)

    # ===== Timeline Initialization =====

    def _init_sequence_timeline(self):
        """Initialize unified sequence timeline."""
        fps = self._timeline_manager.init_from_shots(self._shots)
        self._timeline_state.current_video_fps = fps

        # Setup frame ruler
        self._frame_ruler.set_total_frames(self._timeline_manager.total_frames)
        self._frame_ruler.set_shot_boundaries(self._timeline_manager.get_shot_boundaries())
        self._frame_ruler.set_current_frame(0)
        self._update_time_display(0)

        # Compute shot durations and pass to panel
        durations = []
        for i in range(len(self._shots)):
            frame_count = self._timeline_manager.get_shot_frame_count(i)
            shot_fps = self._timeline_manager.get_shot_fps(i)
            durations.append(frame_count / shot_fps if shot_fps > 0 else 0.0)
        self._shot_list_panel.set_shot_durations(durations)

        # Load first shot
        self._load_shot(self._current_index)

    # ===== Shot Loading =====

    def _load_shot(self, index: int) -> None:
        """Load video for shot at given index."""
        if not self._shots or index < 0 or index >= len(self._shots):
            return

        # Cancel preload and stop playback
        self._preload_manager.cancel()
        self._active_engine.stop_playback()
        self._playback.reset()
        self._display.clear_frame()

        self._current_index = index
        shot = self._shots[index]

        # Update UI
        shot_name = shot.get('shot_name', shot.get('name', f'Shot {index + 1}'))
        self._shot_label.setText(f"Shot: {shot_name}")
        self._counter_label.setText(f"({index + 1}/{len(self._shots)})")
        self._shot_list_panel.set_current_shot(index)

        # Get video path
        video_path = ShotVideoResolver.get_existing_video_path(shot)
        if not video_path:
            self._show_no_video_message(shot_name)
            return

        # Open video
        video_info = self._active_engine.open_video(video_path)
        if not video_info:
            self._show_no_video_message(shot_name, "Cannot open video")
            return

        # Update state and UI
        self._timeline_state.current_video_fps = video_info.fps
        self._playback_label.setText(
            f"{video_info.width}x{video_info.height} | {video_info.fps:.1f}fps | {video_info.duration_ms / 1000:.1f}s"
        )

        # Update timeline position
        global_frame = self._timeline_manager.get_global_frame(index, 0)
        self._frame_ruler.set_current_frame(global_frame)
        self._update_time_display(global_frame)

        # Show first frame
        first_frame = self._active_engine.get_frame(0)
        if first_frame:
            self._display_frame(first_frame.image)

        self._set_button_icon(self._play_btn, "play")
        self.shot_changed.emit(index, shot)

    def _show_no_video_message(self, shot_name: str, message: str = "No playblast"):
        """Show message when video unavailable."""
        self._video_label.clear()
        self._video_label.setText(f"{message}\n{shot_name}")
        self._video_label.setStyleSheet("background-color: #000000; color: #808080; font-size: 14px;")
        self._playback_label.setText("")

    def _display_frame(self, image: QImage):
        """Display frame with proper scaling."""
        self._display.set_current_frame(image)
        pixmap = QPixmap.fromImage(image)
        label_size = self._video_label.size()

        if label_size.width() < 100:
            screen = self.screen()
            if screen:
                label_size = screen.availableSize()
                label_size.setHeight(label_size.height() - 160)

        scaled = pixmap.scaled(label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._video_label.setPixmap(scaled)

    # ===== Playback Control =====

    def _toggle_playback(self):
        """Toggle play/pause."""
        if self._playback.is_playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        """Start playback."""
        if not self._active_engine.video_info:
            return

        # If at or near end of video, seek to beginning first
        video_info = self._active_engine.video_info
        current_pos = self._active_engine.current_frame
        if current_pos >= video_info.frame_count - 2:
            # Seek to frame 0 and show first frame
            first_frame = self._active_engine.get_frame(0)
            if first_frame:
                self._display_frame(first_frame.image)
                global_frame = self._timeline_manager.get_global_frame(self._current_index, 0)
                self._frame_ruler.set_current_frame(global_frame)
                self._update_time_display(global_frame)

        self._playback.start_playback()
        self._set_button_icon(self._play_btn, "pause")
        self._active_engine.start_playback(on_frame=self._on_frame_callback, loop=False)

    def _pause_playback(self):
        """Pause playback."""
        self._playback.stop_playback()
        self._active_engine.pause_playback()
        self._set_button_icon(self._play_btn, "play")

    def _on_frame_callback(self, result: FrameResult):
        """Handle frame from playback."""
        if not result or not result.image:
            return

        self._display_frame(result.image)

        # Update timeline
        global_frame = self._timeline_manager.get_global_frame(self._current_index, result.frame_number)
        self._frame_ruler.set_current_frame(global_frame)
        self._update_time_display(global_frame)

        # Trigger preload at 80%
        if self._active_engine.video_info:
            progress = result.frame_number / max(1, self._active_engine.video_info.frame_count - 1)
            if (self._playback.auto_advance and progress > 0.8 and
                not self._preload_state.is_ready_for(self._current_index + 1) and
                self._current_index < len(self._shots) - 1):
                self._preload_next_shot()

    def _on_video_complete(self):
        """Handle end of video."""
        self._playback.stop_playback()
        self._set_button_icon(self._play_btn, "play")

        if self._playback.auto_advance and self._current_index < len(self._shots) - 1:
            self._playback.prepare_for_next()

            # Use cancellable timer so manual navigation can interrupt
            self._cancel_advance_timer()
            self._advance_timer = QTimer(self)
            self._advance_timer.setSingleShot(True)
            
            if self._preload_state.is_ready_for(self._current_index + 1):
                self._advance_timer.timeout.connect(self._swap_to_preloaded)
                self._advance_timer.start(16)
            else:
                self._advance_timer.timeout.connect(self._advance_to_next)
                self._advance_timer.start(50)
    
    def _cancel_advance_timer(self):
        """Cancel any pending auto-advance timer."""
        if self._advance_timer is not None:
            self._advance_timer.stop()
            self._advance_timer.deleteLater()
            self._advance_timer = None
        self._playback.waiting_for_next = False

    def _advance_to_next(self):
        """Advance to next shot (fallback)."""
        if self._playback.waiting_for_next and self._current_index < len(self._shots) - 1:
            self._playback.reset()
            self._current_index += 1
            self._load_shot(self._current_index)
            QTimer.singleShot(16, self._start_playback)

    # ===== Preloading =====

    def _preload_next_shot(self):
        """Start preloading next shot."""
        next_index = self._current_index + 1
        if next_index >= len(self._shots) or self._preload_state.preloaded_index == next_index:
            return

        self._preload_state.clear()
        self._preload_state.preloaded_index = next_index

        video_path = ShotVideoResolver.get_existing_video_path(self._shots[next_index])
        if not video_path:
            return

        self._preload_manager.start_preload(self._preload_engine, video_path, self._on_preload_finished)

    def _on_preload_finished(self, success: bool, data):
        """Handle preload completion."""
        if not success or not data:
            self._preload_state.clear()
            return

        video_info, first_frame = data
        self._preload_state.mark_ready(self._preload_state.preloaded_index, first_frame, video_info)

    def _swap_to_preloaded(self):
        """Swap to preloaded video."""
        if not self._preload_state.preload_ready:
            self._advance_to_next()
            return

        self._playback.reset()
        self._active_engine.stop_playback()
        self._display.clear_frame()

        # Swap engines
        self._active_engine, self._preload_engine = self._preload_engine, self._active_engine

        # Update state
        self._current_index = self._preload_state.preloaded_index
        shot = self._shots[self._current_index]

        # Update UI
        shot_name = shot.get('shot_name', shot.get('name', f'Shot {self._current_index + 1}'))
        self._shot_label.setText(f"Shot: {shot_name}")
        self._counter_label.setText(f"({self._current_index + 1}/{len(self._shots)})")
        self._shot_list_panel.set_current_shot(self._current_index)

        if self._preload_state.preloaded_video_info:
            vi = self._preload_state.preloaded_video_info
            self._timeline_state.current_video_fps = vi.fps
            self._playback_label.setText(f"{vi.width}x{vi.height} | {vi.fps:.1f}fps | {vi.duration_ms / 1000:.1f}s")

        # Update timeline
        global_frame = self._timeline_manager.get_global_frame(self._current_index, 0)
        self._frame_ruler.set_current_frame(global_frame)
        self._update_time_display(global_frame)

        # Display preloaded frame
        first_frame, _ = self._preload_state.consume()
        if first_frame:
            self._display_frame(first_frame.image)

        # Cleanup and start
        QTimer.singleShot(100, self._preload_engine.close_video)
        self._start_playback()
        self.shot_changed.emit(self._current_index, shot)

    # ===== Navigation =====

    def _prev_shot(self):
        """Go to previous shot, or restart current shot if at first."""
        self._cancel_advance_timer()
        
        if self._current_index > 0:
            was_playing = self._playback.is_playing
            self._load_shot(self._current_index - 1)
            if was_playing:
                QTimer.singleShot(16, self._start_playback)
        else:
            # At first shot - restart it
            self._restart_current_shot()

    def _next_shot(self):
        """Go to next shot."""
        self._cancel_advance_timer()
        
        if self._current_index < len(self._shots) - 1:
            was_playing = self._playback.is_playing
            self._load_shot(self._current_index + 1)
            if was_playing:
                QTimer.singleShot(16, self._start_playback)

    def _restart_current_shot(self):
        """Restart the current shot from the beginning."""
        was_playing = self._playback.is_playing
        self._load_shot(self._current_index)
        if was_playing:
            QTimer.singleShot(16, self._start_playback)

    def _on_shot_list_clicked(self, index: int):
        """Handle shot list click."""
        self._cancel_advance_timer()
        
        was_playing = self._playback.is_playing
        
        # Always load the shot (allows replay of same shot)
        self._load_shot(index)
        
        if was_playing:
            QTimer.singleShot(16, self._start_playback)

    def _on_ruler_frame_clicked(self, global_frame: int):
        """Handle ruler click/drag."""
        self._cancel_advance_timer()
        
        if self._playback.is_playing:
            self._pause_playback()

        shot_index, local_frame = self._timeline_manager.get_shot_from_global_frame(global_frame)

        if shot_index != self._current_index:
            self._load_shot(shot_index)

        result = self._active_engine.get_frame(local_frame)
        if result:
            self._display_frame(result.image)
            self._frame_ruler.set_current_frame(global_frame)
            self._update_time_display(global_frame)

    # ===== UI Updates =====

    def _toggle_timecode_mode(self):
        """Toggle timecode/frame display."""
        self._timeline_state.show_timecode = self._timecode_btn.isChecked()
        self._set_timecode_button_icon(self._timeline_state.show_timecode)
        self._update_time_display(self._frame_ruler._current_frame)

    def _update_time_display(self, frame: int):
        """Update time/frame display."""
        if self._timeline_state.show_timecode:
            tc = frame_to_timecode(frame, self._timeline_state.current_video_fps)
            self._time_display.setText(tc)
        else:
            total = self._timeline_manager.total_frames
            width = len(str(total))
            self._time_display.setText(f"{frame:>{width}}/{total}")

    def _on_playback_error(self, path, error):
        """Handle playback error."""
        shot_name = self._shots[self._current_index].get('shot_name', 'Unknown')
        self._show_no_video_message(shot_name, "Playback error")

    # ===== Export =====

    def _on_export_clicked(self):
        """Show export menu."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2a2a2a; color: white; border: 1px solid #444; padding: 4px; }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background-color: #3A8FB7; }
        """)

        current_action = menu.addAction("Export Current Shot")
        current_action.triggered.connect(self._export_current_shot)

        if len(self._shots) > 1:
            sequence_action = menu.addAction("Export All Shots (Sequence)")
            sequence_action.triggered.connect(self._export_sequence)

        menu.exec(self._export_btn.mapToGlobal(self._export_btn.rect().bottomLeft()))

    def _export_current_shot(self):
        """Export current shot."""
        shot = self._shots[self._current_index]
        success, message, path = self._export_manager.export_current_shot(shot)

        if success:
            self._show_export_success(str(path))
        else:
            QMessageBox.warning(self, "Export Failed", message)

    def _export_sequence(self):
        """Export full sequence."""
        if not self._export_manager.find_ffmpeg():
            QMessageBox.warning(self, "FFmpeg Required",
                "FFmpeg is required to export sequences.\n"
                "Please install FFmpeg and add it to your PATH.")
            return

        progress = QProgressDialog("Exporting sequence...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Export")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        def update_progress(current, total, msg):
            progress.setValue(int((current / max(1, total)) * 100))
            progress.setLabelText(msg)

        success, message, path = self._export_manager.export_sequence(
            self._shots, progress_callback=update_progress
        )
        progress.close()

        if success:
            self._show_export_success(str(path))
        else:
            QMessageBox.warning(self, "Export Failed", message)

    def _show_export_success(self, path: str):
        """Show export success dialog."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Export Complete")
        msg.setText("Video exported successfully!")
        msg.setInformativeText(f"Saved to:\n{path}")

        open_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()

        if msg.clickedButton() == open_btn:
            self._export_manager.open_in_explorer(path)

    # ===== Events =====

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts."""
        key = event.key()

        handlers = {
            Qt.Key.Key_Escape: self.close,
            Qt.Key.Key_Space: self._toggle_playback,
            Qt.Key.Key_Left: self._prev_shot,
            Qt.Key.Key_Right: self._next_shot,
            Qt.Key.Key_Home: lambda: (self._cancel_advance_timer(), self._load_shot(0)),
            Qt.Key.Key_End: lambda: (self._cancel_advance_timer(), self._load_shot(len(self._shots) - 1)),
            Qt.Key.Key_A: lambda: self._auto_advance_cb.setChecked(not self._playback.auto_advance),
            Qt.Key.Key_R: self._restart_current_shot,
            Qt.Key.Key_T: lambda: (self._timecode_btn.setChecked(not self._timecode_btn.isChecked()), self._toggle_timecode_mode()),
            Qt.Key.Key_L: self._shot_list_panel.toggle_collapse,
        }

        handler = handlers.get(key)
        if handler:
            handler()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        """Handle resize."""
        super().resizeEvent(event)
        if self._display.has_frame():
            QTimer.singleShot(10, lambda: self._display_frame(self._display.current_frame_image))

    def closeEvent(self, event):
        """Clean up on close."""
        self._cancel_advance_timer()
        self._preload_manager.cleanup()
        self._active_engine.stop_playback()
        self._active_engine.close_video()
        self._preload_engine.stop_playback()
        self._preload_engine.close_video()
        super().closeEvent(event)


__all__ = ['SequenceReviewDialog']
