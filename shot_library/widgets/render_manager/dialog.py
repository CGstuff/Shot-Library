"""
Render Manager Dialog

Main dialog for the Render Manager - the core feature for starting
and managing Blender headless renders.

Layout matches mockup (Capture.PNG):
┌─────────────────────────────────────────────────┬───────────────────┐
│ Queue Table                                     │                   │
│ - Project | Status | Scene | Camera | Frames   │   Settings Panel  │
│ - [ADD BLEND FILES] button                     │   (per-job)       │
├─────────────────────────────────────────────────┤                   │
│ Progress Panel                                  │                   │
│ - PROGRESS | LOG OUTPUT tabs                   │                   │
│ - Progress bar, elapsed/remaining time         │                   │
└─────────────────────────────────────────────────┴───────────────────┘
"""

import logging
import time
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QPushButton, QFileDialog, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QTimer, QSize
from ...themes.fonts import Fonts, get_font_stylesheet
from PyQt6.QtGui import QIcon, QCursor

from ...utils.icon_loader import IconLoader

from ...services.blender_render_service import get_blender_render_service, BlendFileInfo
from ...services.render_service import get_render_service
from .queue_table import QueueTable
from .progress_panel import ProgressPanel
from .settings_panel import SettingsPanel

logger = logging.getLogger(__name__)


