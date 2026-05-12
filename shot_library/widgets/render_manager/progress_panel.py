"""
Progress Panel for Render Queue Manager

Shows render progress with:
- PROGRESS / LOG OUTPUT tabs
- Progress bar
- Frame count, elapsed/remaining time
- Status message
- "On queue completion" dropdown
"""

import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QTextEdit, QComboBox, QFrame, QPushButton, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher
from ...themes.fonts import Fonts, get_font_stylesheet
from PyQt6.QtGui import QPixmap

logger = logging.getLogger(__name__)


class ProgressPanel(QWidget):
    """
    Progress tracking panel with tabs for Progress and Log Output.

    Matches mockup:
    ┌─────────────────────────────────────────────────────────────────────┐
    │ PROGRESS │ LOG OUTPUT              On queue completion: [Do nothing]│
    ├─────────────────────────────────────────────────────────────────────┤
    │ Rendering: shot_010.blend                                           │
    │ ████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                          │
    │ Start frame: 1     125 of 250 frames (50%)           End frame: 250 │
    │ Elapsed: 00:45:30   Last frame: 00:00:22          Remaining: ~00:45 │
    │ Status: Rendering frame 125...                                       │
    └─────────────────────────────────────────────────────────────────────┘
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._current_job_name = ""
        self._frame_start = 0
        self._frame_end = 0
        self._current_frame = 0
        self._start_time: Optional[datetime] = None
        self._output_dir: Optional[Path] = None
        self._output_pattern: str = ""
        self._blender_path: Optional[str] = None
        self._oiiotool_path: Optional[str] = None
        self._exr_temp_dir: Optional[Path] = None

        # File watcher for live preview
        self._file_watcher = QFileSystemWatcher()
        self._file_watcher.directoryChanged.connect(self._on_output_dir_changed)

        # Timer to debounce file updates
        self._preview_update_timer = QTimer()
        self._preview_update_timer.setSingleShot(True)
        self._preview_update_timer.timeout.connect(self._update_preview_image)

        self._setup_ui()

    def _setup_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header row: tab buttons + completion dropdown
        header = QWidget()
        header.setFixedHeight(40)
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 12, 0)
        header_layout.setSpacing(0)

        # Tab buttons (custom, not using QTabWidget's built-in bar)
        self._progress_tab_btn = QPushButton("PROGRESS")
        self._progress_tab_btn.setCheckable(True)
        self._progress_tab_btn.setChecked(True)
        self._progress_tab_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                border-bottom: 2px solid #3A8FB7;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:!checked {
                color: #888;
                border-bottom: 2px solid transparent;
            }
            QPushButton:!checked:hover {
                color: #ccc;
            }
        """)
        self._progress_tab_btn.clicked.connect(lambda: self._switch_tab(0))
        header_layout.addWidget(self._progress_tab_btn)

        self._log_tab_btn = QPushButton("LOG OUTPUT")
        self._log_tab_btn.setCheckable(True)
        self._log_tab_btn.setChecked(False)
        self._log_tab_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                border-bottom: 2px solid #3A8FB7;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:!checked {
                color: #888;
                border-bottom: 2px solid transparent;
            }
            QPushButton:!checked:hover {
                color: #ccc;
            }
        """)
        self._log_tab_btn.clicked.connect(lambda: self._switch_tab(1))
        header_layout.addWidget(self._log_tab_btn)

        header_layout.addStretch()

        # On queue completion dropdown (in header row)
        completion_label = QLabel("On queue completion:")
        completion_label.setStyleSheet("color: #888;")
        header_layout.addWidget(completion_label)

        header_layout.addSpacing(8)

        self._completion_combo = QComboBox()
        self._completion_combo.addItems(["Do nothing", "Close application", "Shutdown computer", "Sleep"])
        self._completion_combo.setStyleSheet("""
            QComboBox {
                background-color: #3A3A3A;
                color: white;
                border: 1px solid #404040;
                border-radius: 0px;
                padding: 4px 12px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #3A8FB7;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #3A3A3A;
                color: white;
                border: 1px solid #404040;
                selection-background-color: #3A8FB7;
            }
        """)
        header_layout.addWidget(self._completion_combo)

        layout.addWidget(header)

        # Stacked widget for tab content
        self._tab_stack = QStackedWidget()
        self._tab_stack.setStyleSheet("background-color: #1a1a1a;")

        # Progress tab
        progress_widget = QWidget()
        progress_main_layout = QHBoxLayout(progress_widget)
        progress_main_layout.setContentsMargins(12, 12, 12, 12)
        progress_main_layout.setSpacing(12)

        # Left side: progress info
        progress_info = QWidget()
        progress_layout = QVBoxLayout(progress_info)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)

        # Rendering label
        self._rendering_label = QLabel("Rendering:")
        self._rendering_label.setStyleSheet("color: #888; font-size: 12px;")
        progress_layout.addWidget(self._rendering_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2D2D2D;
                border: none;
                border-radius: 0px;
                height: 8px;
            }
            QProgressBar::chunk {
                background-color: #3A8FB7;
                border-radius: 0px;
            }
        """)
        progress_layout.addWidget(self._progress_bar)

        # Frame info row
        frame_row = QHBoxLayout()
        self._start_frame_label = QLabel("Start frame: 0")
        self._start_frame_label.setStyleSheet("color: #888;")
        frame_row.addWidget(self._start_frame_label)

        frame_row.addStretch()

        self._frame_count_label = QLabel("0 of 0 frames (0%)")
        self._frame_count_label.setStyleSheet("color: white;")
        self._frame_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_row.addWidget(self._frame_count_label)

        frame_row.addStretch()

        self._end_frame_label = QLabel("End frame: 0")
        self._end_frame_label.setStyleSheet("color: #888;")
        frame_row.addWidget(self._end_frame_label)

        progress_layout.addLayout(frame_row)

        # Time info row
        time_row = QHBoxLayout()
        self._elapsed_label = QLabel("Elapsed: 00:00:00")
        self._elapsed_label.setStyleSheet("color: #888;")
        time_row.addWidget(self._elapsed_label)

        time_row.addStretch()

        self._last_frame_label = QLabel("Last frame: 00:00:00")
        self._last_frame_label.setStyleSheet("color: #888;")
        time_row.addWidget(self._last_frame_label)

        time_row.addStretch()

        self._remaining_label = QLabel("Remaining: 00:00:00")
        self._remaining_label.setStyleSheet("color: #888;")
        time_row.addWidget(self._remaining_label)

        progress_layout.addLayout(time_row)

        # Status row
        self._status_label = QLabel("Status: waiting for render job.")
        self._status_label.setStyleSheet("color: #888;")
        progress_layout.addWidget(self._status_label)

        progress_layout.addStretch()

        progress_main_layout.addWidget(progress_info, 1)

        # Right side: live preview thumbnail (borderless, integrated)
        self._preview_frame = QFrame()
        self._preview_frame.setMinimumWidth(250)
        self._preview_frame.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
            }
        """)
        preview_frame_layout = QVBoxLayout(self._preview_frame)
        preview_frame_layout.setContentsMargins(0, 0, 0, 0)

        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("""
            QLabel {
                background-color: #0d0d0d;
                color: #444;
                font-size: 11px;
            }
        """)
        self._preview_label.setText("No preview")
        self._preview_label.setScaledContents(False)
        preview_frame_layout.addWidget(self._preview_label)

        progress_main_layout.addWidget(self._preview_frame, 1)  # Give it stretch

        self._tab_stack.addWidget(progress_widget)

        # Log output tab
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(8, 8, 8, 8)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a;
                color: #888;
                border: none;
                font-family: monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self._log_output)

        self._tab_stack.addWidget(log_widget)

        layout.addWidget(self._tab_stack)

    def _switch_tab(self, index: int):
        """Switch between Progress and Log tabs."""
        self._tab_stack.setCurrentIndex(index)
        self._progress_tab_btn.setChecked(index == 0)
        self._log_tab_btn.setChecked(index == 1)

    def set_job(self, job_name: str, frame_start: int, frame_end: int,
                 output_dir: Optional[str] = None, output_pattern: str = "",
                 blender_path: Optional[str] = None):
        """Set current job info."""
        self._blender_path = blender_path
        self._current_job_name = job_name
        self._frame_start = frame_start
        self._frame_end = frame_end
        self._current_frame = frame_start
        self._start_time = datetime.now()

        self._rendering_label.setText(f"Rendering: {job_name}")
        self._start_frame_label.setText(f"Start frame: {frame_start}")
        self._end_frame_label.setText(f"End frame: {frame_end}")
        self._status_label.setText(f"Status: Starting render...")

        self._progress_bar.setValue(0)
        self._frame_count_label.setText(f"0 of {frame_end - frame_start + 1} frames (0%)")

        # Create temp folder for EXR→PNG conversions
        self._cleanup_exr_temp()
        self._exr_temp_dir = Path(tempfile.mkdtemp(prefix="exr_preview_"))

        # Setup preview watching
        self._clear_preview()
        if output_dir:
            self._output_dir = Path(output_dir)
            self._output_pattern = output_pattern
            self._start_watching_output()

    def set_progress(self, current_frame: int, total_frames: int):
        """Update progress."""
        self._current_frame = current_frame

        # Calculate progress
        frames_done = current_frame - self._frame_start + 1
        percent = int((frames_done / total_frames) * 100) if total_frames > 0 else 0

        self._progress_bar.setValue(percent)
        self._frame_count_label.setText(f"{frames_done} of {total_frames} frames ({percent}%)")
        self._status_label.setText(f"Status: Rendering frame {current_frame}...")

        # Update time estimates
        if self._start_time:
            elapsed = datetime.now() - self._start_time
            self._elapsed_label.setText(f"Elapsed: {self._format_time(elapsed)}")

            if frames_done > 0:
                # Estimate remaining time
                time_per_frame = elapsed.total_seconds() / frames_done
                frames_remaining = total_frames - frames_done
                remaining_seconds = time_per_frame * frames_remaining
                remaining = timedelta(seconds=remaining_seconds)
                self._remaining_label.setText(f"Remaining: ~{self._format_time(remaining)}")

                # Last frame time
                self._last_frame_label.setText(f"Last frame: {self._format_time(timedelta(seconds=time_per_frame))}")

        # Force UI repaint to ensure progress bar updates immediately
        self._progress_bar.repaint()

    def set_completed(self, success: bool, message: str = ""):
        """Mark render as completed."""
        if success:
            self._status_label.setText("Status: Render completed")
            self._status_label.setStyleSheet("color: #27ae60;")
            self._progress_bar.setValue(100)
        else:
            self._status_label.setText(f"Status: Render failed - {message}")
            self._status_label.setStyleSheet("color: #e74c3c;")

        self._remaining_label.setText("Remaining: 00:00:00")
        # Note: Don't clean up temp folder here - render_service may still need it for proxy generation

    def reset(self):
        """Reset to idle state."""
        self._current_job_name = ""
        self._frame_start = 0
        self._frame_end = 0
        self._current_frame = 0
        self._start_time = None

        self._rendering_label.setText("Rendering:")
        self._start_frame_label.setText("Start frame: 0")
        self._end_frame_label.setText("End frame: 0")
        self._frame_count_label.setText("0 of 0 frames (0%)")
        self._elapsed_label.setText("Elapsed: 00:00:00")
        self._last_frame_label.setText("Last frame: 00:00:00")
        self._remaining_label.setText("Remaining: 00:00:00")
        self._status_label.setText("Status: waiting for render job.")
        self._status_label.setStyleSheet("color: #888;")
        self._progress_bar.setValue(0)

        # Clear preview and clean up temp folder
        self._clear_preview()
        self._cleanup_exr_temp()

    def append_log(self, text: str):
        """Append text to log output."""
        self._log_output.append(text)
        # Auto-scroll to bottom
        scrollbar = self._log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self):
        """Clear log output."""
        self._log_output.clear()

    def get_completion_action(self) -> str:
        """Get selected completion action."""
        return self._completion_combo.currentText()

    def _format_time(self, td: timedelta) -> str:
        """Format timedelta as HH:MM:SS."""
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _cleanup_exr_temp(self):
        """Clean up the persistent EXR temp folder."""
        if self._exr_temp_dir and self._exr_temp_dir.exists():
            shutil.rmtree(self._exr_temp_dir, ignore_errors=True)
        self._exr_temp_dir = None

    def get_exr_temp_dir(self) -> Optional[Path]:
        """Get the temp folder containing converted EXR PNGs (for proxy generation)."""
        return self._exr_temp_dir

    def _find_oiiotool(self) -> Optional[str]:
        """Find oiiotool executable in assets/bin/ or system PATH."""
        if self._oiiotool_path:
            return self._oiiotool_path

        # Check bundled location: assets/bin/oiiotool.exe
        module_dir = Path(__file__).parent.parent.parent.parent
        bundled = module_dir / "assets" / "bin" / "oiiotool.exe"
        if bundled.exists():
            self._oiiotool_path = str(bundled)
            return self._oiiotool_path

        # Try system PATH
        try:
            result = subprocess.run(['oiiotool', '--version'], capture_output=True, timeout=5)
            if result.returncode == 0:
                self._oiiotool_path = 'oiiotool'
                return self._oiiotool_path
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return None

    def _is_file_complete(self, file_path: Path) -> bool:
        """Check if file is complete (not still being written)."""
        try:
            # Check if file size is stable over 100ms
            import time
            size1 = file_path.stat().st_size
            time.sleep(0.1)
            size2 = file_path.stat().st_size
            return size1 == size2 and size1 > 0
        except OSError:
            return False

    # ==================== Live Preview ====================

    def _start_watching_output(self):
        """Start watching the output directory for new frames."""
        if not self._output_dir:
            return

        # Create output dir if needed
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Clear previous watches
        watched = self._file_watcher.directories()
        if watched:
            self._file_watcher.removePaths(watched)

        # Watch the output directory
        self._file_watcher.addPath(str(self._output_dir))

    def _stop_watching_output(self):
        """Stop watching the output directory."""
        watched = self._file_watcher.directories()
        if watched:
            self._file_watcher.removePaths(watched)

    def _on_output_dir_changed(self, path: str):
        """Handle output directory change - debounce and update preview."""
        # Debounce rapid file system events
        self._preview_update_timer.start(100)

    def _update_preview_image(self):
        """Update the preview with the latest rendered frame."""
        if not self._output_dir or not self._output_dir.exists():
            return

        # Find the most recent image file
        latest_file = None
        latest_mtime = 0

        # Supported image extensions (all common render formats)
        extensions = ['*.png', '*.jpg', '*.jpeg', '*.exr', '*.tiff', '*.tif', '*.bmp', '*.tga', '*.dpx', '*.hdr']

        for ext in extensions:
            for img_file in self._output_dir.glob(ext):
                try:
                    mtime = img_file.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        latest_file = img_file
                except OSError:
                    continue

        if latest_file:
            self._load_preview_image(latest_file)

    def _load_preview_image(self, image_path: Path):
        """Load and display an image in the preview."""
        try:
            # Formats that need FFmpeg conversion (HDR/linear formats)
            hdr_formats = {'.exr', '.hdr', '.dpx'}
            suffix = image_path.suffix.lower()

            if suffix in hdr_formats:
                # Use FFmpeg to convert HDR image to temp PNG for preview
                pixmap = self._convert_hdr_to_preview(image_path)
                if pixmap is None:
                    self._preview_label.setText(f"{suffix.upper()[1:]}: {image_path.name}")
                    return
            else:
                # Load the image directly (PNG, JPEG, TGA, TIFF, BMP)
                pixmap = QPixmap(str(image_path))

            if pixmap.isNull():
                self._preview_label.setText(f"Loading...")
                return

            # Scale to fit preview label while maintaining aspect ratio
            label_size = self._preview_label.size()
            max_w = max(label_size.width(), 200)
            max_h = max(label_size.height(), 150)

            scaled = pixmap.scaled(
                max_w, max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self._preview_label.setPixmap(scaled)
            self._preview_label.setToolTip(image_path.name)

        except Exception:
            logger.warning("Preview load failed for %s", image_path, exc_info=True)
            self._preview_label.setText(f"Preview error")

    def _convert_hdr_to_preview(self, image_path: Path) -> Optional[QPixmap]:
        """
        Convert HDR image (EXR) to PNG using oiiotool for preview.

        Args:
            image_path: Path to HDR image

        Returns:
            QPixmap or None if conversion failed
        """
        if image_path.suffix.lower() != '.exr':
            return None

        # Check if file is complete (not still being written by Blender)
        if not self._is_file_complete(image_path):
            return None

        oiiotool = self._find_oiiotool()
        if not oiiotool or not self._exr_temp_dir:
            return None

        # Output PNG in temp folder
        png_path = self._exr_temp_dir / f"{image_path.stem}.png"

        # Return cached if already converted
        if png_path.exists():
            pixmap = QPixmap(str(png_path))
            if not pixmap.isNull():
                if pixmap.width() > 400:
                    pixmap = pixmap.scaledToWidth(400, Qt.TransformationMode.SmoothTransformation)
                return pixmap

        try:
            cmd = [oiiotool, str(image_path), '--tocolorspace', 'sRGB', '-o', str(png_path)]
            result = subprocess.run(cmd, capture_output=True, timeout=30)

            if result.returncode == 0 and png_path.exists():
                pixmap = QPixmap(str(png_path))
                if not pixmap.isNull():
                    if pixmap.width() > 400:
                        pixmap = pixmap.scaledToWidth(400, Qt.TransformationMode.SmoothTransformation)
                    return pixmap
        except Exception:
            logger.warning("oiiotool HDR→PNG conversion failed for %s", image_path, exc_info=True)

        return None

    def _clear_preview(self):
        """Clear the preview display."""
        self._preview_label.clear()
        self._preview_label.setText("No preview")
        self._preview_label.setToolTip("")
        self._stop_watching_output()
        self._output_dir = None
        self._output_pattern = ""


__all__ = ['ProgressPanel']
