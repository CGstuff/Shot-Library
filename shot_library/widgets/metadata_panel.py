"""
MetadataPanel - Display shot/animation details

Pattern: QWidget with form layout
Adapted for Shot Library: Shows shot-specific metadata (scene, sequence, shot number, status)
"""

from pathlib import Path
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea,
    QFrame, QGridLayout, QPushButton, QHBoxLayout, QMenu, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QCursor

from ..themes.theme_manager import get_theme_manager
from ..themes.fonts import Fonts, get_font_stylesheet
from ..config import Config
from ..services.database_service import get_database_service
from ..services.shot_data_service import get_shot_data_service, ShotDataService
from .video_preview_widget import VideoPreviewWidget
from .dialogs import VersionHistoryDialog


class MetadataPanel(QWidget):
    """
    Panel for displaying shot metadata

    Features (Shot Library):
    - Shot name and editorial order
    - Shot identity (Episode, Sequence, Scene, Shot number)
    - Production status (WIP, Review, Approved, Blocked)
    - Playblast information (version, duration, resolution)
    - File paths
    - Timestamps
    - Playblast version lineage

    Layout:
        ┌─────────────────┐
        │  Shot Name      │
        │  Editorial Order│
        ├─────────────────┤
        │  Shot Identity  │
        │  - Episode      │
        │  - Sequence     │
        │  - Scene        │
        │  - Shot Number  │
        ├─────────────────┤
        │  Status         │
        │  [WIP/REVIEW]   │
        ├─────────────────┤
        │  Playblast Info │
        │  - Version      │
        │  - Duration     │
        │  - Resolution   │
        ├─────────────────┤
        │  Lineage        │
        │  v003 [LATEST]  │
        │  [View Lineage] │
        └─────────────────┘
    """

    # Signals
    version_changed = pyqtSignal(str)  # Emits UUID when version changes
    notes_changed = pyqtSignal()  # Emitted when notes may have changed (dialog closed)

    def __init__(self, parent=None, theme_manager=None, event_bus=None, db_service=None, shot_data_service=None):
        super().__init__(parent)

        # Current animation
        self._animation: Optional[Dict[str, Any]] = None

        # Preview mode (playblast, lookdev, or render)
        self._preview_mode: str = "playblast"

        # Analysis mode (changes button text from "View Lineage" to "Analyze")
        self._analysis_mode: bool = False

        # Services (injectable for testing)
        self._theme_manager = theme_manager or get_theme_manager()
        self._db_service = db_service  # Lazy init via _get_db_service()
        self._shot_data_service = shot_data_service  # Lazy init via _get_shot_data_service()
        self._audit_service = None  # Set via set_audit_service()

        # Camera-views enrichment cache. Keyed by master shot id; survives mode
        # toggles on the same shot, cleared on set_animation() so external refreshes
        # see fresh data.
        self._views_cache_shot_id: Optional[str] = None
        self._views_cache_data: Optional[list] = None

        # Event bus for application events
        from ..events.event_bus import get_event_bus
        self._event_bus = event_bus or get_event_bus()

        # Setup UI
        self._create_widgets()
        self._create_layout()


        # Set minimum width
        self.setMinimumWidth(300)

    def _get_db_service(self):
        """Get database service (lazy initialization)"""
        if self._db_service is None:
            self._db_service = get_database_service()
        return self._db_service

    def _get_shot_data_service(self) -> ShotDataService:
        """Get shot data service (lazy initialization)"""
        if self._shot_data_service is None:
            self._shot_data_service = get_shot_data_service()
        return self._shot_data_service

    def set_audit_service(self, audit_service):
        """
        Set the audit service for status change logging.

        Args:
            audit_service: AuditService instance
        """
        self._audit_service = audit_service

    def _create_widgets(self):
        """Create panel widgets"""

        # Scroll area for content
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        # Content widget
        self._content_widget = QWidget()

        # Description label (for shot notes/description)
        self._description_label = QLabel("")
        self._description_label.setWordWrap(True)

        # Create info sections (Shot Library specific)
        self._shot_identity_section = self._create_section("Shot Identity")
        self._shot_info_section = self._create_section("Shot Info")  # v12: read-only frame range + description
        self._technical_section, self._technical_section_title = self._create_section_with_title("Playblast Info")
        self._assignment_section = self._create_assignment_section()
        self._file_section = self._create_section("Files")
        self._version_section = self._create_version_section()
        self._pose_actions_section = self._create_pose_actions_section()
        self._camera_views_section = self._create_camera_views_section()

        # Standalone analyze button (shown only in analysis mode, separate from version section)
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_view_history_clicked)
        self._analyze_btn.setToolTip("Open reference video for annotation and analysis")
        self._analyze_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
            }
        """)
        self._analyze_btn.hide()  # Hidden by default, shown only in analysis mode

    def _create_section(self, title: str) -> QWidget:
        """Create a metadata section with highlighted header"""

        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 8)

        # Section title with subtle background
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)

        # Add subtle gray background for header differentiation
        title_label.setStyleSheet("""
            QLabel {
                background-color: rgba(128, 128, 128, 0.15);
                padding: 4px 8px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(title_label)

        # Grid for key-value pairs
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # Store grid for later updates
        section.setProperty("grid", grid)

        return section

    def _create_section_with_title(self, title: str) -> tuple:
        """Create a metadata section with highlighted header, returning both section and title label"""

        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 8)

        # Section title with subtle background
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)

        # Add subtle gray background for header differentiation
        title_label.setStyleSheet("""
            QLabel {
                background-color: rgba(128, 128, 128, 0.15);
                padding: 4px 8px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(title_label)

        # Grid for key-value pairs
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # Store grid for later updates
        section.setProperty("grid", grid)

        return section, title_label

    def _create_preview_section(self) -> QWidget:
        """Create video preview section using VideoPreviewWidget"""
        self._video_preview = VideoPreviewWidget()
        return self._video_preview

    def _create_version_section(self) -> QWidget:
        """Create version information section with history button and status badge"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 8)

        # Section title with subtle background
        title_label = QLabel("Lineage")
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("""
            QLabel {
                background-color: rgba(128, 128, 128, 0.15);
                padding: 4px 8px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(title_label)

        # Version info container
        info_widget = QWidget()
        info_layout = QHBoxLayout(info_widget)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.setSpacing(8)

        # Version label (e.g., "v001")
        self._version_label = QLabel("v001")
        self._version_label.setStyleSheet(f"{get_font_stylesheet(Fonts.HEADER_SMALL)}")
        info_layout.addWidget(self._version_label)

        # Latest badge
        self._latest_badge = QLabel("LATEST")
        self._latest_badge.setStyleSheet(f"""
            QLabel {{
                background-color: #4CAF50;
                color: white;
                padding: 2px 6px;
                {get_font_stylesheet(Fonts.CAPTION)}
            }}
        """)
        info_layout.addWidget(self._latest_badge)

        # Comment indicator (shows when animation has unresolved review comments)
        self._comment_widget = QWidget()
        comment_layout = QHBoxLayout(self._comment_widget)
        comment_layout.setContentsMargins(0, 0, 0, 0)
        comment_layout.setSpacing(4)

        # Info icon
        from ..utils.icon_loader import IconLoader
        from PyQt6.QtGui import QIcon
        self._comment_icon = QLabel()
        try:
            icon_path = IconLoader.get("info")
            self._comment_icon.setPixmap(QIcon(icon_path).pixmap(14, 14))
        except Exception:
            pass
        self._comment_icon.setFixedSize(14, 14)
        comment_layout.addWidget(self._comment_icon)

        # Comment count text
        self._comment_indicator = QLabel("0")
        self._comment_indicator.setStyleSheet(f"""
            QLabel {{
                color: #E91E63;
                {get_font_stylesheet(Fonts.CAPTION)}
            }}
        """)
        comment_layout.addWidget(self._comment_indicator)

        self._comment_widget.hide()  # Hidden by default
        info_layout.addWidget(self._comment_widget)

        # Version count label
        self._version_count_label = QLabel("")
        self._version_count_label.setStyleSheet(f"color: #888; {get_font_stylesheet(Fonts.CAPTION)}")
        info_layout.addWidget(self._version_count_label)

        info_layout.addStretch()
        layout.addWidget(info_widget)

        # Status row
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(8, 4, 8, 4)
        status_layout.setSpacing(8)

        # Status label
        status_text = QLabel("Status:")
        status_text.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(status_text)

        # Status badge (clickable button styled as badge)
        self._status_badge = QPushButton("WIP")
        self._status_badge.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._status_badge.clicked.connect(self._on_status_badge_clicked)
        self._update_status_badge_style('wip')
        status_layout.addWidget(self._status_badge)

        # Per-shot PB/LD/RD mode buttons (Blender-style shading icons)
        from ..utils.icon_loader import IconLoader
        from PyQt6.QtGui import QIcon
        from PyQt6.QtCore import QSize

        btn_style_unchecked = """
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """
        btn_style_checked = """
            QPushButton {
                background-color: #5b8cc9;
                border: none;
                border-radius: 3px;
            }
        """
        btn_style_rd_checked = """
            QPushButton {
                background-color: #c97b5b;
                border: none;
                border-radius: 3px;
            }
        """

        self._pb_mode_btn = QPushButton()
        self._pb_mode_btn.setFixedSize(28, 28)
        self._pb_mode_btn.setCheckable(True)
        self._pb_mode_btn.setChecked(True)
        self._pb_mode_btn.setToolTip("Playblast mode")
        self._pb_mode_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            pb_icon = QIcon(IconLoader.get("shading_solid"))
            self._pb_mode_btn.setIcon(pb_icon)
            self._pb_mode_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._pb_mode_btn.setText("PB")
        self._pb_mode_btn.clicked.connect(self._on_pb_mode_clicked)
        status_layout.addWidget(self._pb_mode_btn)

        self._ld_mode_btn = QPushButton()
        self._ld_mode_btn.setFixedSize(28, 28)
        self._ld_mode_btn.setCheckable(True)
        self._ld_mode_btn.setChecked(False)
        self._ld_mode_btn.setToolTip("Lookdev mode")
        self._ld_mode_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            ld_icon = QIcon(IconLoader.get("shading_texture"))
            self._ld_mode_btn.setIcon(ld_icon)
            self._ld_mode_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._ld_mode_btn.setText("LD")
        self._ld_mode_btn.clicked.connect(self._on_ld_mode_clicked)
        status_layout.addWidget(self._ld_mode_btn)

        self._rd_mode_btn = QPushButton()
        self._rd_mode_btn.setFixedSize(28, 28)
        self._rd_mode_btn.setCheckable(True)
        self._rd_mode_btn.setChecked(False)
        self._rd_mode_btn.setToolTip("Render mode")
        self._rd_mode_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            rd_icon = QIcon(IconLoader.get("shading_rendered"))
            self._rd_mode_btn.setIcon(rd_icon)
            self._rd_mode_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._rd_mode_btn.setText("RD")
        self._rd_mode_btn.clicked.connect(self._on_rd_mode_clicked)
        status_layout.addWidget(self._rd_mode_btn)

        # Add to Render Manager button
        self._add_to_rm_btn = QPushButton()
        self._add_to_rm_btn.setFixedSize(28, 28)
        self._add_to_rm_btn.setToolTip("Add to Render Manager")
        self._add_to_rm_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            rm_icon = QIcon(IconLoader.get("render"))
            self._add_to_rm_btn.setIcon(rm_icon)
            self._add_to_rm_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._add_to_rm_btn.setText("+R")
        self._add_to_rm_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(201, 123, 91, 0.3);
            }
        """)
        self._add_to_rm_btn.clicked.connect(self._on_add_to_render_manager)
        status_layout.addWidget(self._add_to_rm_btn)

        # Store style strings for later use
        self._btn_style_unchecked = btn_style_unchecked
        self._btn_style_checked = btn_style_checked
        self._btn_style_rd_checked = btn_style_rd_checked
        self._update_mode_buttons_style('playblast')

        status_layout.addStretch()
        layout.addWidget(status_widget)

        # Priority row (v12) — sits directly below status, same shape.
        priority_widget = QWidget()
        priority_layout = QHBoxLayout(priority_widget)
        priority_layout.setContentsMargins(8, 4, 8, 4)
        priority_layout.setSpacing(8)

        priority_text = QLabel("Priority:")
        priority_text.setStyleSheet("font-weight: bold;")
        priority_layout.addWidget(priority_text)

        self._priority_badge = QPushButton("NORMAL")
        self._priority_badge.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._priority_badge.clicked.connect(self._on_priority_badge_clicked)
        self._update_priority_badge_style(2)
        priority_layout.addWidget(self._priority_badge)

        priority_layout.addStretch()
        layout.addWidget(priority_widget)

        # View History button
        self._history_btn = QPushButton("View Lineage")
        self._history_btn.clicked.connect(self._on_view_history_clicked)
        self._history_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
            }
        """)
        layout.addWidget(self._history_btn)

        return section

    def _create_pose_actions_section(self) -> QWidget:
        """Create pose-specific action buttons (only shown for poses)"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 8)

        # Section title
        title_label = QLabel("Pose Actions")
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("""
            QLabel {
                background-color: rgba(128, 128, 128, 0.15);
                padding: 4px 8px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(title_label)

        # Select Bones button
        self._select_bones_btn = QPushButton("Select Bones")
        self._select_bones_btn.setToolTip(
            "Click: Select pose bones in Blender\n"
            "Ctrl+Click: Mirror selection (L↔R)\n"
            "Ctrl+Shift+Click: Add to current selection"
        )
        self._select_bones_btn.clicked.connect(self._on_select_bones_clicked)
        self._select_bones_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
            }
        """)
        layout.addWidget(self._select_bones_btn)

        section.hide()  # Hidden by default, shown only for poses
        return section

    def _create_camera_views_section(self) -> QWidget:
        """Create camera views section for multi-camera master shots."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 8)

        # Section title
        title_label = QLabel("📹 Camera Views")
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("""
            QLabel {
                background-color: rgba(33, 150, 243, 0.2);
                padding: 4px 8px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(title_label)

        # View count label
        self._view_count_label = QLabel("0 views")
        self._view_count_label.setStyleSheet(f"color: #888; {get_font_stylesheet(Fonts.CAPTION)} padding-left: 8px;")
        layout.addWidget(self._view_count_label)

        # Views list container
        self._views_list_widget = QWidget()
        self._views_list_layout = QVBoxLayout(self._views_list_widget)
        self._views_list_layout.setContentsMargins(8, 4, 8, 4)
        self._views_list_layout.setSpacing(4)
        layout.addWidget(self._views_list_widget)

        section.hide()  # Hidden by default, shown only for master shots
        return section

    def _create_assignment_section(self) -> QWidget:
        """Create task assignment section (Pipeline Control integration)"""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 8)

        # Section title
        title_label = QLabel("Assignment")
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("""
            QLabel {
                background-color: rgba(128, 128, 128, 0.15);
                padding: 4px 8px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(title_label)

        # Grid for assignment info
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        # Assignee row
        self._assignee_label = QLabel("Not assigned")
        self._assignee_label.setStyleSheet("color: #888888;")
        grid.addWidget(QLabel("Assignee:"), 0, 0)
        grid.addWidget(self._assignee_label, 0, 1)

        # Priority row
        self._priority_label = QLabel("-")
        self._priority_label.setStyleSheet("color: #888888;")
        grid.addWidget(QLabel("Priority:"), 1, 0)
        grid.addWidget(self._priority_label, 1, 1)

        # Due date row
        self._due_date_label = QLabel("-")
        self._due_date_label.setStyleSheet("color: #888888;")
        grid.addWidget(QLabel("Due Date:"), 2, 0)
        grid.addWidget(self._due_date_label, 2, 1)

        # Task status row
        self._task_status_label = QLabel("-")
        self._task_status_label.setStyleSheet("color: #888888;")
        grid.addWidget(QLabel("Task Status:"), 3, 0)
        grid.addWidget(self._task_status_label, 3, 1)

        layout.addLayout(grid)

        # Mark Done button (only shown when assigned to current user)
        self._mark_done_btn = QPushButton("Mark Done")
        self._mark_done_btn.clicked.connect(self._on_mark_done_clicked)
        self._mark_done_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """)
        self._mark_done_btn.hide()  # Hidden until a task is assigned
        layout.addWidget(self._mark_done_btn)

        section.hide()  # Hidden by default, shown when task exists
        return section

    def _update_status_badge_style(self, status: str):
        """Update the status badge appearance based on status"""
        from ..services.control_authority import get_control_authority
        
        status_info = Config.LIFECYCLE_STATUSES.get(status, {'color': '#9E9E9E', 'label': status.upper()})
        color = status_info['color']
        label = status_info['label']

        self._status_badge.setText(label)
        
        # Check if status editing is allowed
        can_edit = get_control_authority().can_edit_status()
        
        # Update cursor based on edit capability
        if can_edit:
            self._status_badge.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        else:
            self._status_badge.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        # Special styling for 'none' status - subtle/muted appearance
        status_font = get_font_stylesheet(Fonts.BUTTON)
        if status == 'none' or color is None:
            if can_edit:
                self._status_badge.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #404040;
                        color: #888888;
                        padding: 4px 10px;
                        border-radius: 0px;
                        {status_font}
                        border: 1px solid #555555;
                    }}
                    QPushButton:hover {{
                        background-color: #505050;
                        border: 1px solid #666666;
                    }}
                """)
            else:
                # No hover effect in Pipeline Mode
                self._status_badge.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #404040;
                        color: #888888;
                        padding: 4px 10px;
                        border-radius: 0px;
                        {status_font}
                        border: 1px solid #555555;
                    }}
                """)
        else:
            if can_edit:
                self._status_badge.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color};
                        color: white;
                        padding: 4px 10px;
                        border-radius: 0px;
                        {status_font}
                        border: none;
                    }}
                    QPushButton:hover {{
                        background-color: {color};
                        border: 2px solid white;
                    }}
                """)
            else:
                # No hover effect in Pipeline Mode
                self._status_badge.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color};
                        color: white;
                        padding: 4px 10px;
                        border-radius: 0px;
                        {status_font}
                        border: none;
                    }}
                """)

    def _update_mode_buttons_style(self, mode: str):
        """Update the per-shot preview mode buttons appearance based on mode"""
        # Update checked state
        self._pb_mode_btn.setChecked(mode == 'playblast')
        self._ld_mode_btn.setChecked(mode == 'lookdev')
        self._rd_mode_btn.setChecked(mode == 'render')

        # Update styles
        self._pb_mode_btn.setStyleSheet(
            self._btn_style_checked if mode == 'playblast' else self._btn_style_unchecked
        )
        self._ld_mode_btn.setStyleSheet(
            self._btn_style_checked if mode == 'lookdev' else self._btn_style_unchecked
        )
        self._rd_mode_btn.setStyleSheet(
            self._btn_style_rd_checked if mode == 'render' else self._btn_style_unchecked
        )

    def _create_layout(self):
        """Create panel layout with resizable preview"""

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Create vertical splitter for resizable preview
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(6)
        self._splitter.setStyleSheet("""
            QSplitter::handle {
                background: #3a3a3a;
            }
            QSplitter::handle:hover {
                background: #3A8FB7;
            }
        """)

        # Top: Video preview
        self._splitter.addWidget(self._create_preview_section())

        # Bottom: Info sections in scroll area
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content_layout.addWidget(self._version_section)
        content_layout.addWidget(self._analyze_btn)  # Standalone button for analysis mode
        content_layout.addWidget(self._pose_actions_section)
        content_layout.addWidget(self._camera_views_section)  # Multi-camera views section
        content_layout.addWidget(self._shot_identity_section)  # Shot-specific section
        content_layout.addWidget(self._shot_info_section)  # v12: frame range, priority, description
        content_layout.addWidget(self._assignment_section)  # Task assignment section
        content_layout.addWidget(self._technical_section)
        content_layout.addWidget(self._description_label)
        content_layout.addWidget(self._file_section)

        self._scroll_area.setWidget(self._content_widget)
        self._splitter.addWidget(self._scroll_area)

        # Set initial sizes (preview takes ~40% of space)
        self._splitter.setSizes([300, 400])

        # Add splitter to main layout
        main_layout.addWidget(self._splitter)

    def set_preview_mode(self, mode: str):
        """
        Set preview mode (playblast, lookdev, or render) and refresh display.

        Args:
            mode: 'playblast', 'lookdev', or 'render'
        """
        if mode not in ('playblast', 'lookdev', 'render'):
            return

        self._preview_mode = mode

        # Update section header
        if mode == "render":
            self._technical_section_title.setText("Render Info")
        elif mode == "lookdev":
            self._technical_section_title.setText("Lookdev Info")
        else:
            self._technical_section_title.setText("Playblast Info")

        # Refresh display if animation is set
        if self._animation:
            self._update_video_preview()
            self._update_technical_section()
            self._update_version_section()
            self._update_camera_views_section()  # Refresh to show PB/LD versions

    def _update_video_preview(self):
        """Update video preview based on current preview mode"""
        if not self._animation:
            self._video_preview.clear()
            return

        # Get video path based on preview mode
        if self._preview_mode == "render":
            preview_path = self._animation.get('render_proxy_path', '')
        elif self._preview_mode == "lookdev":
            preview_path = self._animation.get('latest_lookdev_path', '')
        else:
            preview_path = self._animation.get('latest_playblast_path') or self._animation.get('preview_path', '')

        if preview_path:
            # Check if stored path exists, otherwise resolve to archive location
            if not Path(preview_path).exists():
                shot_data_service = self._get_shot_data_service()
                resolved = shot_data_service.resolve_preview_file(self._animation)
                if resolved:
                    preview_path = str(resolved)
            self._video_preview.load_video(preview_path)
        else:
            self._video_preview.clear()

    def set_animation(self, animation: Dict[str, Any]):
        """
        Display shot/animation metadata

        Args:
            animation: Shot/animation data dict (supports both shot and animation fields)
        """
        self._animation = animation

        # Invalidate camera-views cache on any (re)load so external scans show fresh data.
        self._views_cache_shot_id = None
        self._views_cache_data = None

        # Load video preview based on preview mode
        self._update_video_preview()

        # Description now lives in the Shot Info section (v12). Keep the legacy
        # standalone label hidden to avoid duplication.
        self._description_label.hide()

        # Update shot identity section (Shot Library specific)
        self._update_shot_identity_section()

        # Update shot info section (v12: frame range, priority, description)
        self._update_shot_info_section()

        # Update technical info (playblast info for shots)
        self._update_technical_section()

        # Update file info
        self._update_file_section()

        # Update version info
        self._update_version_section()

        # Update assignment section (Pipeline Control)
        self._update_assignment_section()

        # Update camera views section (multi-camera master shots)
        self._update_camera_views_section()

        # Show/hide pose actions section
        is_pose = animation.get('is_pose', 0)
        self._pose_actions_section.setVisible(bool(is_pose))

    def clear(self):
        """Clear panel"""
        self._animation = None
        self._description_label.clear()
        self._description_label.hide()

        # Clear video preview
        self._video_preview.clear()

        # Clear sections
        self._clear_section(self._shot_identity_section)
        self._clear_section(self._shot_info_section)
        self._shot_info_section.hide()
        self._clear_section(self._technical_section)
        self._clear_section(self._file_section)

        # Clear version section
        self._version_label.setText("v001")
        self._latest_badge.hide()
        self._version_count_label.setText("")
        self._history_btn.setEnabled(False)
        self._update_status_badge_style('none')  # Reset status badge
        self._update_priority_badge_style(2)  # Reset priority badge to NORMAL
        self._update_mode_buttons_style('playblast')  # Reset preview mode buttons

        # Hide pose actions section
        self._pose_actions_section.hide()

    def _update_shot_identity_section(self):
        """Update shot identity section (Episode, Sequence, Scene, Shot numbers)"""

        if not self._animation:
            self._shot_identity_section.hide()
            return

        # Hide in analysis mode - no shot identity needed for reference videos
        if self._analysis_mode:
            self._shot_identity_section.hide()
            return

        grid = self._shot_identity_section.property("grid")
        self._clear_grid(grid)

        row = 0
        has_shot_data = False

        # Shot name
        shot_name = self._animation.get('shot_name') or self._animation.get('name')
        if shot_name:
            self._add_info_row(grid, row, "Shot Name:", shot_name)
            row += 1
            has_shot_data = True

        # Editorial order
        editorial_order = self._animation.get('editorial_order')
        if editorial_order and editorial_order != "9999.9999.9999.9999":
            self._add_info_row(grid, row, "Editorial Order:", editorial_order)
            row += 1
            has_shot_data = True

        # Episode number
        episode_num = self._animation.get('episode_num')
        if episode_num is not None and episode_num > 0:
            self._add_info_row(grid, row, "Episode:", f"EP{episode_num:02d}")
            row += 1
            has_shot_data = True

        # Sequence number
        sequence_num = self._animation.get('sequence_num')
        if sequence_num is not None and sequence_num > 0:
            self._add_info_row(grid, row, "Sequence:", f"SQ{sequence_num:03d}")
            row += 1
            has_shot_data = True

        # Scene number
        scene_num = self._animation.get('scene_num')
        if scene_num is not None and scene_num > 0:
            self._add_info_row(grid, row, "Scene:", f"SC{scene_num:02d}")
            row += 1
            has_shot_data = True

        # Shot number
        shot_num = self._animation.get('shot_num')
        if shot_num is not None and shot_num > 0:
            self._add_info_row(grid, row, "Shot:", f"SH{shot_num:03d}")
            row += 1
            has_shot_data = True

        # Shot version info (for versioned shots like shot1_v003)
        base_shot_name = self._animation.get('base_shot_name')
        shot_version = self._animation.get('shot_version')
        if base_shot_name and shot_version is not None:
            self._add_info_row(grid, row, "Base Name:", base_shot_name)
            row += 1
            self._add_info_row(grid, row, "Shot Version:", f"v{shot_version:03d}")
            row += 1
            has_shot_data = True

        # Version count in group
        version_count = self._animation.get('version_count')
        if version_count is not None and version_count > 1:
            self._add_info_row(grid, row, "Versions in Group:", str(version_count))
            row += 1
            has_shot_data = True

        # Parse warning (for unparseable shot names)
        parse_warning = self._animation.get('parse_warning')
        if parse_warning:
            warning_label = QLabel(parse_warning)
            warning_label.setStyleSheet("color: #FFC107; font-style: italic;")
            warning_label.setWordWrap(True)
            grid.addWidget(warning_label, row, 0, 1, 2)
            row += 1
            has_shot_data = True

        # Show/hide section based on whether we have shot data
        self._shot_identity_section.setVisible(has_shot_data)

    def _get_project_resolution(self) -> tuple:
        """Read the project's configured render resolution from app_settings.

        Returns (width, height) — both 0 when unset. One SELECT against the
        per-project DB, called once per shot selection.
        """
        try:
            db = self._db_service or get_database_service()
            w = int(db.get_app_setting('project_resolution_width', '0') or '0')
            h = int(db.get_app_setting('project_resolution_height', '0') or '0')
            return (w, h)
        except (TypeError, ValueError, Exception):
            return (0, 0)

    def _update_shot_info_section(self):
        """Render Shot Info as read-only labels (v12 schema).

        Shot Library never authors shot metadata. Frame range / description live
        on the shot row; fps / duration / resolution come from the latest
        playblast (they're file-truth metadata, not shot-truth). Priority lives
        in the Lineage section as a colored badge below Status.
        """
        if not self._animation or self._analysis_mode:
            self._shot_info_section.hide()
            return

        grid = self._shot_info_section.property("grid")
        self._clear_grid(grid)

        frame_in = self._animation.get('frame_in')
        frame_out = self._animation.get('frame_out')
        description = (self._animation.get('description') or '').strip()

        # Pull playback metadata from the latest playblast — fps, duration and
        # resolution live on the playblasts table, not on shots.
        fps = None
        duration_seconds = None
        width = None
        height = None
        frame_count = None
        shot_uuid = self._animation.get('uuid') or self._animation.get('id')
        if shot_uuid:
            try:
                pb = self._get_shot_data_service().get_latest_playblast(shot_uuid)
            except Exception:
                pb = None
            if pb:
                fps = pb.get('fps')
                frame_count = pb.get('frame_count')
                duration_ms = pb.get('duration_ms')
                if duration_ms:
                    duration_seconds = duration_ms / 1000.0
                elif frame_count and fps:
                    duration_seconds = frame_count / fps
                width = pb.get('width')
                height = pb.get('height')

        row = 0
        has_data = False

        if fps:
            fps_text = f"{fps:g}" if isinstance(fps, float) else str(fps)
            self._add_info_row(grid, row, "FPS:", fps_text)
            row += 1
            has_data = True

        if frame_in is not None and frame_out is not None:
            self._add_info_row(grid, row, "Frame Range:", f"{frame_in} → {frame_out}")
            row += 1
            has_data = True
        elif frame_count:
            self._add_info_row(grid, row, "Frame Count:", str(frame_count))
            row += 1
            has_data = True

        if duration_seconds:
            self._add_info_row(grid, row, "Duration:", f"{duration_seconds:.2f}s")
            row += 1
            has_data = True

        # Resolution: prefer the configured project resolution (Settings →
        # Backup → Project Settings). The playblast pixels are demoted to a
        # parenthetical so the user can tell when their preview is a
        # downscaled proxy of a higher-res render.
        proj_w, proj_h = self._get_project_resolution()
        if proj_w and proj_h:
            text = f"{proj_w}×{proj_h}"
            if width and height and (width != proj_w or height != proj_h):
                pct = round((width / proj_w) * 100) if proj_w else None
                if pct and pct != 100:
                    text += f"  (preview: {width}×{height} @ {pct}%)"
                else:
                    text += f"  (preview: {width}×{height})"
            self._add_info_row(grid, row, "Resolution:", text)
            row += 1
            has_data = True
        elif width and height:
            # No project resolution configured — show playblast pixels as-is.
            self._add_info_row(grid, row, "Resolution:", f"{width}×{height}")
            row += 1
            has_data = True

        if description:
            self._add_info_row(grid, row, "Description:", description)
            row += 1
            has_data = True

        self._shot_info_section.setVisible(has_data)

    def _update_technical_section(self):
        """Update technical information section based on preview mode and analysis mode"""

        if not self._animation:
            return

        grid = self._technical_section.property("grid")
        self._clear_grid(grid)

        row = 0

        # Analysis mode: Show only video info (Frame Count, FPS, Duration, Resolution)
        if self._analysis_mode:
            # Frame count
            frame_count = self._animation.get('frame_count')
            if frame_count:
                self._add_info_row(grid, row, "Frame Count:", str(frame_count))
                row += 1

            # FPS
            fps = self._animation.get('fps')
            if fps:
                self._add_info_row(grid, row, "FPS:", str(fps))
                row += 1

            # Duration
            duration = self._animation.get('duration_seconds')
            if duration:
                self._add_info_row(grid, row, "Duration:", f"{duration:.2f}s")
                row += 1

            # Resolution (WxH)
            width = self._animation.get('width')
            height = self._animation.get('height')
            if width and height:
                self._add_info_row(grid, row, "Resolution:", f"{width}x{height}")
                row += 1

            return

        # Shot mode: Full playblast/lookdev/render info
        # Animation name (display only)
        name = self._animation.get('name')
        if name:
            self._add_info_row(grid, row, "Name:", name)
            row += 1

        # Show version info based on preview mode
        if self._preview_mode == "render":
            # Render proxy info
            render_proxy_path = self._animation.get('render_proxy_path')
            if render_proxy_path:
                proxy_name = Path(render_proxy_path).name
                self._add_info_row(grid, row, "Proxy:", proxy_name)
                row += 1

            has_render = self._animation.get('has_render', False)
            if has_render:
                self._add_info_row(grid, row, "Status:", "Has Render")
                row += 1
            else:
                self._add_info_row(grid, row, "Status:", "No Render")
                row += 1
        elif self._preview_mode == "lookdev":
            # Lookdev version
            lookdev_version = self._animation.get('latest_lookdev_version')
            if lookdev_version is not None:
                self._add_info_row(grid, row, "Version:", f"v{lookdev_version:03d}")
                row += 1

            # Lookdev count
            lookdev_count = self._animation.get('lookdev_count', 0)
            if lookdev_count > 0:
                self._add_info_row(grid, row, "Total Versions:", str(lookdev_count))
                row += 1
        else:
            # Playblast version
            playblast_version = self._animation.get('latest_playblast_version')
            if playblast_version is not None:
                self._add_info_row(grid, row, "Version:", f"v{playblast_version:03d}")
                row += 1

            # Playblast count
            playblast_count = self._animation.get('playblast_count', 0)
            if playblast_count > 0:
                self._add_info_row(grid, row, "Total Versions:", str(playblast_count))
                row += 1

        # Frame count / FPS / Duration now live in the Shot Info section
        # (sourced from the latest playblast). Don't duplicate them here.

    def _update_file_section(self):
        """Update file information section"""
        from ..utils.icon_loader import IconLoader
        from ..utils.icon_utils import colorize_white_svg
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtCore import QSize

        if not self._animation:
            return

        grid = self._file_section.property("grid")
        self._clear_grid(grid)

        row = 0

        # File size
        file_size = self._animation.get('file_size_mb')
        if file_size:
            self._add_info_row(grid, row, "File Size:", f"{file_size:.2f} MB")
            row += 1

        # Author
        author = self._animation.get('author')
        if author:
            self._add_info_row(grid, row, "Author:", author)
            row += 1

        # Created date
        created = self._animation.get('created_date')
        if created:
            self._add_info_row(grid, row, "Created:", str(created)[:10])  # Just date
            row += 1

        # Open in Blender button (for regular shots, not views)
        blend_file = self._animation.get('blend_file')
        if blend_file:
            label_widget = QLabel("Blend File:")
            label_font = QFont()
            label_font.setBold(True)
            label_widget.setFont(label_font)

            # Container for filename and button
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)

            # Filename
            filename = Path(blend_file).name if blend_file else "Unknown"
            filename_label = QLabel(filename)
            filename_label.setToolTip(blend_file)
            container_layout.addWidget(filename_label)

            container_layout.addStretch()

            # Open in Blender button
            open_btn = QPushButton()
            open_btn.setFixedSize(24, 24)
            open_btn.setToolTip("Open in Blender")
            open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            try:
                icon_path = IconLoader.get("blender")
                if icon_path:
                    open_btn.setIcon(QIcon(icon_path))
                    open_btn.setIconSize(QSize(18, 18))
            except:
                pass
            open_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                }
            """)
            open_btn.clicked.connect(self._on_open_in_blender)
            container_layout.addWidget(open_btn)

            grid.addWidget(label_widget, row, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(container, row, 1)
            row += 1

    def _add_info_row(self, grid: QGridLayout, row: int, label: str, value: str):
        """Add a key-value row to grid"""

        # Label (bold)
        label_widget = QLabel(label)
        label_font = QFont()
        label_font.setBold(True)
        label_widget.setFont(label_font)

        # Value
        value_widget = QLabel(value)
        value_widget.setWordWrap(True)

        grid.addWidget(label_widget, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(value_widget, row, 1)

    def _clear_grid(self, grid: QGridLayout):
        """Clear all widgets from grid"""

        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_section(self, section: QWidget):
        """Clear a section"""

        grid = section.property("grid")
        if grid:
            self._clear_grid(grid)

    # ==================== POSE ACTIONS ====================

    def _on_select_bones_clicked(self):
        """Handle Select Bones button click with modifiers."""
        if not self._animation:
            return

        # Get modifier keys
        from PyQt6.QtWidgets import QApplication, QMessageBox
        modifiers = QApplication.keyboardModifiers()
        mirror = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        add_to_selection = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        # Get bone names - first try animation data, then load from JSON file
        bone_names = self._animation.get('bone_names', [])
        if not bone_names:
            # Load from JSON file (bone_names is stored in JSON but not database)
            json_path = self._animation.get('json_file_path')
            if json_path:
                try:
                    import json
                    with open(json_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    bone_names = json_data.get('bone_names', [])
                except Exception as e:
                    pass

        if not bone_names:
            QMessageBox.information(self, "No Bones", "This pose has no bone data.")
            return

        # Send command to Blender via socket
        from ..services.socket_client import get_socket_client
        client = get_socket_client()

        if not client.connect():
            QMessageBox.warning(self, "Connection Error",
                "Cannot connect to Blender. Make sure Blender is running with the addon enabled.")
            return

        result = client.send_command({
            'type': 'select_bones',
            'bone_names': bone_names,
            'mirror': mirror,
            'add_to_selection': add_to_selection
        })

        if result and result.get('status') == 'error':
            QMessageBox.warning(self, "Error", result.get('message', 'Unknown error'))

    # ==================== VERSION SECTION ====================

    def _update_version_section(self):
        """Update version information section"""

        if not self._animation:
            self._version_section.hide()
            return

        # Hide in analysis mode - use standalone analyze button instead
        if self._analysis_mode:
            self._version_section.hide()
            return

        # Poses don't use versioning - hide the section entirely
        if self._animation.get('is_pose'):
            self._version_section.hide()
            return

        self._version_section.show()

        # Get version info based on preview mode
        if self._preview_mode == "lookdev":
            # Lookdev version info
            lookdev_version = self._animation.get('latest_lookdev_version')
            if lookdev_version is not None:
                version_label = f"v{lookdev_version:03d}"
            else:
                version_label = "No Lookdev"
            # Lookdev count for version display
            version_count = self._animation.get('lookdev_count', 0)
            is_latest = True  # Always show latest for lookdev
        else:
            # Playblast/shot version info
            # Shot fields: shot_version, is_latest_shot_version
            # Animation fields: version_label, is_latest
            playblast_version = self._animation.get('latest_playblast_version')
            shot_version = self._animation.get('shot_version')
            if playblast_version is not None:
                version_label = f"v{playblast_version:03d}"
            elif shot_version is not None:
                version_label = f"v{shot_version:03d}"
            else:
                version_label = self._animation.get('version_label', 'v001')
            version_count = self._animation.get('playblast_count', 0)

            # Check is_latest_shot_version first (shot domain), then is_latest (animation domain)
            is_latest = self._animation.get('is_latest_shot_version')
            if is_latest is None:
                is_latest = self._animation.get('is_latest', 1)

        version_group_id = self._animation.get('version_group_id')

        # Update version label
        self._version_label.setText(version_label)

        # Show/hide latest badge
        if is_latest:
            self._latest_badge.show()
        else:
            self._latest_badge.hide()

        # Update comment indicator (shows when animation has unresolved review comments)
        uuid = self._animation.get('uuid')
        if uuid:
            shot_data_service = self._get_shot_data_service()
            unresolved_count = shot_data_service.get_unresolved_notes_count(uuid)
            if unresolved_count > 0:
                comment_text = f"{unresolved_count} comment{'s' if unresolved_count > 1 else ''}"
                self._comment_indicator.setText(comment_text)
                self._comment_widget.show()
            else:
                self._comment_widget.hide()
        else:
            self._comment_widget.hide()

        # Update status badge
        status = self._animation.get('status', 'none')
        self._update_status_badge_style(status)

        # Update priority badge (v12)
        self._update_priority_badge_style(self._animation.get('priority', 2))

        # Update per-shot preview mode button
        shot_mode = self._animation.get('preview_mode') or self._animation.get('display_mode', 'playblast')
        self._update_mode_buttons_style(shot_mode)

        # Get version count from database
        # Use version_group_id or fall back to animation's own UUID
        group_id = version_group_id or self._animation.get('uuid')

        if group_id:
            shot_data_service = self._get_shot_data_service()
            version_count = shot_data_service.get_version_count(group_id)

            if version_count > 1:
                self._version_count_label.setText(f"({version_count} versions)")
                self._version_count_label.show()
            else:
                self._version_count_label.hide()

            # Always enable button so user can view lineage
            self._history_btn.setEnabled(True)
        else:
            self._version_count_label.hide()
            self._history_btn.setEnabled(False)

    def _update_camera_views_section(self):
        """Update the camera views section for multi-camera master shots."""
        if not self._animation:
            self._camera_views_section.hide()
            return

        # Only show for master shots with views
        shot_role = self._animation.get('shot_role', 'standalone')
        shot_name = self._animation.get('shot_name')
        view_count = self._animation.get('view_count', 0)

        if shot_role != 'master':
            self._camera_views_section.hide()
            return

        # Get views for this master
        shot_id = self._animation.get('id') or self._animation.get('uuid')
        if not shot_id:
            self._camera_views_section.hide()
            return

        # Reuse enriched views on mode toggles; only re-query when the master shot changes.
        if self._views_cache_shot_id == shot_id and self._views_cache_data is not None:
            views = self._views_cache_data
        else:
            shot_data_service = self._get_shot_data_service()
            views = shot_data_service.get_views_for_master(shot_id)

            if not views:
                self._views_cache_shot_id = None
                self._views_cache_data = None
                self._camera_views_section.hide()
                return

            # Enrich views with playblast and lookdev info
            for view in views:
                view_id = view.get('id')
                if view_id:
                    # Get latest playblast for this view
                    playblast = shot_data_service.get_latest_playblast(view_id)
                    if playblast:
                        view['has_playblast'] = True
                        view['latest_playblast_path'] = playblast.get('file_path')
                        view['latest_playblast_version'] = playblast.get('version')
                    else:
                        view['has_playblast'] = False

                    # Get latest lookdev for this view
                    lookdev = shot_data_service.get_latest_lookdev(view_id)
                    if lookdev:
                        view['has_lookdev'] = True
                        view['latest_lookdev_path'] = lookdev.get('file_path')
                        view['latest_lookdev_version'] = lookdev.get('version')
                    else:
                        view['has_lookdev'] = False

            self._views_cache_shot_id = shot_id
            self._views_cache_data = views

        # Show section
        self._camera_views_section.show()

        # Update count label
        view_count = len(views)
        self._view_count_label.setText(f"{view_count} view{'s' if view_count > 1 else ''}")

        # Clear existing view items
        while self._views_list_layout.count():
            item = self._views_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add view items
        for view in views:
            view_widget = self._create_view_item(view)
            self._views_list_layout.addWidget(view_widget)

    def _create_view_item(self, view_data: dict) -> QWidget:
        """Create a widget for a single camera view in the list."""
        from ..utils.icon_loader import IconLoader
        from ..utils.icon_utils import colorize_white_svg
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtCore import QSize

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        # View name (e.g., "ref01", "cam02")
        view_name = view_data.get('view_name') or view_data.get('shot_name', 'Unknown')
        # Extract just the suffix part if it's a full shot name
        if '_ref' in view_name or '_cam' in view_name:
            parts = view_name.rsplit('_', 1)
            if len(parts) > 1:
                view_name = parts[-1]

        name_label = QLabel(f"├─ {view_name}")
        name_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(name_label)

        # Show PB or LD status based on current preview mode
        if self._preview_mode == 'lookdev':
            has_media = view_data.get('has_lookdev', False)
            media_version = view_data.get('latest_lookdev_version')
            media_label = "LD"
        else:
            has_media = view_data.get('has_playblast', False)
            media_version = view_data.get('latest_playblast_version')
            media_label = "PB"

        if has_media and media_version is not None:
            status_label = QLabel(f"[{media_label} v{media_version:03d}]")
            status_label.setStyleSheet(f"color: #4CAF50; {get_font_stylesheet(Fonts.CAPTION)}")
        else:
            status_label = QLabel(f"[No {media_label}]")
            status_label.setStyleSheet(f"color: #888; {get_font_stylesheet(Fonts.CAPTION)}")
        layout.addWidget(status_label)

        layout.addStretch()

        # Jump to shot button (seeks to view's position in combined video)
        if has_media:
            jump_btn = QPushButton()
            jump_btn.setFixedSize(24, 24)
            jump_btn.setToolTip(f"Jump to {view_name} in combined playblast")
            jump_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            try:
                icon_path = IconLoader.get("arrow_right")
                if icon_path:
                    from PyQt6.QtGui import QIcon
                    jump_btn.setIcon(QIcon(icon_path))
                    jump_btn.setIconSize(QSize(16, 16))
            except Exception:
                pass
            jump_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                }
            """)
            jump_btn.clicked.connect(
                lambda checked, v=view_data, vn=view_name: self._on_view_jump_to(v, vn)
            )
            layout.addWidget(jump_btn)

        # Render button (add to render manager with offset)
        render_btn = QPushButton()
        render_btn.setFixedSize(24, 24)
        view_display_name = view_data.get('view_name') or view_data.get('shot_name', 'view')
        render_btn.setToolTip(f"Add {view_display_name} to Render Manager")
        render_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            icon_path = IconLoader.get("render")
            if icon_path:
                from PyQt6.QtGui import QIcon
                render_btn.setIcon(QIcon(icon_path))
                render_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        render_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: rgba(201, 123, 91, 0.3);
                border-radius: 4px;
            }
        """)
        render_btn.clicked.connect(
            lambda checked, v=view_data: self._on_view_render_clicked(v)
        )
        layout.addWidget(render_btn)

        # Open in Blender button
        open_btn = QPushButton()
        open_btn.setFixedSize(24, 24)
        open_btn.setToolTip("Open in Blender")
        open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            icon_path = IconLoader.get("blender")
            if icon_path:
                from PyQt6.QtGui import QIcon
                open_btn.setIcon(QIcon(icon_path))
                open_btn.setIconSize(QSize(18, 18))
        except Exception:
            pass
        open_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
            }
        """)
        open_btn.clicked.connect(
            lambda checked, v=view_data: self._on_view_open_file(v)
        )
        layout.addWidget(open_btn)

        return widget

    def _on_view_jump_to(self, view_data: dict, view_name: str):
        """
        Jump to view's position in combined video and pause.

        Uses the combined playblast or lookdev based on current preview mode.
        Seeks to the view's start time and pauses.
        """
        from ..core.playblast_stitcher import get_playblast_stitcher
        from pathlib import Path

        # Get the combined video path based on current preview mode
        if self._preview_mode == "lookdev":
            combined_path = self._animation.get('combined_lookdev_path') or self._animation.get('latest_lookdev_path')
        else:
            combined_path = self._animation.get('combined_playblast_path') or self._animation.get('latest_playblast_path')

        if not combined_path:
            return

        combined_path = Path(combined_path)
        if not combined_path.exists():
            return

        # Get the start time for this view from the JSON sidecar
        stitcher = get_playblast_stitcher()
        start_time_ms = stitcher.get_view_start_time(combined_path, view_name)

        if start_time_ms is not None:
            # Seek to position and pause
            self._video_preview.seek_to_ms(start_time_ms)
            self._video_preview.pause()

    def _on_open_in_blender(self):
        """Open the current shot's .blend file in Blender."""
        if not self._animation:
            return

        blend_file = self._animation.get('blend_file')
        folder_path = self._animation.get('folder_path', '')

        self._open_blend_file(blend_file, folder_path)

    def _calculate_camera_offset(self, target_view_name: str) -> tuple:
        """
        Calculate the frame offset for a camera based on preceding cameras' frame counts.

        For multi-camera shots, cameras are ordered alphabetically by view_name.
        The offset is the sum of all frame counts from cameras that come before
        the target camera in alphabetical order.

        Args:
            target_view_name: The view_name of the camera to calculate offset for

        Returns:
            Tuple of (offset, error_message). error_message is None if successful.
        """
        if not self._animation:
            return (0, None)

        # Get the master shot ID
        shot_id = self._animation.get('id') or self._animation.get('uuid')
        if not shot_id:
            return (0, None)

        # Get all views for this master shot
        shot_data_service = self._get_shot_data_service()
        views = shot_data_service.get_views_for_master(shot_id)

        if not views:
            return (0, None)

        # Sort views alphabetically by view_name (same order as displayed)
        views.sort(key=lambda v: v.get('view_name') or v.get('shot_name', ''))

        # Calculate offset by summing frame counts of preceding cameras
        offset = 0
        for view in views:
            view_name = view.get('view_name') or view.get('shot_name', '')
            if view_name == target_view_name:
                return (offset, None)

            # Get frame count from the .blend file
            blend_file = view.get('blend_file')
            folder_path = view.get('folder_path', '')

            if not blend_file:
                return (0, f"Camera '{view_name}' has no blend file - cannot calculate offset")

            if folder_path and not Path(blend_file).is_absolute():
                full_path = Path(folder_path) / Path(blend_file).name
            else:
                full_path = Path(blend_file)

            if not full_path.exists():
                return (0, f"Blend file not found for camera '{view_name}':\n{full_path}")

            # Extract frame info using BAT
            from ..services.blender_render_service import get_blender_render_service
            service = get_blender_render_service()
            info = service.extract_blend_info_fast(full_path)

            if info:
                frame_count = info.frame_end - info.frame_start + 1
                offset += frame_count
            else:
                return (0, f"Could not read frame range from '{view_name}' blend file.\n"
                          f"Render cameras in order (first camera doesn't need offset).")

        return (offset, None)

    def _on_view_render_clicked(self, view_data: dict):
        """
        Queue a camera view for rendering with auto-calculated offset.

        Uses the master shot's render directory and shot name, with
        continuous frame numbering across all cameras.
        """
        if not self._animation:
            return

        # Get view's blend file
        blend_file = view_data.get('blend_file')
        folder_path = view_data.get('folder_path', '')

        if not blend_file:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "No Blend File",
                "This camera view does not have a .blend file associated with it."
            )
            return

        # Construct full path
        if folder_path and not Path(blend_file).is_absolute():
            full_path = Path(folder_path) / Path(blend_file).name
        else:
            full_path = Path(blend_file)

        # Get the view name for offset calculation
        view_name = view_data.get('view_name') or view_data.get('shot_name', '')

        # Calculate offset based on preceding cameras
        offset, error = self._calculate_camera_offset(view_name)
        if error:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Cannot Calculate Offset",
                f"Failed to calculate frame offset:\n\n{error}"
            )
            return

        # Get master shot info for output directory and naming
        master_folder_path = self._animation.get('folder_path', '')
        master_shot_name = self._animation.get('shot_name', '')

        # Output directory is master shot's Render/current/
        master_folder = Path(master_folder_path) if master_folder_path else full_path.parent
        output_dir = master_folder / "Render" / "current"

        # Get view's shot UUID for tracking
        view_uuid = view_data.get('id') or view_data.get('uuid', '')

        # Queue the render with offset
        from ..services.blender_render_service import get_blender_render_service
        service = get_blender_render_service()

        job_id = service.queue_render(
            shot_uuid=view_uuid,
            blend_file=full_path,
            output_dir=output_dir,
            output_name=master_shot_name,  # Use master shot name for all cameras
            output_frame_offset=offset,
        )

        if job_id:
            from PyQt6.QtWidgets import QMessageBox
            # Format a helpful message
            view_display = view_name
            if '_ref' in view_display or '_cam' in view_display:
                parts = view_display.rsplit('_', 1)
                if len(parts) > 1:
                    view_display = parts[-1]

            offset_info = f" (frames offset by {offset})" if offset > 0 else ""
            QMessageBox.information(
                self, "Added to Queue",
                f"Added {view_display} to Render Manager queue{offset_info}:\n"
                f"{full_path.name}\n\n"
                f"Open Render Manager to start rendering."
            )

    def _on_view_open_file(self, view_data: dict):
        """Open the .blend file for a camera view."""
        blend_file = view_data.get('blend_file')
        folder_path = view_data.get('folder_path', '')

        self._open_blend_file(blend_file, folder_path)

    def _open_blend_file(self, blend_file: str, folder_path: str):
        """
        Open a .blend file in Blender.

        Uses the Blender path configured in Settings > Blender Integration if set,
        otherwise falls back to system default file association.

        Args:
            blend_file: Blend filename or full path
            folder_path: Folder path (used if blend_file is just filename)
        """
        import subprocess
        import sys

        if not blend_file:
            return

        # Construct full path
        if folder_path and not Path(blend_file).is_absolute():
            full_path = Path(folder_path) / Path(blend_file).name
        else:
            full_path = Path(blend_file)

        if not full_path.exists():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "File Not Found",
                f"Cannot find file:\n{full_path}"
            )
            return

        try:
            # Try to use configured Blender path from Settings > Blender Integration
            blender_path = Config.get_blender_path()
            if blender_path and Path(blender_path).exists():
                # Launch specific Blender version with the file
                subprocess.Popen([blender_path, str(full_path)])
            else:
                # Fall back to system default application
                if sys.platform == 'win32':
                    import os
                    os.startfile(str(full_path))
                elif sys.platform == 'darwin':
                    subprocess.run(['open', str(full_path)])
                else:
                    subprocess.run(['xdg-open', str(full_path)])
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Error",
                f"Failed to open file:\n{e}"
            )

    def _update_assignment_section(self):
        """Update the assignment section with task data from Pipeline Control."""
        if not self._animation:
            self._assignment_section.hide()
            return

        # Get task data from animation dict (enriched by main_window)
        assigned_to = self._animation.get('assigned_to')
        assigned_to_name = self._animation.get('assigned_to_name')
        priority = self._animation.get('task_priority')
        due_date = self._animation.get('task_due_date')
        task_status = self._animation.get('task_status')

        # If no assignment data, hide section
        if not assigned_to and not priority and not due_date:
            self._assignment_section.hide()
            return

        # Show section
        self._assignment_section.show()

        # Update assignee
        if assigned_to_name:
            self._assignee_label.setText(assigned_to_name)
            self._assignee_label.setStyleSheet("color: #3498DB; font-weight: bold;")
        else:
            self._assignee_label.setText("Not assigned")
            self._assignee_label.setStyleSheet("color: #888888;")

        # Update priority with color
        if priority:
            priority_colors = {
                'low': '#95A5A6',
                'medium': '#3498DB',
                'high': '#F39C12',
                'urgent': '#E74C3C',
            }
            color = priority_colors.get(priority, '#888888')
            self._priority_label.setText(priority.capitalize())
            self._priority_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        else:
            self._priority_label.setText("-")
            self._priority_label.setStyleSheet("color: #888888;")

        # Update due date with overdue indicator
        if due_date:
            try:
                from datetime import datetime, date
                if isinstance(due_date, str):
                    due = datetime.fromisoformat(due_date).date()
                else:
                    due = due_date.date() if hasattr(due_date, 'date') else due_date
                
                formatted = due.strftime("%b %d, %Y")
                is_overdue = due < date.today()
                
                if is_overdue:
                    self._due_date_label.setText(f"{formatted} (OVERDUE)")
                    self._due_date_label.setStyleSheet("color: #E74C3C; font-weight: bold;")
                else:
                    self._due_date_label.setText(formatted)
                    self._due_date_label.setStyleSheet("color: #CCCCCC;")
            except (ValueError, AttributeError):
                self._due_date_label.setText(str(due_date))
                self._due_date_label.setStyleSheet("color: #CCCCCC;")
        else:
            self._due_date_label.setText("-")
            self._due_date_label.setStyleSheet("color: #888888;")

        # Update task status
        if task_status:
            status_labels = {
                'pending': 'Pending',
                'in_progress': 'In Progress',
                'done': 'Done',
            }
            status_colors = {
                'pending': '#F39C12',
                'in_progress': '#3498DB',
                'done': '#4CAF50',
            }
            label = status_labels.get(task_status, task_status.capitalize())
            color = status_colors.get(task_status, '#888888')
            self._task_status_label.setText(label)
            self._task_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        else:
            self._task_status_label.setText("-")
            self._task_status_label.setStyleSheet("color: #888888;")

        # Show Mark Done button if task is assigned and not done
        if assigned_to and task_status != 'done':
            self._mark_done_btn.show()
        else:
            self._mark_done_btn.hide()

    def _on_mark_done_clicked(self):
        """Handle Mark Done button click."""
        if not self._animation:
            return

        shot_id = self._animation.get('uuid') or self._animation.get('id')
        if not shot_id:
            return

        try:
            shot_data_service = self._get_shot_data_service()
            if shot_data_service.update_task_status(shot_id, 'done'):
                # Update local data
                self._animation['task_status'] = 'done'
                self._update_assignment_section()

                # Show confirmation
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "Task Complete",
                    f"Task marked as done!"
                )
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Error",
                f"Failed to update task: {e}"
            )

    def _on_status_badge_clicked(self):
        """Show status selection menu when badge is clicked"""
        # Check if we can edit status (only in Standalone mode)
        from ..services.control_authority import get_control_authority
        
        if not get_control_authority().can_edit_status():
            # Show tooltip explaining why status can't be changed
            from PyQt6.QtWidgets import QToolTip
            QToolTip.showText(
                self._status_badge.mapToGlobal(self._status_badge.rect().center()),
                "Status is controlled by Pipeline Control",
                self._status_badge
            )
            return
        
        if not self._animation:
            return

        menu = QMenu(self)

        current_status = self._animation.get('status', 'wip')

        # Add status options
        for status_key, status_info in Config.LIFECYCLE_STATUSES.items():
            action = menu.addAction(status_info['label'])
            action.setData(status_key)

            # Check mark for current status
            if status_key == current_status:
                action.setCheckable(True)
                action.setChecked(True)

            # Connect action
            action.triggered.connect(lambda checked, s=status_key: self._on_status_selected(s))

        # Show menu below the badge
        menu.exec(self._status_badge.mapToGlobal(
            self._status_badge.rect().bottomLeft()
        ))

    def _on_status_selected(self, status: str):
        """Handle status selection from menu"""
        if not self._animation:
            return

        uuid = self._animation.get('uuid')
        if not uuid:
            return

        # Capture old status for audit trail
        old_status = self._animation.get('status', 'wip')

        # Don't do anything if status hasn't changed
        if old_status == status:
            return

        # Update via shot data service (handles DB update + signals)
        shot_data_service = self._get_shot_data_service()
        audit_service = self._audit_service if hasattr(self, '_audit_service') else None

        if shot_data_service.update_status(uuid, status, audit_service):
            # Update local animation data
            self._animation['status'] = status

            # Update badge appearance
            self._update_status_badge_style(status)

            # Add new status to filter to keep shot visible
            # This prevents the shot from disappearing if a status filter is active
            self._event_bus.filter_changed.emit({'add_status': status})

    # ==================== PRIORITY BADGE (v12) ====================

    # 1=Low (green), 2=Normal (blue), 3=Urgent (red)
    _PRIORITY_COLORS = {1: '#4CAF50', 2: '#5b8cc9', 3: '#F44336'}
    _PRIORITY_LABELS = {1: 'LOW', 2: 'NORMAL', 3: 'URGENT'}

    def _update_priority_badge_style(self, priority: int):
        """Style the priority badge with a color matching its level."""
        priority = int(priority) if priority in (1, 2, 3) else 2
        color = self._PRIORITY_COLORS[priority]
        label = self._PRIORITY_LABELS[priority]
        badge_font = get_font_stylesheet(Fonts.BUTTON)
        self._priority_badge.setText(label)
        self._priority_badge.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                padding: 4px 10px;
                border-radius: 0px;
                {badge_font}
                border: none;
            }}
            QPushButton:hover {{
                background-color: {color};
                border: 2px solid white;
            }}
        """)

    def _on_priority_badge_clicked(self):
        """Open priority selection menu below the badge."""
        if not self._animation:
            return

        menu = QMenu(self)
        current = self._animation.get('priority', 2)
        for value in (1, 2, 3):
            action = menu.addAction(self._PRIORITY_LABELS[value].title())
            action.setData(value)
            if value == current:
                action.setCheckable(True)
                action.setChecked(True)
            action.triggered.connect(lambda _checked=False, v=value: self._on_priority_selected(v))

        menu.exec(self._priority_badge.mapToGlobal(
            self._priority_badge.rect().bottomLeft()
        ))

    def _on_priority_selected(self, priority: int):
        """Apply selected priority to the current shot via the bulk service."""
        if not self._animation:
            return
        shot_uuid = self._animation.get('uuid') or self._animation.get('id')
        if not shot_uuid:
            return
        if self._animation.get('priority', 2) == priority:
            return

        shot_data_service = self._get_shot_data_service()
        audit_service = self._audit_service if hasattr(self, '_audit_service') else None
        if shot_data_service.bulk_set_priority([shot_uuid], priority, audit_service=audit_service):
            self._animation['priority'] = priority
            self._update_priority_badge_style(priority)

    def _on_pb_mode_clicked(self):
        """Handle PB button click in metadata panel"""
        self._set_shot_preview_mode('playblast')

    def _on_ld_mode_clicked(self):
        """Handle LD button click in metadata panel"""
        self._set_shot_preview_mode('lookdev')

    def _on_rd_mode_clicked(self):
        """Handle RD button click in metadata panel"""
        self._set_shot_preview_mode('render')

    def _on_add_to_render_manager(self):
        """Add current shot to Render Manager queue."""
        if not self._animation:
            return

        blend_file = self._animation.get('blend_file')
        folder_path = self._animation.get('folder_path', '')

        if not blend_file:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "No Blend File",
                "This shot does not have a .blend file associated with it."
            )
            return

        # Construct full path
        if folder_path and not Path(blend_file).is_absolute():
            full_path = Path(folder_path) / Path(blend_file).name
        else:
            full_path = Path(blend_file)

        # Get render service and add to queue
        from ..services.blender_render_service import get_blender_render_service
        service = get_blender_render_service()

        # Determine output directory
        shot_folder = full_path.parent
        output_dir = shot_folder / "Render" / "current"

        # Get shot UUID for tracking
        shot_uuid = self._animation.get('uuid', '')

        # Queue the render
        job_id = service.queue_render(
            shot_uuid=shot_uuid,
            blend_file=full_path,
            output_dir=output_dir
        )

        if job_id:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Added to Queue",
                f"Added to Render Manager queue:\n{full_path.name}\n\nOpen Render Manager to start rendering."
            )

    def _set_shot_preview_mode(self, new_mode: str):
        """Set preview mode for the current shot"""
        if not self._animation:
            return

        # Get shot ID
        shot_id = self._animation.get('id') or self._animation.get('uuid')
        if not shot_id:
            return

        # Update via shot data service (handles DB update + signals)
        shot_data_service = self._get_shot_data_service()
        if shot_data_service.update_display_mode(shot_id, new_mode):
            # Update local animation data
            self._animation['preview_mode'] = new_mode
            self._animation['display_mode'] = new_mode

            # Update button appearance
            self._update_mode_buttons_style(new_mode)

            # Update video preview to show correct mode
            self._preview_mode = new_mode
            self._update_video_preview()

            # Update technical section header
            if new_mode == "render":
                self._technical_section_title.setText("Render Info")
            elif new_mode == "lookdev":
                self._technical_section_title.setText("Lookdev Info")
            else:
                self._technical_section_title.setText("Playblast Info")

            # Refresh camera views section to show PB/LD versions
            self._update_camera_views_section()

    def _on_view_history_clicked(self):
        """Open version history dialog"""
        if not self._animation:
            return

        # Use version_group_id if available, otherwise fall back to animation's own UUID
        version_group_id = self._animation.get('version_group_id') or self._animation.get('uuid')

        if not version_group_id:
            return

        # Get shot folder and blend stem for lookdev support
        shot_folder = None
        blend_stem = None
        folder_path = self._animation.get('folder_path') or self._animation.get('shot_folder')
        if folder_path:
            shot_folder = Path(folder_path) if isinstance(folder_path, str) else folder_path
        blend_stem = self._animation.get('blend_stem') or self._animation.get('name')

        # Analysis Mode: Get sibling videos for the dialog
        folder_videos = None
        if self._analysis_mode:
            video_path = self._animation.get('preview_path') or self._animation.get('latest_playblast_path')
            if video_path:
                from ..core.reference_indexer import get_reference_indexer
                indexer = get_reference_indexer()
                siblings = indexer.get_sibling_videos(Path(video_path))
                folder_videos = [str(v.file_path) for v in siblings]
                shot_folder = Path(video_path).parent

        # Get shot name for audit logging
        shot_name = self._animation.get('shot_name') or self._animation.get('name', 'Unknown')

        # Open version history dialog
        dialog = VersionHistoryDialog(
            version_group_id,
            parent=self,
            theme_manager=self._theme_manager,
            shot_folder=shot_folder,
            blend_stem=blend_stem,
            analysis_mode=self._analysis_mode,
            folder_videos=folder_videos,
            audit_service=self._audit_service if hasattr(self, '_audit_service') else None,
            shot_name=shot_name
        )

        # Connect signals
        dialog.version_selected.connect(self._on_version_selected)
        dialog.version_set_as_latest.connect(self._on_version_set_as_latest)

        dialog.exec()

        # After dialog closes, refresh notes (comments may have been resolved/deleted)
        self._update_version_section()  # Update metadata panel indicator
        self.notes_changed.emit()  # Notify parent to refresh card badges

    def _on_version_selected(self, uuid: str):
        """Handle version selection from history dialog"""
        # Emit signal for parent to handle (e.g., load that version)
        self.version_changed.emit(uuid)

    def _on_version_set_as_latest(self, uuid: str):
        """Handle version set as latest from history dialog"""
        # Refresh the version section if it's the current animation
        if self._animation and self._animation.get('uuid') == uuid:
            # Refresh animation data from database via shot data service
            shot_data_service = self._get_shot_data_service()
            updated = shot_data_service.get_shot(uuid)
            if updated:
                self._animation = updated
                self._update_version_section()

        # Emit signal for parent to handle
        self.version_changed.emit(uuid)

    def set_analysis_mode(self, enabled: bool):
        """
        Set analysis mode (changes UI layout for reference video analysis).

        Args:
            enabled: True for Analysis Mode, False for Shot Mode
        """
        self._analysis_mode = enabled

        # Update button text
        if enabled:
            self._history_btn.setText("Analyze")
            self._history_btn.setToolTip("Open reference video for annotation and analysis")
        else:
            self._history_btn.setText("View Lineage")
            self._history_btn.setToolTip("View playblast version history and compare versions")

        # Update section visibility
        self._update_section_visibility()

        # Refresh display if animation is set
        if self._animation:
            self._update_technical_section()

    def _update_section_visibility(self):
        """Update section visibility based on analysis mode"""
        is_analysis = self._analysis_mode

        # Shot mode sections - hidden in analysis mode
        self._shot_identity_section.setVisible(not is_analysis)
        self._shot_info_section.setVisible(not is_analysis)
        self._file_section.setVisible(not is_analysis)

        # Version section (Lineage with version/status info) - hidden in analysis mode
        # Standalone analyze button shown instead
        self._version_section.setVisible(not is_analysis)
        self._analyze_btn.setVisible(is_analysis)

        # Per-shot preview mode buttons - only visible in shot mode (within version section)
        self._pb_mode_btn.setVisible(not is_analysis)
        self._ld_mode_btn.setVisible(not is_analysis)
        self._rd_mode_btn.setVisible(not is_analysis)

        # Update technical section header for analysis mode
        if is_analysis:
            self._technical_section_title.setText("Video Info")
        else:
            # Restore based on preview mode
            if self._preview_mode == "render":
                self._technical_section_title.setText("Render Info")
            elif self._preview_mode == "lookdev":
                self._technical_section_title.setText("Lookdev Info")
            else:
                self._technical_section_title.setText("Playblast Info")


__all__ = ['MetadataPanel']