class RenderQueueDialog(QDialog):
    """
    Main Render Manager dialog.

    This is THE CORE FEATURE for starting and managing Blender headless renders.
    Users queue .blend files, the system renders them sequentially via Blender CLI.
    """

    def __init__(self, shots: Optional[List] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # shots parameter kept for backwards compatibility but not used
        # The queue manager lets users add .blend files directly
        self._shots = shots or []

        self._blender_service = get_blender_render_service()
        self._render_service = get_render_service()

        # Sync blender path to render service for EXR proxy generation
        if self._blender_service._blender_path:
            self._render_service.set_blender_path(self._blender_service._blender_path)

        self._setup_window()
        self._setup_ui()
        self._connect_signals()

        # Reload queue from current project and load jobs
        self._blender_service.reload_queue()
        QTimer.singleShot(100, self._load_existing_jobs)

    def _setup_window(self):
        """Configure window."""
        self.setWindowTitle("Render Manager")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self.setStyleSheet("""
            QDialog {
                background-color: #0a0a0a;
            }
        """)

    def _setup_ui(self):
        """Create the UI layout matching mockup."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== Header Bar (Render button + Settings) =====
        header_bar = QWidget()
        header_bar.setFixedHeight(44)
        header_bar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333;")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(12)

        # Render button (main action)
        self._start_btn = QPushButton("  Render")
        self._start_btn.setIcon(QIcon(IconLoader.get("play")))
        self._start_btn.setIconSize(QSize(16, 16))
        self._start_btn.setEnabled(False)
        self._start_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                border: none;
                border-radius: 0px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #3A3A3A;
                color: #666;
            }
        """)
        self._start_btn.clicked.connect(self._on_start_queue)
        header_layout.addWidget(self._start_btn)

        # Blender status indicator
        self._blender_label = QLabel()
        self._blender_label.setStyleSheet("font-size: 11px;")
        header_layout.addWidget(self._blender_label)

        header_layout.addStretch()

        # Settings button (for Blender configuration)
        self._settings_btn = QPushButton()
        self._settings_btn.setFixedSize(32, 32)
        self._settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._settings_btn.setToolTip("Configure Blender path")
        try:
            self._settings_btn.setIcon(QIcon(IconLoader.get("settings")))
            self._settings_btn.setIconSize(QSize(18, 18))
        except:
            self._settings_btn.setText("⚙")
        self._settings_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
            }
        """)
        self._settings_btn.clicked.connect(self._on_configure_blender)
        header_layout.addWidget(self._settings_btn)

        main_layout.addWidget(header_bar)

        self._update_blender_status()

        # ===== Main Content Area =====
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Main splitter (left panel | right settings panel)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #333;
                width: 1px;
            }
        """)

        # ===== Left Panel (Queue + Progress) =====
        left_panel = QWidget()
        left_panel.setStyleSheet("background-color: #0a0a0a;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Vertical splitter for queue table and progress
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #333;
                height: 1px;
            }
        """)

        # Queue Table (top)
        self._queue_table = QueueTable()
        left_splitter.addWidget(self._queue_table)

        # Progress Panel (bottom)
        self._progress_panel = ProgressPanel()
        left_splitter.addWidget(self._progress_panel)

        # Set initial sizes (60% queue, 40% progress for larger preview)
        left_splitter.setSizes([400, 300])

        left_layout.addWidget(left_splitter)

        main_splitter.addWidget(left_panel)

        # ===== Right Panel (Settings) =====
        self._settings_panel = SettingsPanel()
        main_splitter.addWidget(self._settings_panel)

        # Set initial sizes (70% left, 30% settings)
        main_splitter.setSizes([900, 350])

        content_layout.addWidget(main_splitter)
        main_layout.addLayout(content_layout)

    def _connect_signals(self):
        """Connect signals."""
        # Queue table signals
        self._queue_table.add_files_requested.connect(self._on_add_files)
        self._queue_table.job_selected.connect(self._on_job_selected)
        self._queue_table.job_removed.connect(self._on_job_removed)
        self._queue_table.jobs_reordered.connect(self._on_jobs_reordered)
        self._queue_table.refresh_job_requested.connect(self._on_refresh_job)

        # Blender service signals
        self._blender_service.job_queued.connect(self._on_job_queued)
        self._blender_service.job_started.connect(self._on_job_started)
        self._blender_service.job_progress.connect(self._on_job_progress)
        self._blender_service.job_completed.connect(self._on_job_completed)
        self._blender_service.job_cancelled.connect(self._on_job_cancelled)
        self._blender_service.queue_changed.connect(self._update_start_button)
        self._blender_service.log_output.connect(self._on_log_output)

        # Settings panel signals
        self._settings_panel.settings_changed.connect(self._on_settings_changed)

    def _load_existing_jobs(self):
        """Load any existing jobs from service (uses cached blend info - no Blender calls)."""
        jobs = self._blender_service.get_all_jobs()
        for job in jobs:
            # Use cached blend info instead of extracting (avoids 3s Blender subprocess per file)
            blend_info = self._blender_service.get_cached_blend_info(job['id'])
            self._queue_table.add_job(job['id'], job, blend_info)

        self._update_start_button()

    def _update_start_button(self):
        """Update start button enabled state."""
        queue = self._blender_service.get_queue()
        has_pending = any(j['status'] == 'pending' for j in queue)
        self._start_btn.setEnabled(has_pending)

    # ==================== Add Files ====================

    def _on_add_files(self):
        """Handle add files request."""
        if not self._blender_service.is_blender_available():
            QMessageBox.warning(
                self,
                "Blender Not Found",
                "Blender is not available. Please install Blender and ensure it's in your PATH."
            )
            return

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Blend Files",
            "",
            "Blender Files (*.blend)"
        )

        for file_path in files:
            self._add_blend_file(Path(file_path))

    def _add_blend_file(self, blend_file: Path):
        """Add a blend file to the queue."""
        # Extract info from blend file
        blend_info = self._blender_service.extract_blend_info(blend_file)

        # Determine output directory (Render/current/)
        shot_folder = blend_file.parent
        output_dir = shot_folder / "Render" / "current"

        # Queue the render
        job_id = self._blender_service.queue_render(
            shot_uuid="",  # Will be linked later if needed
            blend_file=blend_file,
            output_dir=output_dir,
            frame_start=blend_info.frame_start if blend_info else 1,
            frame_end=blend_info.frame_end if blend_info else 250,
        )

        # Add to table
        job_info = self._blender_service.get_job(job_id)
        if job_info:
            self._queue_table.add_job(job_id, job_info, blend_info)

        self._update_start_button()

    # ==================== Job Events ====================

    def _on_job_selected(self, job_id: str):
        """Handle job selection."""
        job_info = self._queue_table.get_job_info(job_id)
        blend_info = self._queue_table.get_blend_info(job_id)

        if job_info:
            self._settings_panel.set_job(job_id, job_info, blend_info)

    def _on_job_removed(self, job_id: str):
        """Handle job removal."""
        logger.info(f"[DIALOG] _on_job_removed called for {job_id}")
        t0 = time.perf_counter()

        t1 = time.perf_counter()
        logger.info(f"[DIALOG] Calling remove_job...")
        self._blender_service.remove_job(job_id)
        logger.info(f"[DIALOG] remove_job took {(time.perf_counter()-t1)*1000:.1f}ms")

        t2 = time.perf_counter()
        logger.info(f"[DIALOG] Calling settings_panel.clear()...")
        self._settings_panel.clear()
        logger.info(f"[DIALOG] settings_panel.clear() took {(time.perf_counter()-t2)*1000:.1f}ms")

        t3 = time.perf_counter()
        logger.info(f"[DIALOG] Calling _update_start_button()...")
        self._update_start_button()
        logger.info(f"[DIALOG] _update_start_button() took {(time.perf_counter()-t3)*1000:.1f}ms")

        logger.info(f"[DIALOG] _on_job_removed total: {(time.perf_counter()-t0)*1000:.1f}ms")

    def _on_jobs_reordered(self, new_order):
        """Handle queue reorder."""
        logger.info(f"[DIALOG] Jobs reordered: {new_order}")
        if isinstance(new_order, list):
            self._blender_service.reorder_queue(new_order)

    def _on_settings_changed(self, job_id: str, overrides: dict):
        """Handle settings panel override changes."""
        if not job_id or not overrides:
            return

        logger.info(f"[DIALOG] Settings changed for job {job_id}: {overrides}")

        # Map settings panel field names to job field names
        field_map = {
            'file_format': 'file_format',
            'resolution_x': 'resolution_x',
            'resolution_y': 'resolution_y',
            'samples': 'samples',
            'render_engine': 'render_engine',
            # Additional render settings
            'resolution_scale': 'resolution_scale',
            'color_mode': 'color_mode',
            'color_depth': 'color_depth',
            'compression': 'compression',
            'film_transparent': 'film_transparent',
            # EXR-specific settings
            'exr_color_depth': 'exr_color_depth',
            'exr_codec': 'exr_codec',
        }

        # Build kwargs for update_job
        update_kwargs = {}
        for panel_name, job_name in field_map.items():
            if panel_name in overrides:
                value = overrides[panel_name]
                # Convert format names if needed
                if panel_name == 'file_format':
                    format_map = {
                        'PNG': 'PNG', 'JPEG': 'JPEG', 'OpenEXR': 'OPEN_EXR',
                        'TIFF': 'TIFF', 'BMP': 'BMP',
                    }
                    value = format_map.get(value, value)
                elif panel_name == 'render_engine':
                    engine_map = {
                        'Eevee': 'BLENDER_EEVEE', 'Cycles': 'CYCLES',
                        'Workbench': 'BLENDER_WORKBENCH',
                    }
                    value = engine_map.get(value, value)
                update_kwargs[job_name] = value

        if update_kwargs:
            self._blender_service.update_job(job_id, **update_kwargs)

    def _on_refresh_job(self, job_id: str):
        """Handle job refresh/retry request."""
        logger.info(f"[DIALOG] Refresh requested for job {job_id}")
        if self._blender_service.retry_job(job_id):
            # Update status in table
            self._queue_table.update_job_status(job_id, "pending")
            self._update_start_button()

    def _on_job_queued(self, job_id: str, job_info: dict):
        """Handle job queued signal."""
        self._update_start_button()

    def _on_job_started(self, job_id: str):
        """Handle job started signal."""
        job = self._blender_service.get_job(job_id)
        if job:
            self._queue_table.update_job_status(job_id, "rendering")

            # Update progress panel with output dir for live preview
            blend_name = Path(job['blend_file']).name
            output_dir = job.get('output_dir', '')
            output_name = job.get('output_name', '')

            self._progress_panel.set_job(
                blend_name,
                job['frame_start'],
                job['frame_end'],
                output_dir=output_dir,
                output_pattern=output_name,
                blender_path=self._blender_service._blender_path
            )

    def _on_job_progress(self, job_id: str, current_frame: int, total_frames: int):
        """Handle job progress signal."""
        job = self._blender_service.get_job(job_id)
        if not job:
            return

        # Calculate progress correctly: frames_done / total_frames
        frame_start = job.get('frame_start', 1)
        frames_done = current_frame - frame_start + 1
        progress = int((frames_done / total_frames) * 100) if total_frames > 0 else 0

        self._queue_table.update_job_status(job_id, "rendering", progress)
        self._progress_panel.set_progress(current_frame, total_frames)

    def _on_log_output(self, text: str):
        """Handle log output from Blender."""
        self._progress_panel.append_log(text)

    def _on_job_completed(self, job_id: str, success: bool):
        """Handle job completed signal."""
        job = self._blender_service.get_job(job_id)

        status = "completed" if success else "failed"
        self._queue_table.update_job_status(job_id, status)

        error_msg = job.get('error_message', '') if job else ''
        self._progress_panel.set_completed(success, error_msg)

        # Auto-generate proxy after successful render
        if success and job:
            output_dir = Path(job.get('output_dir', ''))
            shot_uuid = job.get('shot_uuid', '')
            if output_dir.exists():
                self._progress_panel.append_log("Generating proxy MP4...")
                proxy_path = self._render_service.generate_proxy(shot_uuid, output_dir)
                if proxy_path:
                    self._progress_panel.append_log(f"Proxy created: {proxy_path}")
                else:
                    self._progress_panel.append_log("Proxy generation failed")

        self._update_start_button()

    def _on_job_cancelled(self, job_id: str):
        """Handle job cancelled signal."""
        self._queue_table.update_job_status(job_id, "cancelled")
        self._progress_panel.reset()
        self._update_start_button()

    # ==================== Actions ====================

    def _on_start_queue(self):
        """Start processing the queue."""
        self._blender_service.start_queue()
        self._start_btn.setEnabled(False)

    # ==================== Blender Configuration ====================

    def _update_blender_status(self):
        """Update Blender status label."""
        blender_available = self._blender_service.is_blender_available()
        if blender_available:
            self._blender_label.setText("Blender: Ready")
            self._blender_label.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self._blender_label.setText("Blender: Not configured")
            self._blender_label.setStyleSheet("color: #e74c3c; font-size: 11px;")

    def _on_configure_blender(self):
        """Open dialog to configure Blender path."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Blender Executable",
            "",
            "Blender (blender.exe blender);;All Files (*)"
        )

        if file_path:
            # Set the path in both services
            self._blender_service.set_blender_path(file_path)
            self._render_service.set_blender_path(file_path)

            # Verify it works
            if self._blender_service.is_blender_available():
                self._update_blender_status()
                QMessageBox.information(
                    self,
                    "Blender Configured",
                    f"Blender path set to:\n{file_path}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Invalid Blender Path",
                    f"The selected file does not appear to be a valid Blender executable:\n{file_path}"
                )
                self._update_blender_status()


# Backwards compatibility alias
RenderManagerDialog = RenderQueueDialog

__all__ = ['RenderQueueDialog', 'RenderManagerDialog']
