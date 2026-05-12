"""
Version History Dialog - View and manage animation versions

Features:
- Version table with thumbnails
- Video preview with playback controls
- SyncSketch-style frame ruler timeline
- Review notes panel on right side
- Compare two versions side-by-side
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QApplication, QSizePolicy, QSplitter, QWidget,
    QFrame, QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QObject, QRunnable, QThreadPool, QRectF
from ...themes.fonts import Fonts, get_font_stylesheet
from PyQt6.QtGui import QColor, QPixmap, QImage, QIcon, QFont, QBrush, QKeyEvent

from ...config import Config
from ...services.database_service import get_database_service

logger = logging.getLogger(__name__)
from ...services.notes_database import get_notes_database
from ...services.permissions import DrawoverPermissions
from ...services.drawover_storage import get_drawover_storage, get_drawover_cache
# Analysis Mode imports
from ...services.reference_database import get_reference_database
from ...services.reference_drawover_storage import get_reference_drawover_storage, get_reference_drawover_cache
from ...utils.icon_loader import IconLoader
from ...utils.icon_utils import colorize_white_svg
from ...themes.theme_manager import get_theme_manager
from ...core.lookdev_indexer import LookdevIndexer
from ...core.playblast_indexer import PlayblastIndexer
from ..video_preview_widget import VideoPreviewWidget
from ..frame_ruler_timeline import FrameRulerTimeline
from ..drawover_canvas import DrawoverCanvas, DrawingTool
from ..review_notes_panel import ReviewNotesPanel
from .comparison_widget import ComparisonWidget
from .version_history import AnnotatedExportManager, ReviewNotesManager


# ==================== Async Thumbnail Loading ====================

class ThumbnailSignals(QObject):
    # THREAD SAFETY FIX: Emit QImage from worker thread, convert to QPixmap in main thread
    loaded = pyqtSignal(str, QImage)
    failed = pyqtSignal(str)


class ThumbnailTask(QRunnable):
    """Load thumbnail from image file or extract frame from video file.

    Thread Safety: Returns QImage (not QPixmap) because QPixmap operations
    must only occur in the main/GUI thread. Conversion to QPixmap happens
    in the signal handler on the main thread.
    """

    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}

    def __init__(self, uuid: str, thumbnail_path: str, size: int):
        super().__init__()
        self.uuid = uuid
        self.thumbnail_path = thumbnail_path
        self.size = size
        self.signals = ThumbnailSignals()

    def run(self):
        try:
            path = Path(self.thumbnail_path)
            if not path.exists():
                self.signals.failed.emit(self.uuid)
                return

            # Check if it's a video file - extract frame using cv2
            if path.suffix.lower() in self.VIDEO_EXTENSIONS:
                image = self._extract_video_frame(path)
            else:
                # It's an image file - load directly
                image = self._load_image(path)

            if image and not image.isNull():
                self.signals.loaded.emit(self.uuid, image)
            else:
                self.signals.failed.emit(self.uuid)

        except Exception:
            self.signals.failed.emit(self.uuid)

    def _load_image(self, path: Path) -> Optional[QImage]:
        """Load and scale an image file. Returns QImage for thread safety."""
        image = QImage(str(path))
        if image.isNull():
            return None

        scaled = image.scaled(
            self.size, self.size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        return scaled

    def _extract_video_frame(self, path: Path) -> Optional[QImage]:
        """Extract a frame from video file using cv2. Returns QImage for thread safety."""
        try:
            import cv2

            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                return None

            # Get total frames and seek to middle frame for better thumbnail
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            target_frame = total_frames // 2 if total_frames > 1 else 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return None

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame_rgb.shape[:2]

            # Scale to thumbnail size while keeping aspect ratio
            scale = min(self.size / w, self.size / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            frame_resized = cv2.resize(frame_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Convert to QImage (NOT QPixmap - must happen in main thread)
            h, w = frame_resized.shape[:2]
            bytes_per_line = 3 * w
            qimage = QImage(
                frame_resized.data.tobytes(),
                w, h,
                bytes_per_line,
                QImage.Format.Format_RGB888
            ).copy()  # Copy to own the data since numpy array may be freed
            return qimage

        except ImportError:
            # cv2 not available - try loading as image fallback
            return self._load_image(path)
        except Exception:
            return None


# ==================== Version History Dialog ====================


class VersionHistoryDialog(QDialog):
    """
    Dialog for viewing animation version history with review notes.

    Layout: [Version Table] | [Video + Timeline] | [Notes Panel]
    """

    version_selected = pyqtSignal(str)
    version_set_as_latest = pyqtSignal(str)

    THUMBNAIL_SIZE = 50  # Thumbnails for version list
    TABLE_WIDTH_NORMAL = 380  # Width to fit status/frames
    TABLE_WIDTH_COMPARE = 220

    def __init__(self, version_group_id: str, parent=None, theme_manager=None,
                 shot_folder: Optional[Path] = None, blend_stem: Optional[str] = None,
                 analysis_mode: bool = False, folder_videos: Optional[List[str]] = None,
                 audit_service=None, shot_name: Optional[str] = None):
        super().__init__(parent)

        self._version_group_id = version_group_id
        self._theme_manager = theme_manager
        self._db_service = get_database_service()
        self._audit_service = audit_service
        self._shot_name = shot_name or "Unknown"

        # Analysis Mode setup
        self._analysis_mode = analysis_mode
        self._folder_videos = folder_videos or []
        self._initial_video_path: Optional[str] = None
        self._current_video_path: Optional[str] = None  # Current video path for reference mode

        # Use appropriate database based on mode
        if analysis_mode:
            self._notes_db = get_reference_database()
        else:
            self._notes_db = get_notes_database()

        self._versions: List[Dict[str, Any]] = []
        self._selected_uuid: Optional[str] = None
        self._selected_version_label: Optional[str] = None

        # Shot folder for lookdev indexing
        self._shot_folder = shot_folder
        self._blend_stem = blend_stem

        # Preview mode (playblast, lookdev, or render) - not used in analysis mode
        self._preview_mode = "playblast"
        self._lookdev_indexer = LookdevIndexer() if not analysis_mode else None
        self._playblast_indexer = PlayblastIndexer() if not analysis_mode else None
        self._playblast_versions: List[Any] = []
        self._lookdev_versions: List[Any] = []

        # Compare mode - disabled in analysis mode
        self._compare_mode = False
        self._compare_selections: List[str] = []

        # Thumbnails
        self._thread_pool = QThreadPool.globalInstance()
        self._thumbnail_cache: Dict[str, QPixmap] = {}
        self._pending_thumbnails: Dict[str, QTreeWidgetItem] = {}
        self._hierarchy: Dict[str, Any] = {}  # Hierarchical version data

        # Video state
        self._current_fps: int = 24
        self._total_frames: int = 0

        # Drawover state (always-on mode) - use appropriate storage based on mode
        if analysis_mode:
            self._drawover_storage = get_reference_drawover_storage()
            self._drawover_cache = get_reference_drawover_cache()
        else:
            self._drawover_storage = get_drawover_storage()
            self._drawover_cache = get_drawover_cache()
        self._current_drawover_frame: int = -1
        self._annotation_frames: List[int] = []  # Cached list of frames with annotations

        # Display mode state
        self._hide_annotations = False
        self._hold_enabled = False
        self._ghost_enabled = False
        self._ghost_settings = {
            'before_frames': 2,
            'after_frames': 2,
            'before_color': QColor("#FF5555"),
            'after_color': QColor("#55FF55"),
            'sketches_only': True
        }
        self._strokes_from_hold = False  # Track if strokes are from Hold mode

        # Export manager
        self._export_manager = AnnotatedExportManager(self)

        # Studio Mode state
        self._is_studio_mode: bool = self._notes_db.is_studio_mode()
        self._current_user: str = self._notes_db.get_current_user()
        self._current_user_role: str = self._get_current_user_role()

        # Review notes manager
        self._notes_manager = ReviewNotesManager(
            parent_widget=self,
            notes_db=self._notes_db,
            is_studio_mode=self._is_studio_mode,
            current_user=self._current_user,
            current_user_role=self._current_user_role,
            on_notes_changed=self._on_notes_changed
        )

        self._configure_window()
        self._apply_theme_styles()
        self._build_ui()
        # Load versions based on mode
        if self._analysis_mode:
            self._load_analysis_videos()
        else:
            self._load_playblast_versions()

        # Log focused view to audit trail (Shot Mode only)
        if self._audit_service and not self._analysis_mode:
            from ...services.audit_service import AuditEntityType
            self._audit_service.log_view(
                entity_type=AuditEntityType.SHOT,
                entity_id=self._version_group_id,
                entity_name=self._shot_name
            )

    def _get_current_user_role(self) -> str:
        """Get role of current user."""
        if not self._current_user:
            return 'artist'
        user = self._notes_db.get_user(self._current_user)
        return user.get('role', 'artist') if user else 'artist'

    def _configure_window(self):
        title = "Analyse Footage" if self._analysis_mode else "Shot Lineage"
        self.setWindowTitle(title)
        self.setModal(True)
        # Make it a normal window with min/max/close buttons for proper Windows behavior
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowCloseButtonHint
        )

    def showEvent(self, event):
        """Maximize window when shown for full screen workspace."""
        super().showEvent(event)
        if not self.isMaximized():
            self.showMaximized()

    def _apply_theme_styles(self):
        if not self._theme_manager:
            self.setStyleSheet("""
                QDialog { background-color: #1e1e1e; }
                QLabel { color: #e0e0e0; background-color: transparent; }
                QPushButton {
                    background-color: #3a3a3a;
                    color: #e0e0e0;
                    border: 1px solid #404040;
                    border-radius: 3px;
                    padding: 8px 16px;
                }
                QPushButton:hover { background-color: #4a4a4a; }
                QPushButton:pressed { background-color: #2a2a2a; }
                QPushButton:disabled { background-color: #252525; color: #606060; }
                QTableWidget {
                    background-color: #2a2a2a;
                    color: #e0e0e0;
                    border: 1px solid #404040;
                    gridline-color: #404040;
                    selection-background-color: #3A8FB7;
                }
                QTableWidget::item {
                    padding: 8px;
                    background-color: #2a2a2a;
                    color: #e0e0e0;
                }
                QTableWidget::item:selected {
                    background-color: #3A8FB7;
                    color: #ffffff;
                }
                QTableWidget::item:selected:!active {
                    background-color: #3A8FB7;
                    color: #ffffff;
                }
                QTableWidget::item:hover:!selected { background-color: #3a3a3a; }
                QHeaderView::section {
                    background-color: #505050;
                    color: #ffffff;
                    padding: 8px;
                    border: none;
                    border-right: 1px solid #606060;
                    border-bottom: 1px solid #606060;
                    font-weight: bold;
                }
                QScrollBar:vertical {
                    background-color: #2d2d2d;
                    width: 10px;
                }
                QScrollBar::handle:vertical {
                    background-color: #4a4a4a;
                    border-radius: 5px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #5a5a5a;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QSplitter::handle { background-color: #404040; }
                QSplitter::handle:hover { background-color: #5a5a5a; }
                QSplitter::handle:pressed { background-color: #3A8FB7; }
                QFrame { background-color: transparent; }
            """)

    def _center_over_parent(self):
        if self.parent():
            pg = self.parent().geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + (pg.height() - self.height()) // 2
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                x = max(sg.x(), min(x, sg.x() + sg.width() - self.width()))
                y = max(sg.y() + 30, min(y, sg.y() + sg.height() - self.height()))
            self.move(x, y)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header row with title and PB/LD toggle
        header_layout = QHBoxLayout()

        # Header text changes based on mode
        header_text = "Analyse Footage" if self._analysis_mode else "Shot Lineage"
        header = QLabel(header_text)
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(header)

        header_layout.addStretch()

        # PB/LD/RD toggle buttons with Blender shading icons (hidden in Analysis Mode)
        mode_btn_style = """
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border: 1px solid #666;
            }
            QPushButton:checked {
                background-color: #5b8cc9;
                border: 1px solid #5b8cc9;
            }
        """
        mode_btn_style_rd = """
            QPushButton {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border: 1px solid #666;
            }
            QPushButton:checked {
                background-color: #c97b5b;
                border: 1px solid #c97b5b;
            }
        """

        self._pb_btn = QPushButton()
        self._pb_btn.setFixedSize(32, 28)
        self._pb_btn.setCheckable(True)
        self._pb_btn.setChecked(True)
        self._pb_btn.setToolTip("Show Playblast versions")
        try:
            pb_icon = QIcon(IconLoader.get("shading_solid"))
            self._pb_btn.setIcon(pb_icon)
            self._pb_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._pb_btn.setText("PB")
        self._pb_btn.setStyleSheet(mode_btn_style)
        self._pb_btn.clicked.connect(self._on_pb_mode_clicked)
        header_layout.addWidget(self._pb_btn)

        self._ld_btn = QPushButton()
        self._ld_btn.setFixedSize(32, 28)
        self._ld_btn.setCheckable(True)
        self._ld_btn.setChecked(False)
        self._ld_btn.setToolTip("Show Lookdev versions")
        try:
            ld_icon = QIcon(IconLoader.get("shading_texture"))
            self._ld_btn.setIcon(ld_icon)
            self._ld_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._ld_btn.setText("LD")
        self._ld_btn.setStyleSheet(mode_btn_style)
        self._ld_btn.clicked.connect(self._on_ld_mode_clicked)
        header_layout.addWidget(self._ld_btn)

        self._rd_btn = QPushButton()
        self._rd_btn.setFixedSize(32, 28)
        self._rd_btn.setCheckable(True)
        self._rd_btn.setChecked(False)
        self._rd_btn.setToolTip("Show Render proxy versions")
        try:
            rd_icon = QIcon(IconLoader.get("shading_rendered"))
            self._rd_btn.setIcon(rd_icon)
            self._rd_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._rd_btn.setText("RD")
        self._rd_btn.setStyleSheet(mode_btn_style_rd)
        self._rd_btn.clicked.connect(self._on_rd_mode_clicked)
        header_layout.addWidget(self._rd_btn)

        # Hide PB/LD/RD buttons in Analysis Mode
        if self._analysis_mode:
            self._pb_btn.hide()
            self._ld_btn.hide()
            self._rd_btn.hide()

        layout.addLayout(header_layout)

        self._name_label = QLabel("")
        self._name_label.setStyleSheet("font-size: 13px; color: #888;")
        layout.addWidget(self._name_label)

        # Main splitter: Table | Video | Notes (draggable)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)  # Visible handle for dragging

        # ===== LEFT: Version tree (hierarchical) =====
        self._tree_container = QWidget()
        self._tree_container.setMinimumWidth(self.TABLE_WIDTH_COMPARE)  # Min width when dragged
        tree_layout = QVBoxLayout(self._tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["", "Version", "Status", "Frames"])
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setIconSize(QSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE))
        self._tree.setIndentation(16)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)

        # Apply tree-specific styles (compact padding)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background-color: #2D2D2D;
                color: #FFFFFF;
                border: 1px solid #404040;
            }
            QTreeWidget::item {
                background-color: #2D2D2D;
                color: #FFFFFF;
                padding: 2px 4px;
                margin: 0px;
            }
            QTreeWidget::item:selected {
                background-color: #3A8FB7;
                color: #FFFFFF;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #4A4A4A;
            }
            QTreeWidget::branch {
                background-color: #2D2D2D;
            }
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                border-image: none;
                image: url(:/icons/branch-closed.png);
            }
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {
                border-image: none;
                image: url(:/icons/branch-open.png);
            }
            QHeaderView::section {
                background-color: #4A4A4A;
                color: #FFFFFF;
                padding: 4px 8px;
                border: none;
                border-right: 1px solid #505050;
                border-bottom: 1px solid #505050;
                font-weight: bold;
            }
        """)

        header_view = self._tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(0, self.THUMBNAIL_SIZE + 4)  # Thumbnail column
        self._tree.setColumnWidth(2, 50)  # Status column
        self._tree.setColumnWidth(3, 50)  # Frames column

        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.itemExpanded.connect(self._on_item_expanded)

        tree_layout.addWidget(self._tree)
        self._splitter.addWidget(self._tree_container)

        # ===== CENTER: Video preview + timeline =====
        self._center_widget = QWidget()
        center_layout = QVBoxLayout(self._center_widget)
        center_layout.setContentsMargins(8, 0, 8, 0)
        center_layout.setSpacing(4)

        # Preview header
        preview_header = QHBoxLayout()
        self._preview_info_label = QLabel("Select a version to preview")
        self._preview_info_label.setStyleSheet("font-size: 12px; color: #888;")
        preview_header.addWidget(self._preview_info_label)
        preview_header.addStretch()

        # Annotation toolbar (shown when version is selected - always-on mode)
        from ..annotation_toolbar import AnnotationToolbar, GhostSettingsPopup
        self._annotation_toolbar = AnnotationToolbar()
        self._annotation_toolbar.tool_changed.connect(self._on_tool_selected)
        self._annotation_toolbar.color_changed.connect(self._on_draw_color_changed)
        self._annotation_toolbar.brush_size_changed.connect(self._on_brush_size_changed)
        self._annotation_toolbar.opacity_changed.connect(self._on_opacity_changed)
        self._annotation_toolbar.undo_clicked.connect(self._on_drawover_undo)
        self._annotation_toolbar.redo_clicked.connect(self._on_drawover_redo)
        self._annotation_toolbar.clear_clicked.connect(self._on_drawover_clear)
        self._annotation_toolbar.delete_all_clicked.connect(self._on_drawover_delete_all)
        self._annotation_toolbar.hide()  # Show when version is selected
        center_layout.addWidget(self._annotation_toolbar)

        # Ghost settings popup (shared)
        self._ghost_popup = GhostSettingsPopup(self)
        self._ghost_popup.settings_changed.connect(self._on_ghost_settings_changed)
        self._ghost_popup.ghost_toggled.connect(self._on_ghost_toggled)

        center_layout.addLayout(preview_header)

        # Video preview with drawover overlay (using stacked widget approach)
        from PyQt6.QtWidgets import QStackedLayout
        video_container = QWidget()
        video_container.setMinimumWidth(400)

        # Use a stacked layout with all widgets visible
        self._video_stack = QVBoxLayout(video_container)
        self._video_stack.setContentsMargins(0, 0, 0, 0)
        self._video_stack.setSpacing(0)

        # Create a frame to hold video and drawover
        preview_frame = QFrame()
        preview_frame.setStyleSheet("background: #1e1e1e;")  # Match dialog background
        preview_frame_layout = QVBoxLayout(preview_frame)
        preview_frame_layout.setContentsMargins(0, 0, 0, 0)

        # Video preview
        self._video_preview = VideoPreviewWidget()
        self._video_preview.hide_controls()  # Use our own controls below
        preview_frame_layout.addWidget(self._video_preview, 1)

        self._video_stack.addWidget(preview_frame, 1)

        # Drawover canvas (overlay - will be positioned over video)
        self._drawover_canvas = DrawoverCanvas()
        self._drawover_canvas.set_author(self._current_user)
        self._drawover_canvas.drawing_started.connect(self._on_drawing_started)
        self._drawover_canvas.drawing_modified.connect(self._on_drawover_modified)
        self._drawover_canvas.drawing_finished.connect(self._on_drawing_finished)
        self._drawover_canvas.read_only = True
        self._drawover_canvas.set_tool(DrawingTool.NONE)
        self._drawover_canvas.hide()  # Hidden until version selected

        center_layout.addWidget(video_container, 1)

        # Timeline controls row: Play | Loop | Frame Ruler
        timeline_row = QHBoxLayout()
        timeline_row.setSpacing(4)
        timeline_row.setContentsMargins(0, 0, 0, 0)

        # Load icons (same as video preview widget)
        self._load_playback_icons()

        # Play/pause button (matches video preview widget style)
        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._play_icon)
        self._play_btn.setIconSize(QSize(24, 24))
        self._play_btn.setFixedSize(36, 36)
        self._play_btn.setProperty("media", "true")
        self._play_btn.setToolTip("Play/Pause")
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.clicked.connect(self._on_play_clicked)
        timeline_row.addWidget(self._play_btn)

        # Loop button (matches video preview widget style)
        self._loop_btn = QPushButton()
        self._loop_btn.setIcon(self._loop_icon)
        self._loop_btn.setIconSize(QSize(24, 24))
        self._loop_btn.setFixedSize(36, 36)
        self._loop_btn.setProperty("media", "true")
        self._loop_btn.setCheckable(True)
        self._loop_btn.setChecked(True)
        self._loop_btn.setToolTip("Toggle Loop")
        self._loop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._loop_btn.setStyleSheet("""
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 0.35);
            }
        """)
        self._loop_btn.clicked.connect(self._on_loop_clicked)
        timeline_row.addWidget(self._loop_btn)

        # Frame ruler timeline
        self._frame_timeline = FrameRulerTimeline()
        self._frame_timeline.frame_clicked.connect(self._on_timeline_frame_clicked)
        self._frame_timeline.frame_dragged.connect(self._on_timeline_frame_clicked)
        self._frame_timeline.marker_clicked.connect(self._on_marker_clicked)
        self._frame_timeline.annotation_marker_clicked.connect(self._on_annotation_marker_clicked)
        timeline_row.addWidget(self._frame_timeline, 1)

        center_layout.addLayout(timeline_row)

        # Connect video frame changes to timeline
        self._video_preview.frame_changed.connect(self._on_video_frame_changed)

        self._splitter.addWidget(self._center_widget)

        # ===== RIGHT: Notes panel =====
        self._notes_panel = ReviewNotesPanel(
            fps=self._current_fps,
            is_studio_mode=self._is_studio_mode,
            current_user=self._current_user,
            current_user_role=self._current_user_role
        )
        self._notes_panel.setFixedWidth(320)

        # Connect notes panel signals
        self._notes_panel.note_clicked.connect(self._on_note_clicked)
        self._notes_panel.note_added.connect(self._on_note_added)
        self._notes_panel.note_resolved.connect(self._on_note_resolve_toggled)
        self._notes_panel.note_deleted.connect(self._on_note_delete_requested)
        self._notes_panel.note_restored.connect(self._on_note_restore_requested)
        self._notes_panel.note_edited.connect(self._on_note_edit_saved)

        self._splitter.addWidget(self._notes_panel)

        # Comparison widget (hidden)
        self._comparison_widget = ComparisonWidget()
        self._comparison_widget.hide()
        self._splitter.addWidget(self._comparison_widget)

        # Set initial splitter sizes (tree, video, notes)
        self._splitter.setSizes([self.TABLE_WIDTH_NORMAL, 800, 320])

        layout.addWidget(self._splitter, 1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._set_latest_btn = QPushButton("Set as Latest")
        self._set_latest_btn.setEnabled(False)
        self._set_latest_btn.clicked.connect(self._on_set_as_latest)
        btn_layout.addWidget(self._set_latest_btn)

        self._apply_btn = QPushButton("Apply This Version")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_version)
        btn_layout.addWidget(self._apply_btn)

        self._compare_btn = QPushButton("Compare")
        self._compare_btn.clicked.connect(self._toggle_compare_mode)
        btn_layout.addWidget(self._compare_btn)

        # Hide shot-specific buttons in Analysis Mode
        if self._analysis_mode:
            self._set_latest_btn.hide()
            self._compare_btn.hide()
            self._apply_btn.hide()

        self._export_annotations_btn = QPushButton("Export with Annotations")
        self._export_annotations_btn.setEnabled(False)
        self._export_annotations_btn.setToolTip("Export video with annotations burned in as MP4")
        self._export_annotations_btn.clicked.connect(self._on_export_with_annotations)
        btn_layout.addWidget(self._export_annotations_btn)

        # Add separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("background: #444;")
        sep.setFixedWidth(2)
        btn_layout.addWidget(sep)

        # Display options: Prev | Next | Hide | Hold | Ghost
        self._build_display_options_buttons(btn_layout)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Enable keyboard focus for shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _build_display_options_buttons(self, layout: QHBoxLayout):
        """Add display options buttons to the bottom bar: Prev | Next | Hide | Hold | Ghost."""
        # Get theme icon color
        theme = get_theme_manager().get_current_theme()
        icon_color = theme.palette.header_icon_color if theme else "#e0e0e0"

        btn_style = """
            QPushButton { background: #2d2d2d; border: 1px solid #444;
                          border-radius: 3px; padding: 4px 8px; }
            QPushButton:hover { background: #3a3a3a; border-color: #555; }
            QPushButton:disabled { background: #252525; border-color: #333; }
        """
        toggle_style = """
            QPushButton { background: #2d2d2d; border: 1px solid #444;
                          border-radius: 3px; padding: 4px 8px; }
            QPushButton:hover { background: #3a3a3a; border-color: #555; }
            QPushButton:checked { background: #4CAF50; border-color: #4CAF50; }
            QPushButton:disabled { background: #252525; border-color: #333; }
        """

        def make_icon_btn(icon_name, tooltip, checkable=False, style=btn_style):
            btn = QPushButton()
            btn.setIcon(colorize_white_svg(IconLoader.get(icon_name), icon_color))
            btn.setIconSize(QSize(18, 18))
            btn.setFixedSize(32, 32)
            btn.setToolTip(tooltip)
            btn.setCheckable(checkable)
            btn.setStyleSheet(style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            return btn

        # Previous annotation button (A key)
        self._prev_ann_btn = make_icon_btn("arrow_left", "Previous annotation (A)")
        self._prev_ann_btn.clicked.connect(self._on_prev_annotation)
        self._prev_ann_btn.setEnabled(False)
        layout.addWidget(self._prev_ann_btn)

        # Next annotation button (D key)
        self._next_ann_btn = make_icon_btn("arrow_right", "Next annotation (D)")
        self._next_ann_btn.clicked.connect(self._on_next_annotation)
        self._next_ann_btn.setEnabled(False)
        layout.addWidget(self._next_ann_btn)

        # HIDE button - Eye icon (V key) - TOGGLE
        self._hide_btn = make_icon_btn("eye", "Hide annotations (V)", checkable=True, style=toggle_style)
        self._hide_btn.toggled.connect(self._on_hide_toggled)
        layout.addWidget(self._hide_btn)

        # HOLD button - Persist forward (H key) - TOGGLE
        self._hold_btn = make_icon_btn("hold_frames", "Hold frames forward (H)", checkable=True, style=toggle_style)
        self._hold_btn.toggled.connect(self._on_hold_toggled)
        layout.addWidget(self._hold_btn)

        # GHOST button - Opens settings popup (G key) - TOGGLE
        self._ghost_btn = make_icon_btn("ghost", "Ghost/Onion skin settings (G)", checkable=True, style=toggle_style)
        self._ghost_btn.clicked.connect(self._on_ghost_btn_clicked)
        layout.addWidget(self._ghost_btn)

    # ==================== Thumbnails ====================

    def _load_thumbnail_async(self, uuid: str, thumbnail_path: str, item: QTreeWidgetItem):
        """Load thumbnail asynchronously for a tree item."""
        if not thumbnail_path:
            return
        if uuid in self._thumbnail_cache:
            item.setIcon(0, QIcon(self._thumbnail_cache[uuid]))
            return

        # Store item reference for later update
        self._pending_thumbnails[uuid] = item
        task = ThumbnailTask(uuid, thumbnail_path, self.THUMBNAIL_SIZE)
        task.signals.loaded.connect(self._on_thumbnail_loaded)
        task.signals.failed.connect(self._on_thumbnail_failed)
        self._thread_pool.start(task)

    def _on_thumbnail_loaded(self, uuid: str, image: QImage):
        """Handle thumbnail loaded signal. Converts QImage to QPixmap in main thread."""
        # THREAD SAFETY: Convert QImage to QPixmap here in main thread
        pixmap = QPixmap.fromImage(image)
        self._thumbnail_cache[uuid] = pixmap
        if uuid in self._pending_thumbnails:
            item = self._pending_thumbnails.pop(uuid)
            if item is not None:
                item.setIcon(0, QIcon(pixmap))

    def _on_thumbnail_failed(self, uuid: str):
        self._pending_thumbnails.pop(uuid, None)

    # ==================== Version Loading ====================

    def _load_versions(self):
        """Load hierarchical version history into tree widget."""
        # Analysis Mode: Load folder videos instead of shot versions
        if self._analysis_mode:
            self._load_analysis_videos()
            return

        self._hierarchy = self._db_service.get_hierarchical_version_history(self._version_group_id)
        shot_versions = self._hierarchy.get('shot_versions', [])
        base_name = self._hierarchy.get('base_shot_name', 'Unknown')

        if not shot_versions:
            self._name_label.setText("No versions found")
            self._load_versions_flat()
            return

        has_multiple_shot_versions = len(shot_versions) > 1
        self._name_label.setText(f"Shot: {base_name}")
        self._tree.clear()
        self._versions = []
        latest_playblast_item = None

        if has_multiple_shot_versions:
            for shot_ver in shot_versions:
                shot_id = shot_ver.get('shot_id')
                shot_name = shot_ver.get('shot_name', 'Unknown')
                shot_version_label = shot_ver.get('shot_version_label', 'v001')
                is_latest = shot_ver.get('is_latest_shot_version', False)
                status = shot_ver.get('status', 'WIP')
                playblasts = shot_ver.get('playblasts', [])

                parent_item = QTreeWidgetItem()
                blend_icon = IconLoader.get_themed_icon("blend")
                if blend_icon and not blend_icon.isNull():
                    parent_item.setIcon(0, blend_icon)

                label = f"Shot {shot_version_label}"
                if is_latest:
                    label += " [LATEST]"

                parent_item.setText(1, label)
                parent_item.setText(2, status.upper())
                parent_item.setText(3, f"{len(playblasts)} pb")
                parent_item.setSizeHint(0, QSize(24, 24))

                parent_item.setData(0, Qt.ItemDataRole.UserRole, {
                    'type': 'shot_version',
                    'shot_id': shot_id,
                    'shot_name': shot_name,
                    'shot_version_label': shot_version_label,
                    'is_latest_shot_version': is_latest,
                })

                font = parent_item.font(1)
                font.setBold(True)
                parent_item.setFont(1, font)
                if is_latest:
                    parent_item.setForeground(1, QBrush(QColor("#4CAF50")))

                self._tree.addTopLevelItem(parent_item)

                for pb in playblasts:
                    version = self._map_playblast_to_version(pb, shot_name, status)
                    resolved_preview = self._db_service.animations.resolve_preview_file(version)
                    if resolved_preview:
                        version['preview_path'] = str(resolved_preview)
                    self._versions.append(version)

                    child_item = self._create_playblast_item(version, pb.get('is_latest', False))
                    parent_item.addChild(child_item)

                    if is_latest and pb.get('is_latest', False):
                        latest_playblast_item = child_item

                if is_latest:
                    parent_item.setExpanded(True)
        else:
            shot_ver = shot_versions[0]
            shot_name = shot_ver.get('shot_name', 'Unknown')
            status = shot_ver.get('status', 'WIP')
            playblasts = shot_ver.get('playblasts', [])

            for pb in playblasts:
                version = self._map_playblast_to_version(pb, shot_name, status)
                resolved_preview = self._db_service.animations.resolve_preview_file(version)
                if resolved_preview:
                    version['preview_path'] = str(resolved_preview)
                self._versions.append(version)

                item = self._create_playblast_item(version, pb.get('is_latest', False))
                self._tree.addTopLevelItem(item)

                if pb.get('is_latest', False):
                    latest_playblast_item = item

        if latest_playblast_item:
            self._tree.setCurrentItem(latest_playblast_item)

    def _load_versions_flat(self):
        """Fall back to flat playblast list (original behavior)."""
        self._versions = self._db_service.get_version_history(self._version_group_id)

        if not self._versions:
            self._name_label.setText("No versions found")
            return

        for version in self._versions:
            resolved_thumb = self._db_service.animations.resolve_thumbnail_file(version)
            if resolved_thumb:
                version['thumbnail_path'] = str(resolved_thumb)
            resolved_preview = self._db_service.animations.resolve_preview_file(version)
            if resolved_preview:
                version['preview_path'] = str(resolved_preview)

        self._name_label.setText(f"Animation: {self._versions[0].get('name', 'Unknown')}")
        self._tree.clear()

        latest_item = None
        for version in self._versions:
            is_latest = version.get('is_latest', 0)
            item = self._create_playblast_item(version, is_latest)
            self._tree.addTopLevelItem(item)
            if is_latest:
                latest_item = item

        if latest_item:
            self._tree.setCurrentItem(latest_item)

    def _load_analysis_videos(self):
        """
        Load folder videos for Analysis Mode.

        In Analysis Mode, the version tree shows ALL videos in the folder,
        allowing quick switching between reference videos (like SyncSketch).
        """
        self._tree.clear()
        self._versions = []

        if not self._folder_videos:
            self._name_label.setText("No videos in folder")
            return

        # Set window title for analysis mode
        folder_name = Path(self._folder_videos[0]).parent.name if self._folder_videos else "Reference"
        self._name_label.setText(f"Reference Videos: {folder_name}")
        self.setWindowTitle("Reference Video Analysis")

        initial_item = None

        for video_path in self._folder_videos:
            video_path_obj = Path(video_path)
            video_name = video_path_obj.stem

            # Create version dict for compatibility
            from ...services.reference_database import ReferenceDatabase
            video_id = ReferenceDatabase.get_video_id(video_path)

            version = {
                'uuid': video_id,
                'version_label': video_name,
                'name': video_name,
                'preview_path': video_path,
                'created_at': '',
                'is_reference_video': True,
                # Store original video path for reference database operations
                '_video_path': video_path,
            }
            self._versions.append(version)

            # Create tree item
            item = QTreeWidgetItem()

            # Set icon (video icon)
            video_icon = IconLoader.get_themed_icon("video")
            if video_icon and not video_icon.isNull():
                item.setIcon(0, video_icon)

            item.setText(1, video_name)
            item.setText(2, "REF")  # Status column
            item.setText(3, "")  # No frame count

            item.setData(0, Qt.ItemDataRole.UserRole, {
                'type': 'reference_video',
                'uuid': video_id,
                'video_path': video_path,
            })

            # Queue thumbnail
            self._pending_thumbnails[video_id] = item
            task = ThumbnailTask(video_id, video_path, self.THUMBNAIL_SIZE)
            task.signals.loaded.connect(self._on_thumbnail_loaded)
            task.signals.failed.connect(self._on_thumbnail_failed)
            self._thread_pool.start(task)

            self._tree.addTopLevelItem(item)

            # Track initial video to select
            if video_path == self._folder_videos[0] or video_id == self._version_group_id:
                initial_item = item
                self._initial_video_path = video_path

        if initial_item:
            self._tree.setCurrentItem(initial_item)
            # Explicitly trigger selection handler to load the video
            # (setCurrentItem may not always emit the signal during initialization)
            self._on_selection_changed()

    def _on_pb_mode_clicked(self):
        """Switch to Playblast mode."""
        self._preview_mode = "playblast"
        self._pb_btn.setChecked(True)
        self._ld_btn.setChecked(False)
        self._rd_btn.setChecked(False)
        self._load_playblast_versions()

    def _on_ld_mode_clicked(self):
        """Switch to Lookdev mode."""
        self._preview_mode = "lookdev"
        self._pb_btn.setChecked(False)
        self._ld_btn.setChecked(True)
        self._rd_btn.setChecked(False)
        self._load_lookdev_versions()

    def _on_rd_mode_clicked(self):
        """Switch to Render mode."""
        self._preview_mode = "render"
        self._pb_btn.setChecked(False)
        self._ld_btn.setChecked(False)
        self._rd_btn.setChecked(True)
        self._load_render_versions()

    def _load_playblast_versions(self):
        """Load playblast versions from filesystem."""
        if self._playblast_indexer is None:
            return
        self._tree.clear()
        self._versions = []
        self._playblast_versions = []

        if not self._shot_folder or not self._shot_folder.exists():
            self._name_label.setText("No shot folder available for playblast")
            return

        # Discover playblast versions using indexer
        try:
            self._playblast_versions = self._playblast_indexer.discover_playblasts(
                self._shot_folder,
                blend_stem=self._blend_stem
            )
        except Exception:
            logger.warning(
                "Failed to discover playblasts in %s", self._shot_folder, exc_info=True,
            )
            self._playblast_versions = []

        if not self._playblast_versions:
            self._name_label.setText("No playblast versions found")
            return

        self._name_label.setText(f"Playblast: {self._blend_stem or self._shot_folder.name}")

        # Track latest for auto-selection
        latest_item = None

        for playblast in self._playblast_versions:  # Already sorted by version descending
            item = self._create_playblast_item_from_discovered(playblast)
            self._tree.addTopLevelItem(item)

            if playblast.is_latest:
                latest_item = item

        # Auto-select latest
        if latest_item:
            self._tree.setCurrentItem(latest_item)

    def _create_playblast_item_from_discovered(self, playblast) -> QTreeWidgetItem:
        """Create a tree item for a discovered playblast."""
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, {
            'type': 'discovered_playblast',
            'playblast': playblast,
        })

        version_label = f"v{playblast.version:03d}"
        if playblast.is_latest:
            version_label += " ★"
        item.setText(1, version_label)
        item.setText(2, "archived" if playblast.is_archived else "")

        frames = "-"
        if playblast.metadata and playblast.metadata.frame_count:
            frames = str(playblast.metadata.frame_count)
        item.setText(3, frames)
        item.setSizeHint(0, QSize(self.THUMBNAIL_SIZE + 4, self.THUMBNAIL_SIZE + 4))

        if playblast.file_path.exists():
            self._load_thumbnail_async(f"pb_{playblast.version}", str(playblast.file_path), item)

        return item

    def _load_lookdev_versions(self):
        """Load lookdev versions from filesystem."""
        if self._lookdev_indexer is None:
            return
        self._tree.clear()
        self._versions = []
        self._lookdev_versions = []

        if not self._shot_folder or not self._shot_folder.exists():
            self._name_label.setText("No shot folder available for lookdev")
            return

        # Discover lookdev versions using indexer
        try:
            self._lookdev_versions = self._lookdev_indexer.discover_lookdevs(
                self._shot_folder,
                blend_stem=self._blend_stem
            )
        except Exception:
            logger.warning(
                "Failed to discover lookdevs in %s", self._shot_folder, exc_info=True,
            )
            self._lookdev_versions = []

        if not self._lookdev_versions:
            self._name_label.setText("No lookdev versions found")
            return

        self._name_label.setText(f"Lookdev: {self._blend_stem or self._shot_folder.name}")

        # Track latest for auto-selection
        latest_item = None

        for lookdev in reversed(self._lookdev_versions):  # Show newest first
            item = self._create_lookdev_item(lookdev)
            self._tree.addTopLevelItem(item)

            if lookdev.is_latest:
                latest_item = item

        # Auto-select latest
        if latest_item:
            self._tree.setCurrentItem(latest_item)

    def _create_lookdev_item(self, lookdev) -> QTreeWidgetItem:
        """Create a tree item for a lookdev version."""
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'lookdev', 'lookdev': lookdev})

        version_label = f"v{lookdev.version:03d}"
        if lookdev.is_latest:
            version_label += " ★"
        item.setText(1, version_label)
        item.setText(2, "archived" if lookdev.is_archived else "")

        frames = "-"
        if lookdev.metadata:
            frames = str(lookdev.metadata.frame_count) if lookdev.metadata.frame_count else "-"
        item.setText(3, frames)
        item.setSizeHint(0, QSize(self.THUMBNAIL_SIZE + 4, self.THUMBNAIL_SIZE + 4))

        if lookdev.file_path.exists():
            self._load_thumbnail_async(f"lookdev_{lookdev.version}", str(lookdev.file_path), item)

        return item

    def _load_render_versions(self):
        """Load render proxy from Render/ folder."""
        self._tree.clear()
        self._versions = []

        if not self._shot_folder or not self._shot_folder.exists():
            self._name_label.setText("No shot folder available for render")
            return

        render_folder = self._shot_folder / "Render"
        if not render_folder.exists():
            self._name_label.setText("No Render folder found")
            return

        # Find render proxy files: {shot_name}_RD_v*.mp4
        shot_name = self._shot_folder.name
        proxy_files = sorted(render_folder.glob(f"{shot_name}_RD_v*.mp4"), reverse=True)

        # Fallback: any *_RD_v*.mp4 file
        if not proxy_files:
            proxy_files = sorted(render_folder.glob("*_RD_v*.mp4"), reverse=True)

        if not proxy_files:
            self._name_label.setText("No render proxy found")
            return

        self._name_label.setText(f"Render: {shot_name}")

        for proxy_path in proxy_files:
            item = self._create_render_item(proxy_path)
            self._tree.addTopLevelItem(item)

        # Auto-select first (latest)
        if self._tree.topLevelItemCount() > 0:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def _create_render_item(self, proxy_path: Path) -> QTreeWidgetItem:
        """Create a tree item for a render proxy."""
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'render', 'proxy_path': str(proxy_path)})

        # Extract version from filename (e.g., shot_RD_v001.mp4)
        filename = proxy_path.stem
        version_str = "v001"
        if "_RD_v" in filename:
            try:
                version_part = filename.split("_RD_v")[1]
                version_num = int(version_part[:3])
                version_str = f"v{version_num:03d}"
            except (IndexError, ValueError):
                pass

        item.setText(1, version_str)
        item.setText(2, "")  # Status
        item.setText(3, "-")  # Frames

        # Load JSON metadata if exists
        json_path = proxy_path.with_suffix('.json')
        if json_path.exists():
            try:
                import json
                with open(json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                frame_count = metadata.get('frame_count')
                if frame_count:
                    item.setText(3, str(frame_count))
            except Exception:
                pass

        item.setSizeHint(0, QSize(self.THUMBNAIL_SIZE + 4, self.THUMBNAIL_SIZE + 4))

        if proxy_path.exists():
            self._load_thumbnail_async(f"render_{proxy_path.stem}", str(proxy_path), item)

        return item

    def _map_playblast_to_version(self, pb: dict, shot_name: str, status: str) -> dict:
        """Map playblast dict to version dict format for dialog compatibility."""
        return {
            'uuid': pb.get('uuid'),
            'shot_id': pb.get('shot_id'),
            'name': shot_name,
            'version': pb.get('version', 1),
            'version_label': pb.get('version_label', 'v001'),
            'is_latest': pb.get('is_latest', False),
            'status': status,
            'frame_count': pb.get('frame_count'),
            'fps': pb.get('fps'),
            'duration_seconds': pb.get('duration_ms', 0) / 1000.0 if pb.get('duration_ms') else None,
            'preview_path': pb.get('preview_path'),
            'thumbnail_path': pb.get('thumbnail_path'),
            'width': pb.get('width'),
            'height': pb.get('height'),
            'created_at': pb.get('created_at'),
            'is_archived': pb.get('is_archived', False),
        }

    def _create_playblast_item(self, version: dict, is_latest: bool) -> QTreeWidgetItem:
        """Create a tree item for a playblast version."""
        item = QTreeWidgetItem()
        uuid = version.get('uuid', '')

        item.setData(0, Qt.ItemDataRole.UserRole, {
            'type': 'playblast',
            'uuid': uuid,
            'version': version,
        })

        version_label = version.get('version_label', 'v001')
        if is_latest:
            version_label += " ★"
        item.setText(1, version_label)
        item.setText(2, "")

        frames = version.get('frame_count')
        item.setText(3, str(frames) if frames else '-')
        item.setSizeHint(0, QSize(self.THUMBNAIL_SIZE + 4, self.THUMBNAIL_SIZE + 4))

        self._load_thumbnail_async(uuid, version.get('preview_path', ''), item)

        return item

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Handle tree item expansion."""
        # Could load thumbnails on-demand here if needed
        pass

    # ==================== Selection ====================

    def _on_selection_changed(self):
        if self._compare_mode:
            self._on_compare_selection_changed()
            return

        selected_items = self._tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            item_data = item.data(0, Qt.ItemDataRole.UserRole)

            if not item_data:
                return

            item_type = item_data.get('type', '')

            if item_type == 'shot_version':
                # User clicked on a shot version header
                # Auto-select the first playblast child
                if item.childCount() > 0:
                    first_child = item.child(0)
                    self._tree.setCurrentItem(first_child)
                return

            elif item_type == 'playblast':
                # User selected a playblast
                version = item_data.get('version', {})
                self._selected_uuid = version.get('uuid')
                self._selected_version_label = version.get('version_label', 'v001')

                is_latest = version.get('is_latest', 0)
                self._set_latest_btn.setEnabled(not is_latest)
                self._apply_btn.setEnabled(True)

                self._update_preview_from_version(version)

                # Reset drawover state for new version
                self._current_drawover_frame = -1
                self._strokes_from_hold = False
                self._load_annotation_markers()

            elif item_type == 'lookdev':
                # User selected a lookdev
                lookdev = item_data.get('lookdev')
                if lookdev:
                    self._selected_uuid = f"lookdev_{lookdev.version}"
                    self._selected_version_label = f"v{lookdev.version:03d}"

                    # Can't set lookdev as "latest" through this dialog
                    self._set_latest_btn.setEnabled(False)
                    self._apply_btn.setEnabled(False)

                    self._update_preview_from_lookdev(lookdev)

                    # Reset drawover state for new version
                    self._current_drawover_frame = -1
                    self._strokes_from_hold = False
                    self._load_annotation_markers()

            elif item_type == 'discovered_playblast':
                # User selected a discovered playblast (filesystem)
                playblast = item_data.get('playblast')
                if playblast:
                    self._selected_uuid = f"pb_{playblast.version}"
                    self._selected_version_label = f"v{playblast.version:03d}"

                    self._set_latest_btn.setEnabled(False)
                    self._apply_btn.setEnabled(False)

                    self._update_preview_from_playblast(playblast)

                    # Reset drawover state for new version
                    self._current_drawover_frame = -1
                    self._strokes_from_hold = False
                    self._load_annotation_markers()

            elif item_type == 'render':
                # User selected a render proxy
                proxy_path = item_data.get('proxy_path')
                if proxy_path:
                    self._selected_uuid = f"render_{Path(proxy_path).stem}"
                    self._selected_version_label = "render"

                    # Can't set render as "latest" through this dialog
                    self._set_latest_btn.setEnabled(False)
                    self._apply_btn.setEnabled(False)

                    # Create a version dict for preview
                    version = {
                        'uuid': self._selected_uuid,
                        'preview_path': proxy_path,
                        'version_label': Path(proxy_path).stem,
                    }
                    self._update_preview_from_version(version)

                    # Reset drawover state for new version
                    self._current_drawover_frame = -1
                    self._strokes_from_hold = False
                    self._load_annotation_markers()

            elif item_type == 'reference_video':
                # User selected a reference video (Analysis Mode)
                video_path = item_data.get('video_path')
                uuid = item_data.get('uuid')

                if video_path:
                    self._selected_uuid = uuid
                    # Use "reference" as version label for ReferenceDrawoverStorage compatibility
                    self._selected_version_label = "reference"

                    # Store current video path for drawover operations
                    self._current_video_path = video_path

                    # Ensure session exists in reference database for later note operations
                    # This allows add_note to look up video_path from video_id
                    if self._analysis_mode:
                        self._notes_db.get_or_create_session(video_path)

                    # Disable apply/set-latest in analysis mode
                    self._set_latest_btn.setEnabled(False)
                    self._apply_btn.setEnabled(False)

                    # Create a version dict for preview
                    version = {
                        'uuid': uuid,
                        'preview_path': video_path,
                        'version_label': Path(video_path).stem,  # Display name
                        '_video_path': video_path,
                    }
                    self._update_preview_from_version(version)

                    # Reset drawover state for new video
                    self._current_drawover_frame = -1
                    self._strokes_from_hold = False
                    self._load_annotation_markers()
        else:
            self._selected_uuid = None
            self._selected_version_label = None
            self._set_latest_btn.setEnabled(False)
            self._apply_btn.setEnabled(False)
            self._video_preview.clear()
            self._preview_info_label.setText("Select a version to preview")
            self._frame_timeline.set_total_frames(1)
            self._clear_notes()
            # Clear drawover
            self._drawover_canvas.clear()
            self._drawover_canvas.hide()
            self._current_drawover_frame = -1
            self._annotation_frames = []
            self._strokes_from_hold = False

    def _update_preview(self, row: int):
        """Legacy method for compatibility - finds version by index."""
        if row < 0 or row >= len(self._versions):
            return
        version = self._versions[row]
        self._update_preview_from_version(version)

    def _update_preview_from_version(self, version: dict):
        """Update preview panel from a version dict."""
        version_label = version.get('version_label', 'v001')
        status = version.get('status', 'none')
        status_info = Config.LIFECYCLE_STATUSES.get(status, {'label': status})

        # Info label
        is_latest = "Latest" if version.get('is_latest', 0) else ""
        info_parts = [version_label]
        if is_latest:
            info_parts.append(is_latest)
        if status != 'none':
            info_parts.append(status_info.get('label', status))
        self._preview_info_label.setText(" | ".join(info_parts))

        # Load video
        preview_path = version.get('preview_path', '')
        if preview_path and Path(preview_path).exists():
            self._video_preview.load_video(preview_path)
        else:
            self._video_preview.clear()

        # Store video info - get from version dict or from loaded video
        self._current_fps = version.get('fps', 24) or 24
        self._total_frames = version.get('frame_count', 0) or 0

        # If frame_count not in version dict, get it from the video preview widget
        # (important for Analysis Mode where version dict may not have metadata)
        if self._total_frames == 0 and self._video_preview.is_video_loaded:
            self._total_frames = self._video_preview.total_frames
            self._current_fps = self._video_preview.fps or 24

        # Update timeline
        self._frame_timeline.set_total_frames(max(1, self._total_frames))
        self._frame_timeline.set_current_frame(0)

        # Always-on annotation mode - show toolbar
        self._annotation_toolbar.show()
        self._export_annotations_btn.setEnabled(True)
        self._current_drawover_frame = -1  # Reset to force load
        self._strokes_from_hold = False

        # Canvas is always editable (always-on mode)
        self._drawover_canvas.read_only = False
        self._drawover_canvas.set_tool(DrawingTool.PEN)
        self._drawover_canvas.color = self._annotation_toolbar.current_color
        self._annotation_toolbar.set_tool(DrawingTool.PEN)
        self._position_drawover_canvas()
        self._drawover_canvas.show()
        self._load_drawover_for_frame(0)

        # Load review notes and annotation markers
        self._load_review_notes()
        self._load_annotation_markers()

    def _update_preview_from_lookdev(self, lookdev):
        """Update preview panel from a lookdev version."""
        version_label = f"v{lookdev.version:03d}"

        # Info label
        is_latest = "Latest" if lookdev.is_latest else ""
        info_parts = [f"Lookdev {version_label}"]
        if is_latest:
            info_parts.append(is_latest)
        if lookdev.is_archived:
            info_parts.append("archived")
        self._preview_info_label.setText(" | ".join(info_parts))

        # Load video
        if lookdev.file_path.exists():
            self._video_preview.load_video(str(lookdev.file_path))
        else:
            self._video_preview.clear()

        # Store video info from metadata
        if lookdev.metadata:
            self._current_fps = lookdev.metadata.fps or 24
            self._total_frames = lookdev.metadata.frame_count or 0
        else:
            self._current_fps = 24
            self._total_frames = 0

        # Update timeline
        self._frame_timeline.set_total_frames(max(1, self._total_frames))
        self._frame_timeline.set_current_frame(0)

        # Always-on annotation mode - show toolbar
        self._annotation_toolbar.show()
        self._export_annotations_btn.setEnabled(True)
        self._current_drawover_frame = -1  # Reset to force load
        self._strokes_from_hold = False

        # Canvas is always editable (always-on mode)
        self._drawover_canvas.read_only = False
        self._drawover_canvas.set_tool(DrawingTool.PEN)
        self._drawover_canvas.color = self._annotation_toolbar.current_color
        self._annotation_toolbar.set_tool(DrawingTool.PEN)
        self._position_drawover_canvas()
        self._drawover_canvas.show()
        self._load_drawover_for_frame(0)

        # Load review notes and annotation markers
        self._load_review_notes()
        self._load_annotation_markers()

    def _update_preview_from_playblast(self, playblast):
        """Update preview panel from a discovered playblast."""
        version_label = f"v{playblast.version:03d}"

        # Info label
        is_latest = "Latest" if playblast.is_latest else ""
        info_parts = [f"Playblast {version_label}"]
        if is_latest:
            info_parts.append(is_latest)
        if playblast.is_archived:
            info_parts.append("archived")
        self._preview_info_label.setText(" | ".join(info_parts))

        # Load video
        if playblast.file_path.exists():
            self._video_preview.load_video(str(playblast.file_path))
        else:
            self._video_preview.clear()

        # Store video info from metadata
        if playblast.metadata:
            self._current_fps = playblast.metadata.fps or 24
            self._total_frames = playblast.metadata.frame_count or 0
        else:
            self._current_fps = 24
            self._total_frames = 0

        # Update timeline
        self._frame_timeline.set_total_frames(max(1, self._total_frames))
        self._frame_timeline.set_current_frame(0)

        # Always-on annotation mode - show toolbar
        self._annotation_toolbar.show()
        self._export_annotations_btn.setEnabled(True)
        self._current_drawover_frame = -1  # Reset to force load
        self._strokes_from_hold = False

        # Canvas is always editable (always-on mode)
        self._drawover_canvas.read_only = False
        self._drawover_canvas.set_tool(DrawingTool.PEN)
        self._drawover_canvas.color = self._annotation_toolbar.current_color
        self._annotation_toolbar.set_tool(DrawingTool.PEN)
        self._position_drawover_canvas()
        self._drawover_canvas.show()
        self._load_drawover_for_frame(0)

        # Load review notes and annotation markers
        self._load_review_notes()
        self._load_annotation_markers()

    def _load_playback_icons(self):
        """Load media control icons matching video preview widget."""
        theme = get_theme_manager().get_current_theme()
        icon_color = theme.palette.header_icon_color if theme else "#1a1a1a"

        self._play_icon = colorize_white_svg(IconLoader.get("play"), icon_color)
        self._pause_icon = colorize_white_svg(IconLoader.get("pause"), icon_color)
        self._loop_icon = colorize_white_svg(IconLoader.get("loop"), icon_color)

    def _on_video_frame_changed(self, frame: int):
        """Sync timeline with video playback."""
        self._frame_timeline.set_current_frame(frame)
        # Update play button icon based on playing state
        self._update_play_button_icon()

        # Update notes panel current frame
        self._notes_panel.set_current_frame(frame)

        # Load drawover for new frame (show annotations even when not editing)
        if frame != self._current_drawover_frame:
            self._load_drawover_for_frame(frame)

    def _update_play_button_icon(self):
        """Update play button icon based on playback state."""
        if self._video_preview.is_playing:
            self._play_btn.setIcon(self._pause_icon)
        else:
            self._play_btn.setIcon(self._play_icon)

    def _on_play_clicked(self):
        """Toggle video playback."""
        self._video_preview.toggle_playback()
        self._update_play_button_icon()

    def _on_loop_clicked(self):
        """Toggle loop mode."""
        self._video_preview.set_loop(self._loop_btn.isChecked())

    def _on_timeline_frame_clicked(self, frame: int):
        """Seek video when timeline is clicked."""
        if hasattr(self._video_preview, 'seek_to_frame'):
            self._video_preview.seek_to_frame(frame)
        # Ensure timeline playhead is synced
        self._frame_timeline.set_current_frame(frame)

    def _on_marker_clicked(self, frame: int, note_id: int):
        """Handle click on a timeline marker - seek to frame."""
        # Seek video and update timeline
        if hasattr(self._video_preview, 'seek_to_frame'):
            self._video_preview.seek_to_frame(frame)
        self._frame_timeline.set_current_frame(frame)

    # ==================== Review Notes ====================

    def _on_show_deleted_toggled(self, checked: bool):
        """Handle show deleted checkbox toggle."""
        self._notes_manager.show_deleted = checked
        self._load_review_notes()

    def _load_review_notes(self):
        """Load review notes for the selected version."""
        if not self._selected_uuid or not self._selected_version_label:
            self._notes_panel.set_notes([])
            return

        notes = self._notes_manager.load_notes(self._selected_uuid, self._selected_version_label)

        # Update timeline markers (only show non-deleted notes on timeline)
        active_notes = self._notes_manager.get_active_notes()
        self._frame_timeline.set_notes(active_notes)

        # Update notes panel
        self._notes_panel.set_notes(notes)

    def _on_notes_changed(self):
        """Callback when notes change - reload and display."""
        self._load_review_notes()

    def _clear_notes(self):
        """Clear all notes display."""
        self._notes_panel.clear()

    def _on_note_added(self, frame: int, text: str):
        """Add a new note at the given frame."""
        if self._selected_uuid and self._selected_version_label:
            self._notes_manager.add_note(self._selected_uuid, self._selected_version_label, frame, text)

    def _on_note_clicked(self, frame: int):
        """Seek to note's frame and update timeline."""
        if hasattr(self._video_preview, 'seek_to_frame'):
            self._video_preview.seek_to_frame(frame)
        self._frame_timeline.set_current_frame(frame)

    def _on_note_resolve_toggled(self, note_id: int, new_resolved: bool):
        """Toggle note resolved status."""
        self._notes_manager.resolve_note(note_id, new_resolved)

    def _on_note_delete_requested(self, note_id: int):
        """Delete a note (soft delete with audit trail)."""
        self._notes_manager.delete_note(note_id, confirm=True)

    def _on_note_restore_requested(self, note_id: int):
        """Restore a soft-deleted note."""
        self._notes_manager.restore_note(note_id)

    def _on_note_edit_saved(self, note_id: int, new_text: str):
        """Save edited note with audit trail."""
        self._notes_manager.edit_note(note_id, new_text)

    # ==================== Annotation Markers ====================

    def _load_annotation_markers(self):
        """Load frames with annotations for timeline display."""
        if not self._selected_uuid or not self._selected_version_label:
            self._annotation_frames = []
            self._frame_timeline.set_annotation_frames([])
            self._update_annotation_nav_buttons()
            return

        # Both Shot Mode and Analysis Mode use the same interface:
        # - Shot Mode: uuid = animation_uuid, version_label = "v001" etc.
        # - Analysis Mode: uuid = video_id (path hash), version_label = "reference"
        self._annotation_frames = self._drawover_storage.list_frames_with_drawovers(
            self._selected_uuid, self._selected_version_label
        )
        self._frame_timeline.set_annotation_frames(self._annotation_frames)
        self._update_annotation_nav_buttons()

    def _on_annotation_marker_clicked(self, frame: int):
        """Handle click on annotation marker - seek to frame."""
        if hasattr(self._video_preview, 'seek_to_frame'):
            self._video_preview.seek_to_frame(frame)
        self._frame_timeline.set_current_frame(frame)

    def _update_annotation_nav_buttons(self):
        """Update enabled state of prev/next annotation buttons."""
        if not self._annotation_frames:
            self._prev_ann_btn.setEnabled(False)
            self._next_ann_btn.setEnabled(False)
            return

        current = self._video_preview.current_frame if hasattr(self._video_preview, 'current_frame') else 0
        has_prev = any(f < current for f in self._annotation_frames)
        has_next = any(f > current for f in self._annotation_frames)
        self._prev_ann_btn.setEnabled(has_prev)
        self._next_ann_btn.setEnabled(has_next)

    def _on_prev_annotation(self):
        """Navigate to previous annotation frame."""
        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.navigate_prev_annotation()
            return

        if not self._annotation_frames:
            return
        current = self._video_preview.current_frame if hasattr(self._video_preview, 'current_frame') else 0
        prev_frames = [f for f in self._annotation_frames if f < current]
        if prev_frames:
            target = max(prev_frames)
            if hasattr(self._video_preview, 'seek_to_frame'):
                self._video_preview.seek_to_frame(target)
            self._frame_timeline.set_current_frame(target)
        self._update_annotation_nav_buttons()

    def _on_next_annotation(self):
        """Navigate to next annotation frame."""
        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.navigate_next_annotation()
            return

        if not self._annotation_frames:
            return
        current = self._video_preview.current_frame if hasattr(self._video_preview, 'current_frame') else 0
        next_frames = [f for f in self._annotation_frames if f > current]
        if next_frames:
            target = min(next_frames)
            if hasattr(self._video_preview, 'seek_to_frame'):
                self._video_preview.seek_to_frame(target)
            self._frame_timeline.set_current_frame(target)
        self._update_annotation_nav_buttons()

    # ==================== Display Options (Hide/Hold/Ghost) ====================

    def _on_hide_toggled(self, checked: bool):
        """Toggle hide annotations mode."""
        self._hide_annotations = checked

        # Update icon
        theme = get_theme_manager().get_current_theme()
        icon_color = theme.palette.header_icon_color if theme else "#e0e0e0"
        icon_name = "eye_off" if checked else "eye"
        self._hide_btn.setIcon(colorize_white_svg(IconLoader.get(icon_name), icon_color))

        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.set_annotations_visible(not checked)
            return

        if checked:
            self._drawover_canvas.hide()
        else:
            self._drawover_canvas.show()
            self._load_drawover_for_frame(self._current_drawover_frame)

    def _on_hold_toggled(self, checked: bool):
        """Toggle hold frames forward mode."""
        self._hold_enabled = checked

        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.set_hold_enabled(checked)
            return

        self._load_drawover_for_frame(self._current_drawover_frame)

    def _on_ghost_btn_clicked(self, checked: bool):
        """Handle ghost button click - show settings popup."""
        self._ghost_popup.adjustSize()
        popup_height = self._ghost_popup.sizeHint().height()
        button_top_left = self._ghost_btn.mapToGlobal(self._ghost_btn.rect().topLeft())
        global_pos = QPoint(button_top_left.x(), button_top_left.y() - popup_height - 5)
        self._ghost_popup.exec(global_pos)

        settings = self._ghost_popup.get_settings()
        enabled = settings.get('enabled', False)
        self._ghost_btn.setChecked(enabled)
        self._ghost_enabled = enabled
        if enabled:
            self._ghost_settings = settings

        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.set_ghost_enabled(enabled)
            if enabled:
                self._comparison_widget.set_ghost_settings(self._ghost_settings)
            return

        self._load_drawover_for_frame(self._current_drawover_frame)

    def _on_ghost_settings_changed(self, settings: dict):
        """Handle ghost settings change."""
        self._ghost_settings = settings
        enabled = settings.get('enabled', False)
        self._ghost_enabled = enabled
        self._ghost_btn.setChecked(enabled)

        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.set_ghost_enabled(enabled)
            self._comparison_widget.set_ghost_settings(settings)
            return

        self._load_drawover_for_frame(self._current_drawover_frame)

    def _on_ghost_toggled(self, enabled: bool):
        """Handle ghost enable/disable toggle."""
        self._ghost_enabled = enabled
        self._ghost_btn.setChecked(enabled)

        # In compare mode, delegate to comparison widget
        if self._compare_mode and self._comparison_widget.isVisible():
            self._comparison_widget.set_ghost_enabled(enabled)
            return

        self._load_drawover_for_frame(self._current_drawover_frame)

    # ==================== Additional Toolbar Handlers ====================

    def _on_brush_size_changed(self, size: int):
        """Handle brush size change."""
        self._drawover_canvas.brush_size = size

    def _on_opacity_changed(self, opacity: float):
        """Handle opacity change."""
        self._drawover_canvas.opacity = opacity

    def _on_drawover_delete_all(self):
        """Delete ALL annotations for the current version (nuclear option)."""
        if not self._selected_uuid or not self._selected_version_label:
            return

        reply = QMessageBox.warning(
            self,
            "Delete All Annotations",
            f"This will permanently delete ALL annotations for this version.\n\n"
            f"This action cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Delete all annotation files for this version
            success = self._drawover_storage.delete_all_for_version(
                self._selected_uuid,
                self._selected_version_label
            )

            if success:
                # Clear cache
                self._drawover_cache.invalidate_version(
                    self._selected_uuid,
                    self._selected_version_label
                )
                # Clear canvas
                self._drawover_canvas.clear()
                # Reload markers
                self._load_annotation_markers()
                QMessageBox.information(self, "Deleted", "All annotations have been deleted.")
            else:
                QMessageBox.warning(self, "Error", "Failed to delete annotations.")

    # ==================== Actions ====================

    def _on_double_click(self, item):
        self._on_apply_version()

    def _on_set_as_latest(self):
        if not self._selected_uuid:
            return
        reply = QMessageBox.question(
            self, "Set as Latest",
            "Set this version as the latest?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._db_service.set_version_as_latest(self._selected_uuid):
                self.version_set_as_latest.emit(self._selected_uuid)
                self._load_versions()
            else:
                QMessageBox.warning(self, "Error", "Failed to set version as latest.")

    def _on_apply_version(self):
        if self._selected_uuid:
            self.version_selected.emit(self._selected_uuid)
            self.accept()

    def get_selected_uuid(self) -> Optional[str]:
        return self._selected_uuid

    # ==================== Compare Mode ====================

    def _toggle_compare_mode(self):
        if self._compare_mode:
            self._exit_compare_mode()
        else:
            self._enter_compare_mode()

    def _enter_compare_mode(self):
        self._save_current_drawover()
        self._drawover_canvas.hide()
        self._annotation_toolbar.hide()

        self._compare_mode = True
        self._compare_selections = []

        self._compare_btn.setText("Exit Compare")
        self._compare_btn.setStyleSheet("background-color: #3A8FB7;")

        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._tree.clearSelection()

        self._set_latest_btn.setEnabled(False)
        self._apply_btn.setEnabled(False)
        self._preview_info_label.setText("Select 2 playblasts to compare")

        # Enable annotation nav buttons (they will work with comparison widget)
        self._prev_ann_btn.setEnabled(True)
        self._next_ann_btn.setEnabled(True)

        self._notes_panel.hide()
        current_sizes = self._splitter.sizes()
        self._splitter.setSizes([self.TABLE_WIDTH_COMPARE, current_sizes[1] + (current_sizes[0] - self.TABLE_WIDTH_COMPARE), 0])

    def _exit_compare_mode(self):
        self._compare_mode = False
        self._compare_selections = []

        self._compare_btn.setText("Compare")
        self._compare_btn.setStyleSheet("")

        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.clearSelection()

        self._comparison_widget.hide()
        self._comparison_widget.clear()
        self._center_widget.show()
        self._notes_panel.show()

        self._splitter.setSizes([self.TABLE_WIDTH_NORMAL, 800, 320])

    def _on_compare_selection_changed(self):
        """Handle selection changes in compare mode."""
        try:
            selected_items = self._tree.selectedItems()

            media_items = []
            for item in selected_items:
                item_data = item.data(0, Qt.ItemDataRole.UserRole)
                if item_data:
                    item_type = item_data.get('type')
                    if item_type == 'playblast':
                        uuid = item_data.get('uuid')
                        if uuid:
                            media_items.append((item, uuid, 'playblast'))
                    elif item_type == 'lookdev':
                        lookdev = item_data.get('lookdev')
                        if lookdev:
                            uuid = f"lookdev_{lookdev.version}"
                            media_items.append((item, uuid, 'lookdev'))

            if len(media_items) > 2:
                self._tree.blockSignals(True)
                self._tree.clearSelection()
                for item, uuid, _ in media_items[:2]:
                    item.setSelected(True)
                self._tree.blockSignals(False)
                media_items = media_items[:2]

            self._compare_selections = [(uuid, media_type) for _, uuid, media_type in media_items]

            if len(self._compare_selections) == 2:
                self._show_comparison()
            else:
                self._comparison_widget.hide()
                self._center_widget.show()
                count_needed = 2 - len(self._compare_selections)
                media_type = "lookdev(s)" if self._preview_mode == "lookdev" else "playblast(s)"
                self._preview_info_label.setText(f"Select {count_needed} more {media_type}")
        except Exception:
            logger.warning("Compare selection update failed", exc_info=True)

    def _show_comparison(self):
        if len(self._compare_selections) != 2:
            return

        uuid_a, type_a = self._compare_selections[0]
        uuid_b, type_b = self._compare_selections[1]

        version_a = self._find_compare_version(uuid_a, type_a)
        version_b = self._find_compare_version(uuid_b, type_b)

        if version_a and version_b:
            notes_a = []
            notes_b = []

            if self._notes_db and type_a == 'playblast':
                label_a = version_a.get('version_label', '')
                if uuid_a and label_a:
                    notes_a = self._notes_db.get_notes_for_version(uuid_a, label_a)

            if self._notes_db and type_b == 'playblast':
                label_b = version_b.get('version_label', '')
                if uuid_b and label_b:
                    notes_b = self._notes_db.get_notes_for_version(uuid_b, label_b)

            self._center_widget.hide()
            self._comparison_widget.show()
            self._comparison_widget.set_versions(version_a, version_b, notes_a, notes_b)

    def _find_compare_version(self, uuid: str, media_type: str) -> Optional[Dict]:
        """Find a version dict for comparison by uuid and type."""
        if media_type == 'playblast':
            return next((v for v in self._versions if v.get('uuid') == uuid), None)
        elif media_type == 'lookdev':
            for lookdev in self._lookdev_versions:
                if f"lookdev_{lookdev.version}" == uuid:
                    return {
                        'uuid': uuid,
                        'version_label': f"v{lookdev.version:03d}",
                        'status': 'archived' if lookdev.is_archived else '',
                        'preview_path': str(lookdev.file_path) if lookdev.file_path.exists() else '',
                        'frame_count': lookdev.metadata.frame_count if lookdev.metadata else 0,
                        'fps': lookdev.metadata.fps if lookdev.metadata else 24,
                    }
        return None

    # ==================== Drawover Canvas ====================

    def _position_drawover_canvas(self):
        """Position drawover canvas over video content area."""
        video_label = self._video_preview.video_label
        video_rect = self._video_preview.get_video_display_rect()

        self._drawover_canvas.setParent(video_label)

        if video_rect and video_rect.isValid():
            self._drawover_canvas.setGeometry(video_rect)
            local_rect = QRectF(0, 0, video_rect.width(), video_rect.height())
            self._drawover_canvas.set_video_rect(local_rect)
        else:
            self._drawover_canvas.setGeometry(0, 0, video_label.width(), video_label.height())
            self._drawover_canvas.set_video_rect(QRectF(0, 0, video_label.width(), video_label.height()))

        self._drawover_canvas.raise_()

    def resizeEvent(self, event):
        """Handle resize - reposition canvas and refresh strokes."""
        super().resizeEvent(event)
        if hasattr(self, '_drawover_canvas') and self._drawover_canvas.isVisible():
            # Delay to allow layout to update
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, self._on_resize_complete)

    def _on_resize_complete(self):
        """Called after resize to update canvas position."""
        self._position_drawover_canvas()
        self._drawover_canvas.refresh_strokes()

    def _load_drawover_for_frame(self, frame: int):
        """Load drawover data for a specific frame with Hide/Hold/Ghost support."""
        if not self._selected_uuid or not self._selected_version_label:
            return

        # Hide mode: the canvas's stroke state is stale (last-loaded frame still in _item_data).
        # Both save and load must be skipped so that stale state isn't written to disk for
        # every frame the user scrubs past. Just track the frame so other UI stays in sync.
        if self._hide_annotations:
            self._drawover_canvas.hide()
            self._current_drawover_frame = frame
            return

        # Save previous frame's annotations (only if not from Hold)
        if self._current_drawover_frame >= 0 and self._current_drawover_frame != frame:
            if not self._strokes_from_hold:
                self._save_current_drawover()

        self._current_drawover_frame = frame
        self._strokes_from_hold = False

        # Position canvas
        self._position_drawover_canvas()

        # Clear ghost strokes first
        self._drawover_canvas.clear_ghost_strokes()

        # Load strokes for current frame (or held frame if Hold enabled)
        strokes, canvas_size, from_hold = self._get_strokes_for_frame(frame)
        self._strokes_from_hold = from_hold

        # Import strokes
        source_size = tuple(canvas_size) if canvas_size else None
        self._drawover_canvas.import_strokes(strokes, source_size)

        # Handle Ghost mode
        if self._ghost_enabled:
            self._add_ghost_strokes_for_frame(frame)

        # Show canvas
        self._drawover_canvas.show()
        # Always allow drawing - drawing on held frames creates new annotation frames
        self._drawover_canvas.read_only = False
        # Preserve current tool selection (don't reset to PEN)

        # Update UI buttons
        self._update_drawover_buttons()
        self._update_annotation_nav_buttons()

    def _get_strokes_for_frame(self, frame: int):
        """
        Get strokes for a frame, with Hold mode support.

        Returns:
            (strokes, canvas_size, from_hold) tuple
        """
        # Check cache first
        cached = self._drawover_cache.get(
            self._selected_uuid,
            self._selected_version_label,
            frame
        )

        if cached:
            strokes = cached.get('strokes', [])
            canvas_size = cached.get('canvas_size')
            if strokes:
                return strokes, canvas_size, False

        # Load from storage
        data = self._drawover_storage.load_drawover(
            self._selected_uuid,
            self._selected_version_label,
            frame
        )

        if data:
            strokes = data.get('strokes', [])
            canvas_size = data.get('canvas_size')
            self._drawover_cache.put(
                self._selected_uuid,
                self._selected_version_label,
                frame,
                data
            )
            if strokes:
                return strokes, canvas_size, False

        # If Hold enabled and no strokes, search backwards
        if self._hold_enabled and self._annotation_frames:
            prev_frames = [f for f in self._annotation_frames if f < frame]
            if prev_frames:
                held_frame = max(prev_frames)
                cached = self._drawover_cache.get(
                    self._selected_uuid,
                    self._selected_version_label,
                    held_frame
                )
                if cached:
                    return cached.get('strokes', []), cached.get('canvas_size'), True

                data = self._drawover_storage.load_drawover(
                    self._selected_uuid,
                    self._selected_version_label,
                    held_frame
                )
                if data:
                    strokes = data.get('strokes', [])
                    canvas_size = data.get('canvas_size')
                    self._drawover_cache.put(
                        self._selected_uuid,
                        self._selected_version_label,
                        held_frame,
                        data
                    )
                    return strokes, canvas_size, True

        return [], None, False

    def _add_ghost_strokes_for_frame(self, frame: int):
        """Add ghost/onion skin strokes from neighboring frames."""
        before_count = self._ghost_settings.get('before_frames', 2)
        after_count = self._ghost_settings.get('after_frames', 2)
        before_color = self._ghost_settings.get('before_color', QColor("#FF5555"))
        after_color = self._ghost_settings.get('after_color', QColor("#55FF55"))
        sketches_only = self._ghost_settings.get('sketches_only', True)

        total_frames = self._total_frames

        if sketches_only:
            if not self._annotation_frames:
                return
            before_frames = sorted([f for f in self._annotation_frames if f < frame], reverse=True)
            before_frames = before_frames[:before_count]
            after_frames = sorted([f for f in self._annotation_frames if f > frame])
            after_frames = after_frames[:after_count]
        else:
            before_frames = [frame - i for i in range(1, before_count + 1) if frame - i >= 0]
            after_frames = [frame + i for i in range(1, after_count + 1) if frame + i < total_frames]

        # Add ghost strokes for "before" frames
        for idx, ghost_frame in enumerate(before_frames):
            strokes, canvas_size = self._load_strokes_from_storage(ghost_frame)
            if strokes:
                distance = idx + 1
                opacity = 0.5 / distance
                self._drawover_canvas.add_ghost_strokes(
                    strokes, before_color, opacity,
                    tuple(canvas_size) if canvas_size else None
                )

        # Add ghost strokes for "after" frames
        for idx, ghost_frame in enumerate(after_frames):
            strokes, canvas_size = self._load_strokes_from_storage(ghost_frame)
            if strokes:
                distance = idx + 1
                opacity = 0.5 / distance
                self._drawover_canvas.add_ghost_strokes(
                    strokes, after_color, opacity,
                    tuple(canvas_size) if canvas_size else None
                )

    def _load_strokes_from_storage(self, frame: int):
        """Load strokes from storage (with caching)."""
        cached = self._drawover_cache.get(
            self._selected_uuid,
            self._selected_version_label,
            frame
        )
        if cached:
            return cached.get('strokes', []), cached.get('canvas_size')

        data = self._drawover_storage.load_drawover(
            self._selected_uuid,
            self._selected_version_label,
            frame
        )
        if data:
            self._drawover_cache.put(
                self._selected_uuid,
                self._selected_version_label,
                frame,
                data
            )
            return data.get('strokes', []), data.get('canvas_size')

        return [], None

    def _save_current_drawover(self):
        """Save current frame's drawover to storage."""
        if self._current_drawover_frame < 0 or not self._selected_uuid or not self._selected_version_label:
            return

        # Never save strokes from Hold mode
        if self._strokes_from_hold:
            return

        strokes = self._drawover_canvas.export_strokes()
        video_label = self._video_preview.video_label

        # Persist the empty state too, but only if the frame previously had
        # strokes on disk — otherwise we'd create noise files for every frame
        # the user scrubbed past with an empty canvas.
        had_existing = (
            not strokes
            and self._drawover_storage.has_drawover(
                self._selected_uuid,
                self._selected_version_label,
                self._current_drawover_frame,
            )
        )

        if strokes or had_existing:
            canvas_size = (video_label.width(), video_label.height())

            success = self._drawover_storage.save_drawover(
                self._selected_uuid,
                self._selected_version_label,
                self._current_drawover_frame,
                strokes,
                author=self._current_user,
                canvas_size=canvas_size
            )

            if success:
                # Invalidate cache
                self._drawover_cache.invalidate(
                    self._selected_uuid,
                    self._selected_version_label,
                    self._current_drawover_frame
                )

                # Log action + update metadata atomically so the audit trail
                # and per-frame metadata can't drift out of sync.
                authors = set(s.get('author', '') for s in strokes if s.get('author'))
                if self._is_studio_mode:
                    self._notes_db.log_drawover_with_metadata(
                        self._selected_uuid,
                        self._selected_version_label,
                        self._current_drawover_frame,
                        'saved',
                        self._current_user,
                        self._current_user_role,
                        stroke_count=len(strokes),
                        authors=','.join(authors),
                        details={'stroke_count': len(strokes)},
                    )
                else:
                    self._notes_db.update_drawover_metadata(
                        self._selected_uuid,
                        self._selected_version_label,
                        self._current_drawover_frame,
                        len(strokes),
                        ','.join(authors)
                    )

                # Update annotation markers
                self._load_annotation_markers()

    def _on_drawing_started(self):
        """Handle drawing start - clear held strokes if drawing on a held frame."""
        # If starting to draw on a held frame, clear the canvas first
        # User wants to create a fresh annotation, not include the held strokes
        if self._strokes_from_hold:
            self._drawover_canvas.clear()
            self._strokes_from_hold = False

    def _on_drawover_modified(self):
        """Handle drawover canvas modification."""
        self._update_drawover_buttons()

    def _on_drawing_finished(self):
        """Handle drawing stroke completion - save and update markers."""
        # Save the current frame's annotations
        self._save_current_drawover()

        # Update annotation markers on timeline
        self._load_annotation_markers()

        # Update undo/redo buttons
        self._update_drawover_buttons()

    def _on_tool_selected(self, tool: DrawingTool):
        """Handle tool selection from compact toolbar."""
        self._drawover_canvas.set_tool(tool)

    def _on_draw_color_changed(self, color: QColor):
        """Handle color change from ColorPicker widget."""
        self._drawover_canvas.color = color

    def _on_drawover_undo(self):
        """Undo last stroke."""
        self._drawover_canvas.undo_stack.undo()
        self._update_drawover_buttons()

    def _on_drawover_redo(self):
        """Redo last undone stroke."""
        self._drawover_canvas.undo_stack.redo()
        self._update_drawover_buttons()

    def _on_drawover_clear(self):
        """Clear all strokes on current frame - immediate, no confirmation."""
        from PyQt6.QtWidgets import QMessageBox

        # If showing held strokes from another frame, can't clear
        if self._strokes_from_hold:
            return

        # Check if there are any strokes to clear
        strokes = self._drawover_canvas.export_strokes()
        if not strokes:
            return

        # Check permissions for clearing in studio mode
        if self._is_studio_mode:
            has_others = any(
                s.get('author', '') and s.get('author') != self._current_user
                for s in strokes
            )
            if not DrawoverPermissions.can_clear_frame(
                self._is_studio_mode,
                self._current_user_role,
                has_others
            ):
                QMessageBox.warning(
                    self,
                    "Permission Denied",
                    "You don't have permission to clear annotations from other users."
                )
                return

        # Clear from storage first
        if self._selected_uuid and self._selected_version_label:
            soft_delete = DrawoverPermissions.use_soft_delete(self._is_studio_mode)
            self._drawover_storage.clear_frame(
                self._selected_uuid,
                self._selected_version_label,
                self._current_drawover_frame,
                soft_delete=soft_delete,
                deleted_by=self._current_user
            )

            # Invalidate cache for this frame
            self._drawover_cache.invalidate(
                self._selected_uuid,
                self._selected_version_label,
                self._current_drawover_frame
            )

            # Log action
            if self._is_studio_mode:
                self._notes_db.log_drawover_action(
                    self._selected_uuid,
                    self._selected_version_label,
                    self._current_drawover_frame,
                    'cleared',
                    self._current_user,
                    self._current_user_role
                )

        # Clear canvas
        self._drawover_canvas.clear()
        self._update_drawover_buttons()

        # Update annotation markers on timeline
        self._load_annotation_markers()

    def _update_drawover_buttons(self):
        """Update undo/redo button enabled states."""
        if hasattr(self, '_annotation_toolbar'):
            self._annotation_toolbar.set_undo_enabled(self._drawover_canvas.undo_stack.canUndo())
            self._annotation_toolbar.set_redo_enabled(self._drawover_canvas.undo_stack.canRedo())

    # ==================== Export with Annotations ====================

    def _on_export_with_annotations(self):
        """Handle Export with Annotations button click."""
        if not self._selected_uuid or not self._selected_version_label:
            QMessageBox.warning(self, "No Version", "Please select a version to export.")
            return

        # Find the version data - check both playblasts and lookdevs
        version = None
        preview_path = ''
        fps = 24
        animation_name = 'animation'

        if self._preview_mode == 'lookdev':
            # Find lookdev version
            for lookdev in self._lookdev_versions:
                if f"lookdev_{lookdev.version}" == self._selected_uuid:
                    preview_path = str(lookdev.file_path) if lookdev.file_path.exists() else ''
                    fps = lookdev.metadata.fps if lookdev.metadata else 24
                    animation_name = lookdev.shot_folder.name if lookdev.shot_folder else 'lookdev'
                    version = lookdev
                    break
        else:
            # Find playblast version
            version = next((v for v in self._versions if v.get('uuid') == self._selected_uuid), None)
            if version:
                preview_path = version.get('preview_path', '')
                fps = version.get('fps', 24) or 24
                animation_name = version.get('name', 'animation')

        if not version:
            QMessageBox.warning(self, "Error", "Could not find version data.")
            return

        if not preview_path:
            QMessageBox.warning(self, "Error", "Video file not found.")
            return

        # Delegate to export manager (pass the correct storage for analysis mode)
        self._export_manager.start_export(
            video_path=preview_path,
            animation_uuid=self._selected_uuid,
            version_label=self._selected_version_label,
            animation_name=animation_name,
            fps=fps,
            storage=self._drawover_storage
        )

    # ==================== Keyboard Shortcuts ====================

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts for annotation mode."""
        key = event.key()

        # Only handle shortcuts if a version is selected and not in compare mode
        if not self._selected_uuid or self._compare_mode:
            super().keyPressEvent(event)
            return

        # A - Previous annotation
        if key == Qt.Key.Key_A:
            self._on_prev_annotation()
            event.accept()
            return

        # D - Next annotation
        if key == Qt.Key.Key_D:
            self._on_next_annotation()
            event.accept()
            return

        # V - Toggle hide annotations
        if key == Qt.Key.Key_V:
            self._hide_btn.setChecked(not self._hide_annotations)
            event.accept()
            return

        # H - Toggle hold frames
        if key == Qt.Key.Key_H:
            self._hold_btn.setChecked(not self._hold_enabled)
            event.accept()
            return

        # G - Toggle ghost/onion skin
        if key == Qt.Key.Key_G:
            self._on_ghost_btn_clicked(not self._ghost_enabled)
            event.accept()
            return

        # P - Pen tool
        if key == Qt.Key.Key_P:
            self._annotation_toolbar.set_tool(DrawingTool.PEN)
            event.accept()
            return

        # B - Brush tool
        if key == Qt.Key.Key_B:
            self._annotation_toolbar.set_tool(DrawingTool.BRUSH)
            event.accept()
            return

        # L - Line tool
        if key == Qt.Key.Key_L:
            self._annotation_toolbar.set_tool(DrawingTool.LINE)
            event.accept()
            return

        # R - Rectangle tool
        if key == Qt.Key.Key_R:
            self._annotation_toolbar.set_tool(DrawingTool.RECT)
            event.accept()
            return

        # C - Circle tool
        if key == Qt.Key.Key_C:
            self._annotation_toolbar.set_tool(DrawingTool.CIRCLE)
            event.accept()
            return

        super().keyPressEvent(event)

    def closeEvent(self, event):
        # Save any pending drawover changes (always-on mode)
        if not self._strokes_from_hold:
            self._save_current_drawover()

        self._video_preview.clear()
        self._comparison_widget.clear()
        super().closeEvent(event)


__all__ = ['VersionHistoryDialog']
