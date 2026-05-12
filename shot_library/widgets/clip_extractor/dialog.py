"""Clip Extractor Dialog — fullscreen video trimmer for Analysis Mode."""

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSplitter, QMessageBox,
)
from PyQt6.QtCore import Qt, QSize, QTimer
from ...themes.fonts import Fonts, get_font_stylesheet
from PyQt6.QtGui import QPixmap, QKeyEvent, QFont, QShortcut, QKeySequence

from ...services.media_engine import MediaEngine, FrameResult, VideoInfo
from ...utils import IconLoader, colorize_white_svg
from ..frame_ruler_timeline import FrameRulerTimeline
from .state import ClipPlaybackState, ClipSelectionState, ExportedClip
from .clip_list_panel import ClipListPanel
from .clip_export_manager import ClipExportManager

# Icon colour for dark-background dialogs
_ICON_COLOR = "#cccccc"


class ClipExtractorDialog(QDialog):
    """Fullscreen dialog for trimming clips from a reference video."""

    def __init__(
        self,
        video_path: Path,
        video_name: str = "video",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._video_path = video_path
        self._video_name = video_name

        # State
        self._playback = ClipPlaybackState()
        self._selection = ClipSelectionState()
        self._video_info: Optional[VideoInfo] = None

        # Managers
        self._engine = MediaEngine(target_fps=30)
        self._export_manager = ClipExportManager()

        # Playback timer
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._open_video()

    # ------------------------------------------------------------------ setup
    def _setup_window(self):
        self.setWindowTitle(f"Clip Extractor — {self._video_name}")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.showMaximized()

    # ------------------------------------------------------------- UI build
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Header ---
        root.addWidget(self._build_header())

        # --- Body: clip list + video ---
        body = QSplitter(Qt.Orientation.Horizontal)
        self._clip_list = ClipListPanel()
        body.addWidget(self._clip_list)

        # Video area (video label + ruler)
        video_area = QWidget()
        va_layout = QVBoxLayout(video_area)
        va_layout.setContentsMargins(0, 0, 0, 0)
        va_layout.setSpacing(0)

        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setStyleSheet("background-color: #111;")
        self._video_label.setMinimumHeight(200)
        va_layout.addWidget(self._video_label, 1)

        # Timecodes + ruler row
        ruler_row = QHBoxLayout()
        ruler_row.setContentsMargins(0, 0, 0, 0)
        ruler_row.setSpacing(0)

        self._tc_label = QLabel("00:00:00:00")
        self._tc_label.setFixedWidth(100)
        self._tc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tc_label.setStyleSheet("color:#ccc; font-family:Consolas; font-size:11px; background:#1a1a1a;")
        ruler_row.addWidget(self._tc_label)

        self._frame_ruler = FrameRulerTimeline()
        ruler_row.addWidget(self._frame_ruler, 1)

        self._duration_tc = QLabel("00:00:00:00")
        self._duration_tc.setFixedWidth(100)
        self._duration_tc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._duration_tc.setStyleSheet("color:#ccc; font-family:Consolas; font-size:11px; background:#1a1a1a;")
        ruler_row.addWidget(self._duration_tc)

        va_layout.addLayout(ruler_row)
        body.addWidget(video_area)

        body.setStretchFactor(0, 0)  # clip list fixed
        body.setStretchFactor(1, 1)  # video stretchy
        root.addWidget(body, 1)

        # --- Control bar ---
        root.addWidget(self._build_controls())

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setStyleSheet("background-color: #252525;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel(self._video_name)
        title.setStyleSheet("color: #e0e0e0; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._info_label)

        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedSize(70, 30)
        close_btn.setStyleSheet(
            "QPushButton { color: #ccc; background:#333; border:1px solid #555; border-radius:3px; }"
            "QPushButton:hover { background:#444; }"
        )
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return bar

    def _build_controls(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setStyleSheet("background-color: #252525;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        btn_style = (
            "QPushButton { color:#ccc; background:#333; border:1px solid #555; "
            "border-radius:3px; padding:4px 10px; font-size:11px; }"
            "QPushButton:hover { background:#444; }"
            "QPushButton:disabled { color:#666; background:#2a2a2a; border-color:#444; }"
        )
        icon_size = QSize(16, 16)

        # Cache play/pause icons for toggling
        self._play_icon = colorize_white_svg(IconLoader.get("play"), _ICON_COLOR)
        self._pause_icon = colorize_white_svg(IconLoader.get("pause"), _ICON_COLOR)

        # Transport
        self._prev_btn = QPushButton()
        self._prev_btn.setIcon(colorize_white_svg(IconLoader.get("arrow_left"), _ICON_COLOR))
        self._prev_btn.setIconSize(icon_size)
        self._prev_btn.setFixedSize(36, 28)
        self._prev_btn.setToolTip("Previous frame (Left)")
        self._prev_btn.setStyleSheet(btn_style)
        layout.addWidget(self._prev_btn)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._play_icon)
        self._play_btn.setIconSize(icon_size)
        self._play_btn.setFixedSize(36, 28)
        self._play_btn.setToolTip("Play / Pause (Space)")
        self._play_btn.setStyleSheet(btn_style)
        layout.addWidget(self._play_btn)

        self._next_btn = QPushButton()
        self._next_btn.setIcon(colorize_white_svg(IconLoader.get("arrow_right"), _ICON_COLOR))
        self._next_btn.setIconSize(icon_size)
        self._next_btn.setFixedSize(36, 28)
        self._next_btn.setToolTip("Next frame (Right)")
        self._next_btn.setStyleSheet(btn_style)
        layout.addWidget(self._next_btn)

        layout.addSpacing(24)

        # In/Out controls
        self._set_in_btn = QPushButton()
        self._set_in_btn.setIcon(colorize_white_svg(IconLoader.get("set_in"), _ICON_COLOR))
        self._set_in_btn.setIconSize(icon_size)
        self._set_in_btn.setFixedSize(36, 28)
        self._set_in_btn.setToolTip("Set in point (I)")
        self._set_in_btn.setStyleSheet(btn_style)
        layout.addWidget(self._set_in_btn)

        self._set_out_btn = QPushButton()
        self._set_out_btn.setIcon(colorize_white_svg(IconLoader.get("set_out"), _ICON_COLOR))
        self._set_out_btn.setIconSize(icon_size)
        self._set_out_btn.setFixedSize(36, 28)
        self._set_out_btn.setToolTip("Set out point (O)")
        self._set_out_btn.setStyleSheet(btn_style)
        layout.addWidget(self._set_out_btn)

        self._reset_btn = QPushButton()
        self._reset_btn.setIcon(colorize_white_svg(IconLoader.get("refresh"), _ICON_COLOR))
        self._reset_btn.setIconSize(icon_size)
        self._reset_btn.setFixedSize(36, 28)
        self._reset_btn.setToolTip("Reset in/out (R)")
        self._reset_btn.setStyleSheet(btn_style)
        layout.addWidget(self._reset_btn)

        layout.addSpacing(24)

        # Export
        self._export_btn = QPushButton()
        self._export_btn.setIcon(colorize_white_svg(IconLoader.get("export"), _ICON_COLOR))
        self._export_btn.setIconSize(icon_size)
        self._export_btn.setFixedSize(36, 28)
        self._export_btn.setToolTip("Export selection as clip (E)")
        self._export_btn.setEnabled(False)
        self._export_btn.setStyleSheet(btn_style)
        layout.addWidget(self._export_btn)

        # Selection duration label
        self._sel_label = QLabel("")
        self._sel_label.setStyleSheet("color: #3A8FB7; font-size: 11px; font-weight: bold;")
        layout.addWidget(self._sel_label)

        layout.addStretch()

        return bar

    # -------------------------------------------------------- signal wiring
    def _connect_signals(self):
        # Transport
        self._prev_btn.clicked.connect(self._step_backward)
        self._play_btn.clicked.connect(self._toggle_play)
        self._next_btn.clicked.connect(self._step_forward)

        # In/Out
        self._set_in_btn.clicked.connect(self._set_in_point)
        self._set_out_btn.clicked.connect(self._set_out_point)
        self._reset_btn.clicked.connect(self._reset_selection)

        # Export
        self._export_btn.clicked.connect(self._export_clip)

        # Ruler
        self._frame_ruler.frame_clicked.connect(self._seek_to_frame)
        self._frame_ruler.frame_dragged.connect(self._seek_to_frame)

    # ------------------------------------------------------------ video I/O
    def _open_video(self):
        info = self._engine.open_video(self._video_path)
        if info is None:
            self._info_label.setText("Failed to open video")
            return

        self._video_info = info
        self._frame_ruler.set_total_frames(info.frame_count)
        self._info_label.setText(
            f"  {info.width}x{info.height}  |  {info.fps:.2f} fps  |  "
            f"{info.frame_count} frames  ({info.duration_ms / 1000:.1f}s)"
        )
        self._duration_tc.setText(self._timecode(info.frame_count - 1))

        # Show first frame
        result = self._engine.get_frame(0)
        if result:
            self._display_frame(result)

    def _display_frame(self, result: FrameResult):
        self._playback.current_frame = result.frame_number
        self._frame_ruler.set_current_frame(result.frame_number)
        self._tc_label.setText(result.timecode)

        pixmap = QPixmap.fromImage(result.image)
        label_size = self._video_label.size()
        scaled = pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._video_label.setPixmap(scaled)

    # -------------------------------------------------------- playback
    def _toggle_play(self):
        if self._playback.is_playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        if not self._video_info:
            return
        self._playback.is_playing = True
        self._play_btn.setIcon(self._pause_icon)
        interval = max(1, int(1000 / self._video_info.fps))
        self._frame_timer.start(interval)

    def _stop_playback(self):
        self._playback.is_playing = False
        self._play_btn.setIcon(self._play_icon)
        self._frame_timer.stop()

    def _on_frame_tick(self):
        if not self._video_info:
            return
        next_frame = self._playback.current_frame + 1
        if next_frame >= self._video_info.frame_count:
            self._stop_playback()
            return
        result = self._engine.get_frame(next_frame)
        if result:
            self._display_frame(result)

    # -------------------------------------------------------- seeking
    def _seek_to_frame(self, frame: int):
        if not self._video_info:
            return
        frame = max(0, min(frame, self._video_info.frame_count - 1))
        result = self._engine.get_frame(frame)
        if result:
            self._display_frame(result)

    def _step_forward(self):
        self._seek_to_frame(self._playback.current_frame + 1)

    def _step_backward(self):
        self._seek_to_frame(self._playback.current_frame - 1)

    def _go_to_start(self):
        self._seek_to_frame(0)

    def _go_to_end(self):
        if self._video_info:
            self._seek_to_frame(self._video_info.frame_count - 1)

    # -------------------------------------------------------- in/out points
    def _set_in_point(self):
        self._selection.set_in(self._playback.current_frame)
        self._sync_ruler_in_out()

    def _set_out_point(self):
        self._selection.set_out(self._playback.current_frame)
        self._sync_ruler_in_out()

    def _reset_selection(self):
        self._selection.clear()
        self._sync_ruler_in_out()

    def _sync_ruler_in_out(self):
        self._frame_ruler.set_in_point(self._selection.in_point)
        self._frame_ruler.set_out_point(self._selection.out_point)
        self._export_btn.setEnabled(self._selection.has_valid_selection)

        if self._selection.has_valid_selection and self._video_info:
            dur = (self._selection.out_point - self._selection.in_point) / self._video_info.fps
            self._sel_label.setText(f"Selection: {dur:.1f}s")
        else:
            self._sel_label.setText("")

    # -------------------------------------------------------- export
    def _export_clip(self):
        if not self._selection.has_valid_selection or not self._video_info:
            return

        was_playing = self._playback.is_playing
        if was_playing:
            self._stop_playback()

        ok, msg, path = self._export_manager.export_clip(
            source_path=self._video_path,
            in_frame=self._selection.in_point,
            out_frame=self._selection.out_point,
            fps=self._video_info.fps,
            video_name=self._video_name,
        )

        if ok and path:
            dur = (self._selection.out_point - self._selection.in_point) / self._video_info.fps
            clip = ExportedClip(
                path=path,
                in_frame=self._selection.in_point,
                out_frame=self._selection.out_point,
                duration_seconds=dur,
                filename=path.name,
            )
            self._clip_list.add_clip(clip)

        # Notify user
        if ok:
            self._sel_label.setText(msg)
        else:
            QMessageBox.warning(self, "Export Failed", msg)

    # -------------------------------------------------------- keyboard
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key == Qt.Key.Key_Space:
            self._toggle_play()
        elif key == Qt.Key.Key_Left:
            self._step_backward()
        elif key == Qt.Key.Key_Right:
            self._step_forward()
        elif key == Qt.Key.Key_I:
            self._set_in_point()
        elif key == Qt.Key.Key_O:
            self._set_out_point()
        elif key == Qt.Key.Key_R:
            self._reset_selection()
        elif key == Qt.Key.Key_E:
            if self._selection.has_valid_selection:
                self._export_clip()
        elif key == Qt.Key.Key_L:
            self._clip_list.toggle_collapse()
        elif key == Qt.Key.Key_Home:
            self._go_to_start()
        elif key == Qt.Key.Key_End:
            self._go_to_end()
        elif key == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    # -------------------------------------------------------- helpers
    def _timecode(self, frame: int) -> str:
        if not self._video_info or self._video_info.fps <= 0:
            return "00:00:00:00"
        fps = self._video_info.fps
        total_seconds = frame / fps
        h = int(total_seconds // 3600)
        m = int((total_seconds % 3600) // 60)
        s = int(total_seconds % 60)
        f = int(frame % fps)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    def closeEvent(self, event):
        self._stop_playback()
        self._engine.stop_playback()
        super().closeEvent(event)
