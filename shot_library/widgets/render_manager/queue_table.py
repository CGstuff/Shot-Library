"""
Queue Table for Render Queue Manager

Shows the list of queued render jobs with columns:
Project | Status | Scene | Camera | Render Layer | Frames
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QCheckBox, QComboBox, QAbstractItemView, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from ...themes.fonts import Fonts, get_font_stylesheet
from PyQt6.QtGui import QColor, QIcon

from ...services.blender_render_service import BlendFileInfo
from ...utils.icon_loader import IconLoader

logger = logging.getLogger(__name__)


class ReorderableTableWidget(QTableWidget):
    """QTableWidget with drag-and-drop row reordering support."""

    rows_reordered = pyqtSignal(int, int)  # Emitted after rows are reordered (from_row, to_row)

    def dropEvent(self, event):
        """Handle drop event for row reordering."""
        if event.source() == self:
            # Get the row being dragged
            selected_row = self.currentRow()
            if selected_row < 0:
                event.ignore()
                return

            # Get drop position
            drop_row = self.rowAt(event.position().toPoint().y())
            if drop_row < 0:
                drop_row = self.rowCount() - 1

            if selected_row == drop_row:
                event.ignore()
                return

            # Emit signal with from/to rows - let parent handle the actual move
            # This avoids widget destruction issues
            self.rows_reordered.emit(selected_row, drop_row)
            event.accept()
        else:
            event.ignore()


class QueueTable(QWidget):
    """
    Table showing queued render jobs.

    Matches mockup layout:
    [Enable] [Refresh] Project | Status | Scene | Camera | Render Layer | Frames [Warn] [X] [Menu]
    """

    job_selected = pyqtSignal(str)          # job_id
    job_removed = pyqtSignal(str)           # job_id
    job_toggled = pyqtSignal(str, bool)     # job_id, enabled
    jobs_reordered = pyqtSignal(list)       # list of job_ids in new order
    add_files_requested = pyqtSignal()
    refresh_job_requested = pyqtSignal(str) # job_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._jobs: Dict[str, Dict] = {}  # job_id -> job_info
        self._blend_infos: Dict[str, BlendFileInfo] = {}  # job_id -> blend_info

        self._setup_ui()

    def _setup_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Table (using custom reorderable table)
        self._table = ReorderableTableWidget()
        self._table.setColumnCount(8)
        self._table.rows_reordered.connect(self._on_row_moved)
        self._table.setHorizontalHeaderLabels([
            "", "Project", "Status", "Scene", "Camera", "Render Layer", "Frames", ""
        ])

        # Column sizing - Project column stretches to fill width
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)  # Don't stretch last column (it's the remove button)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)       # Checkbox + refresh
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)     # Project stretches to fill
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)       # Status
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)       # Scene
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)       # Camera
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)       # Render Layer
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)       # Frames
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)       # Remove button

        self._table.setColumnWidth(0, 100)  # Checkbox + refresh (wider)
        self._table.setColumnWidth(2, 80)   # Status
        self._table.setColumnWidth(3, 100)  # Scene
        self._table.setColumnWidth(4, 120)  # Camera
        self._table.setColumnWidth(5, 120)  # Render Layer
        self._table.setColumnWidth(6, 80)   # Frames
        self._table.setColumnWidth(7, 60)   # Remove button (wider)

        # Set row height for better spacing
        self._table.verticalHeader().setDefaultSectionSize(44)
        self._table.verticalHeader().setVisible(False)

        # Selection behavior
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # Enable drag-and-drop reordering
        self._table.setDragEnabled(True)
        self._table.setAcceptDrops(True)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._table.setDropIndicatorShown(True)
        self._table.setDefaultDropAction(Qt.DropAction.MoveAction)

        # Modern clean styling
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                color: #cccccc;
                border: none;
                gridline-color: transparent;
                font-size: 13px;
                outline: none;
            }
            QTableCornerButton::section {
                background-color: #1a1a1a;
                border: none;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #666666;
                padding: 12px 8px;
                border: none;
                border-bottom: 1px solid #333;
                font-size: 12px;
                font-weight: normal;
            }
            QTableWidget::item {
                padding: 8px 4px;
                border: none;
                border-bottom: 1px solid #252525;
            }
            QTableWidget::item:selected {
                background-color: #2a4a5a;
                color: #ffffff;
            }
            QTableWidget::item:focus {
                background-color: #2a4a5a;
                outline: none;
            }
        """)

        layout.addWidget(self._table, 1)

        # Add files button - subtle modern style
        add_btn = QPushButton("+ Add Blend File")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #666666;
                border: 1px dashed #333333;
                border-radius: 0px;
                padding: 14px;
                font-size: 13px;
            }
            QPushButton:hover {
                color: #3A8FB7;
                border-color: #3A8FB7;
                background-color: rgba(58, 143, 183, 0.1);
            }
        """)
        add_btn.clicked.connect(self.add_files_requested.emit)
        layout.addWidget(add_btn)

    def _get_modern_combo_style(self) -> str:
        """Return modern borderless combobox stylesheet."""
        return """
            QComboBox {
                background-color: transparent;
                color: #cccccc;
                border: none;
                padding: 4px 20px 4px 8px;
                font-size: 13px;
            }
            QComboBox:hover {
                color: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                width: 0px;
                height: 0px;
                background: transparent;
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #252525;
                color: #cccccc;
                border: 1px solid #333333;
                selection-background-color: #3A8FB7;
                selection-color: white;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 12px;
                min-height: 24px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #333333;
            }
        """

    def add_job(self, job_id: str, job_info: Dict, blend_info: Optional[BlendFileInfo] = None):
        """Add a job to the table."""
        self._jobs[job_id] = job_info
        if blend_info:
            self._blend_infos[job_id] = blend_info

        row = self._table.rowCount()
        self._table.insertRow(row)

        # Checkbox + refresh button
        toggle_widget = QWidget()
        toggle_widget.setStyleSheet("background-color: transparent;")
        toggle_layout = QHBoxLayout(toggle_widget)
        toggle_layout.setContentsMargins(12, 0, 8, 0)
        toggle_layout.setSpacing(10)

        # Sharp square checkbox (no border radius)
        enable_checkbox = QCheckBox()
        enable_checkbox.setChecked(True)
        enable_checkbox.setStyleSheet("""
            QCheckBox {
                spacing: 0px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 0px;
                border: 2px solid #404040;
                background-color: transparent;
            }
            QCheckBox::indicator:checked {
                background-color: #3A8FB7;
                border-color: #3A8FB7;
            }
            QCheckBox::indicator:unchecked:hover {
                border-color: #3A8FB7;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #4A9FC7;
                border-color: #4A9FC7;
            }
        """)
        enable_checkbox.stateChanged.connect(
            lambda state, jid=job_id: self.job_toggled.emit(jid, state == Qt.CheckState.Checked.value)
        )
        toggle_layout.addWidget(enable_checkbox)

        # Refresh button (subtle)
        refresh_btn = QPushButton()
        refresh_btn.setIcon(QIcon(IconLoader.get("refresh")))
        refresh_btn.setIconSize(QSize(18, 18))
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Retry render")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #333333;
            }
        """)
        refresh_btn.clicked.connect(lambda checked, jid=job_id: self.refresh_job_requested.emit(jid))
        toggle_layout.addWidget(refresh_btn)
        self._table.setCellWidget(row, 0, toggle_widget)

        # Project name (with warning icon if no camera)
        project_name = Path(job_info['blend_file']).name
        has_camera = blend_info and blend_info.active_camera

        if not has_camera:
            # Show warning icon and tooltip
            project_widget = QWidget()
            project_layout = QHBoxLayout(project_widget)
            project_layout.setContentsMargins(4, 0, 4, 0)
            project_layout.setSpacing(4)

            warning_label = QLabel("⚠")
            warning_label.setStyleSheet("color: #f39c12; font-size: 14px;")
            warning_label.setToolTip("No camera in scene - render will fail!")
            project_layout.addWidget(warning_label)

            name_label = QLabel(project_name)
            name_label.setStyleSheet("color: white;")
            project_layout.addWidget(name_label, 1)

            self._table.setCellWidget(row, 1, project_widget)
            # Still need item for job_id storage
            project_item = QTableWidgetItem()
            project_item.setData(Qt.ItemDataRole.UserRole, job_id)
            self._table.setItem(row, 1, project_item)
        else:
            project_item = QTableWidgetItem(project_name)
            project_item.setData(Qt.ItemDataRole.UserRole, job_id)
            self._table.setItem(row, 1, project_item)

        # Status
        status_item = QTableWidgetItem(job_info.get('status', 'Ready').capitalize())
        self._update_status_color(status_item, job_info.get('status', 'pending'))
        self._table.setItem(row, 2, status_item)

        # Scene dropdown - modern borderless style
        scene_combo = QComboBox()
        scene_combo.setStyleSheet(self._get_modern_combo_style())
        scene_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        if blend_info and blend_info.scenes:
            scene_combo.addItems(blend_info.scenes)
            if blend_info.active_scene:
                idx = scene_combo.findText(blend_info.active_scene)
                if idx >= 0:
                    scene_combo.setCurrentIndex(idx)
        else:
            scene_combo.addItem("Scene")
        self._table.setCellWidget(row, 3, scene_combo)

        # Camera dropdown - modern borderless style
        camera_combo = QComboBox()
        camera_combo.setStyleSheet(self._get_modern_combo_style())
        camera_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        camera_combo.addItem("All Enabled")
        if blend_info and blend_info.cameras:
            camera_combo.addItems(blend_info.cameras)
        self._table.setCellWidget(row, 4, camera_combo)

        # Render Layer dropdown - modern borderless style
        layer_combo = QComboBox()
        layer_combo.setStyleSheet(self._get_modern_combo_style())
        layer_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        layer_combo.addItem("All Enabled")
        self._table.setCellWidget(row, 5, layer_combo)

        # Frames
        frames_text = f"{job_info.get('frame_start', 1)}-{job_info.get('frame_end', 250)}"
        frames_item = QTableWidgetItem(frames_text)
        self._table.setItem(row, 6, frames_item)

        # Remove button only (refresh moved to column 0)
        action_widget = QWidget()
        action_widget.setStyleSheet("background-color: transparent;")
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 0, 4, 0)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Simple X button
        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setToolTip("Remove from queue")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover {
                color: #E74C3C;
            }
        """)
        remove_btn.clicked.connect(lambda: self._remove_job(job_id))
        action_layout.addWidget(remove_btn)

        self._table.setCellWidget(row, 7, action_widget)

    def update_job_status(self, job_id: str, status: str, progress: int = 0):
        """Update job status in table."""
        row = self._find_row_by_job_id(job_id)
        if row < 0:
            return

        if job_id in self._jobs:
            self._jobs[job_id]['status'] = status
            self._jobs[job_id]['progress'] = progress

        status_text = status.capitalize()
        if status == "rendering" and progress > 0:
            status_text = f"{progress}%"

        status_item = self._table.item(row, 2)
        if status_item:
            status_item.setText(status_text)
            self._update_status_color(status_item, status)

    def _update_status_color(self, item: QTableWidgetItem, status: str):
        """Update status item color based on status."""
        colors = {
            "pending": "#888",
            "ready": "#888",
            "rendering": "#3498db",
            "completed": "#27ae60",
            "failed": "#e74c3c",
            "cancelled": "#888",
        }
        color = colors.get(status.lower(), "#888")
        item.setForeground(QColor(color))

    def _remove_job(self, job_id: str):
        """Remove a job from the table."""
        logger.info(f"[REMOVE] Starting remove for job_id={job_id}")
        t0 = time.perf_counter()

        row = self._find_row_by_job_id(job_id)
        logger.info(f"[REMOVE] Found row={row} in {(time.perf_counter()-t0)*1000:.1f}ms")

        if row >= 0:
            # Remove from UI immediately (non-blocking)
            t1 = time.perf_counter()
            self._table.removeRow(row)
            logger.info(f"[REMOVE] removeRow() took {(time.perf_counter()-t1)*1000:.1f}ms")

            t2 = time.perf_counter()
            if job_id in self._jobs:
                del self._jobs[job_id]
            if job_id in self._blend_infos:
                del self._blend_infos[job_id]
            logger.info(f"[REMOVE] Dict cleanup took {(time.perf_counter()-t2)*1000:.1f}ms")

            # Emit signal after UI update (service cleanup happens async)
            logger.info(f"[REMOVE] About to emit job_removed signal via QTimer")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._emit_job_removed(job_id))

        logger.info(f"[REMOVE] _remove_job() total: {(time.perf_counter()-t0)*1000:.1f}ms")

    def _emit_job_removed(self, job_id: str):
        """Emit job_removed signal (called from QTimer)."""
        logger.info(f"[REMOVE] Emitting job_removed signal for {job_id}")
        t0 = time.perf_counter()
        self.job_removed.emit(job_id)
        logger.info(f"[REMOVE] Signal emission took {(time.perf_counter()-t0)*1000:.1f}ms")

    def _find_row_by_job_id(self, job_id: str) -> int:
        """Find table row by job ID."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)
            if item and item.data(Qt.ItemDataRole.UserRole) == job_id:
                return row
        return -1

    def _on_selection_changed(self):
        """Handle selection change."""
        selected = self._table.selectedItems()
        if selected:
            row = selected[0].row()
            item = self._table.item(row, 1)
            if item:
                job_id = item.data(Qt.ItemDataRole.UserRole)
                if job_id:
                    self.job_selected.emit(job_id)

    def get_selected_job_id(self) -> Optional[str]:
        """Get currently selected job ID."""
        selected = self._table.selectedItems()
        if selected:
            row = selected[0].row()
            item = self._table.item(row, 1)
            if item:
                return item.data(Qt.ItemDataRole.UserRole)
        return None

    def get_job_info(self, job_id: str) -> Optional[Dict]:
        """Get job info by ID."""
        return self._jobs.get(job_id)

    def get_blend_info(self, job_id: str) -> Optional[BlendFileInfo]:
        """Get blend info by job ID."""
        return self._blend_infos.get(job_id)

    def clear(self):
        """Clear all jobs."""
        self._table.setRowCount(0)
        self._jobs.clear()
        self._blend_infos.clear()

    def _on_row_moved(self, from_row: int, to_row: int):
        """Handle row move via drag-and-drop."""
        logger.info(f"[QUEUE] Moving row {from_row} to {to_row}")

        # Get the job_id of the row being moved
        item = self._table.item(from_row, 1)
        if not item:
            return
        job_id = item.data(Qt.ItemDataRole.UserRole)
        if not job_id:
            return

        # Get all current job IDs in order
        current_order = self.get_job_order()
        if job_id not in current_order:
            return

        # Calculate new order
        current_order.remove(job_id)

        # Adjust to_row if moving down (since we removed an item)
        insert_pos = to_row if from_row > to_row else to_row - 1
        insert_pos = max(0, min(insert_pos, len(current_order)))

        current_order.insert(insert_pos, job_id)

        logger.info(f"[QUEUE] New order: {current_order}")

        # Rebuild the table in new order
        self._rebuild_table(current_order)

        # Emit signal with new order
        self.jobs_reordered.emit(current_order)

    def _rebuild_table(self, job_order: List[str]):
        """Rebuild the table with jobs in specified order."""
        # Store current data
        jobs_backup = dict(self._jobs)
        blend_infos_backup = dict(self._blend_infos)

        # Clear and rebuild
        self._table.setRowCount(0)
        self._jobs.clear()
        self._blend_infos.clear()

        for job_id in job_order:
            if job_id in jobs_backup:
                job_info = jobs_backup[job_id]
                blend_info = blend_infos_backup.get(job_id)
                self.add_job(job_id, job_info, blend_info)

    def get_job_order(self) -> List[str]:
        """Get current job IDs in table order."""
        order = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)  # Project column has job_id in UserRole
            if item:
                job_id = item.data(Qt.ItemDataRole.UserRole)
                if job_id:
                    order.append(job_id)
        return order


__all__ = ['QueueTable']
