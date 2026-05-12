"""
HeaderToolbar - Main toolbar for Shot Library

Shot Library specific:
- Search to filter shots (maintains editorial order)
- View mode toggle (grid/list)
- Card size slider
- Scan/Refresh button for shot discovery
- NO sorting (editorial order is mandatory)
- NO rig types or tags (animation library concepts)
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton,
    QSlider, QLabel, QComboBox, QFileDialog, QToolButton, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QIcon
from pathlib import Path

from ..config import Config
from ..events.event_bus import get_event_bus
from ..services.database_service import get_database_service
from ..utils import IconLoader, colorize_white_svg
from ..themes.theme_manager import get_theme_manager
from ..themes.fonts import Fonts, get_font_stylesheet


class HeaderToolbar(QWidget):
    """
    Header toolbar for Shot Library

    Features:
    - Search box (filters shots, maintains editorial order)
    - View mode toggle (grid/list)
    - Card size slider
    - Scan folder button
    - Settings access

    Shot Library Rules:
    - NO sorting controls (editorial order is mandatory)
    - NO rig type filters (animation library concept)
    - NO tag filters (animation library concept)
    """

    # Signals
    search_text_changed = pyqtSignal(str)
    view_mode_changed = pyqtSignal(str)  # "grid" or "list"
    card_size_changed = pyqtSignal(int)
    scan_folder_clicked = pyqtSignal(str)  # folder path to scan
    refresh_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    preview_mode_changed = pyqtSignal(str)  # "playblast", "lookdev", or "render"
    app_mode_changed = pyqtSignal(str)  # "shot" or "analysis"
    sequence_review_clicked = pyqtSignal()  # Sequence Review Mode
    clip_extractor_clicked = pyqtSignal()  # Clip Extractor (Analysis Mode)
    folder_filter_toggled = pyqtSignal(bool)  # True = folder filter active
    render_manager_clicked = pyqtSignal()  # Render Manager

    refresh_library_clicked = pyqtSignal()

    def __init__(self, parent=None, db_service=None, event_bus=None, theme_manager=None):
        super().__init__(parent)

        # Set header property for theme-based styling
        self.setProperty("header", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(50)

        # Services
        self._event_bus = event_bus or get_event_bus()
        self._db_service = db_service or get_database_service()
        self._theme_manager = theme_manager or get_theme_manager()

        # State
        self._view_mode = Config.DEFAULT_VIEW_MODE
        self._card_size = Config.DEFAULT_CARD_SIZE
        self._current_folder: str = ""
        self._app_mode: str = "shot"  # "shot" or "analysis"

        # Setup UI
        self._create_widgets()
        self._create_layout()
        self._connect_signals()

        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)

    def _create_widgets(self):
        """Create toolbar widgets"""
        theme = self._theme_manager.get_current_theme()
        icon_color = theme.palette.header_icon_color if theme else "#1a1a1a"

        # App mode dropdown (Shot Mode / Analysis Mode)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Shot Mode", "shot")
        self._mode_combo.addItem("Analysis Mode", "analysis")
        self._mode_combo.setFixedWidth(130)
        self._mode_combo.setToolTip("Switch between Shot Management and Reference Analysis modes")

        # Folder dropdown button (replaces browse button)
        self._folder_dropdown = QToolButton()
        self._folder_dropdown.setText("Browse Folder...")
        self._folder_dropdown.setToolTip("Select a production folder to browse shots")
        self._folder_dropdown.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._folder_dropdown.setMinimumWidth(200)
        self._folder_dropdown.setFixedHeight(32)

        # Dropdown menu for recent folders
        self._folder_menu = QMenu(self)
        self._folder_dropdown.setMenu(self._folder_menu)

        # Populate menu with recent folders
        self._refresh_folder_menu()

        # Search box
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter shots...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setFixedWidth(200)
        self._search_box.setToolTip("Filter shots by name (editorial order maintained)")

        # Rescan button
        self._rescan_btn = QPushButton()
        rescan_icon_path = IconLoader.get("refresh")
        rescan_icon = colorize_white_svg(rescan_icon_path, icon_color)
        self._rescan_btn.setIcon(rescan_icon)
        self._rescan_btn.setIconSize(QSize(24, 24))
        self._rescan_btn.setFixedSize(40, 40)
        self._rescan_btn.setToolTip("Rescan folder for shots (F5)")

        # View mode toggle
        self._view_mode_btn = QPushButton()
        view_mode_icon_path = IconLoader.get("view_mode")
        view_mode_icon = colorize_white_svg(view_mode_icon_path, icon_color)
        self._view_mode_btn.setIcon(view_mode_icon)
        self._view_mode_btn.setIconSize(QSize(20, 20))
        self._view_mode_btn.setFixedSize(32, 32)
        self._view_mode_btn.setCheckable(True)
        self._view_mode_btn.setChecked(self._view_mode == "grid")
        self._view_mode_btn.setToolTip("Toggle Grid/List View")

        # Card size slider with icon
        self._grid_icon_label = QLabel()
        grid_icon_path = IconLoader.get("resize_grid")
        grid_icon = colorize_white_svg(grid_icon_path, icon_color)
        self._grid_icon_label.setPixmap(grid_icon.pixmap(20, 20))
        self._grid_icon_label.setToolTip("Card Size")

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setProperty("cardsize", "true")
        self._size_slider.setMinimum(Config.MIN_CARD_SIZE)
        self._size_slider.setMaximum(Config.MAX_CARD_SIZE)
        self._size_slider.setValue(self._card_size)
        self._size_slider.setSingleStep(Config.CARD_SIZE_STEP)
        self._size_slider.setPageStep(Config.CARD_SIZE_STEP * 2)
        self._size_slider.setFixedWidth(120)
        self._size_slider.setToolTip(f"Card size ({Config.MIN_CARD_SIZE}-{Config.MAX_CARD_SIZE}px)")

        # Preview mode toggle buttons (PB/LD/RD) - Blender-style shading icons
        self._preview_mode = "playblast"

        mode_btn_style = """
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:checked {
                background-color: #5b8cc9;
                border-radius: 3px;
            }
        """
        mode_btn_style_rd = """
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:checked {
                background-color: #c97b5b;
                border-radius: 3px;
            }
        """

        self._pb_btn = QPushButton()
        self._pb_btn.setFixedSize(32, 28)
        self._pb_btn.setCheckable(True)
        self._pb_btn.setChecked(True)  # Default to playblast
        self._pb_btn.setToolTip("Set ALL visible shots to Playblast mode")
        try:
            pb_icon = QIcon(IconLoader.get("shading_solid"))
            self._pb_btn.setIcon(pb_icon)
            self._pb_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._pb_btn.setText("PB")
        self._pb_btn.setStyleSheet(mode_btn_style)

        self._ld_btn = QPushButton()
        self._ld_btn.setFixedSize(32, 28)
        self._ld_btn.setCheckable(True)
        self._ld_btn.setChecked(False)
        self._ld_btn.setToolTip("Set ALL visible shots to Lookdev mode")
        try:
            ld_icon = QIcon(IconLoader.get("shading_texture"))
            self._ld_btn.setIcon(ld_icon)
            self._ld_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._ld_btn.setText("LD")
        self._ld_btn.setStyleSheet(mode_btn_style)

        self._rd_btn = QPushButton()
        self._rd_btn.setFixedSize(32, 28)
        self._rd_btn.setCheckable(True)
        self._rd_btn.setChecked(False)
        self._rd_btn.setToolTip("Set ALL visible shots to Render mode")
        try:
            rd_icon = QIcon(IconLoader.get("shading_rendered"))
            self._rd_btn.setIcon(rd_icon)
            self._rd_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._rd_btn.setText("RD")
        self._rd_btn.setStyleSheet(mode_btn_style_rd)

        # Sequence Review button
        self._review_btn = QPushButton()
        review_icon_path = IconLoader.get("play")
        review_icon = colorize_white_svg(review_icon_path, icon_color)
        self._review_btn.setIcon(review_icon)
        self._review_btn.setIconSize(QSize(18, 18))
        self._review_btn.setFixedSize(36, 28)
        self._review_btn.setToolTip("Sequence Review Mode - Play all shots in succession")

        # Render Manager button - opens the queue dialog
        self._rm_btn = QPushButton()
        self._rm_btn.setFixedSize(36, 28)
        self._rm_btn.setToolTip("Render Manager - Queue and manage Blender renders")
        try:
            rm_icon = QIcon(IconLoader.get("render"))
            self._rm_btn.setIcon(rm_icon)
            self._rm_btn.setIconSize(QSize(20, 20))
        except Exception:
            self._rm_btn.setText("RM")
        self._rm_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)

        # Clip Extractor button (Analysis Mode only)
        self._clip_extractor_btn = QPushButton()
        clip_icon = colorize_white_svg(IconLoader.get("edit"), icon_color)
        self._clip_extractor_btn.setIcon(clip_icon)
        self._clip_extractor_btn.setIconSize(QSize(18, 18))
        self._clip_extractor_btn.setFixedSize(36, 28)
        self._clip_extractor_btn.setToolTip(
            "Clip Extractor \u2014 Select a video, then click to trim and export clips"
        )
        self._clip_extractor_btn.setVisible(False)  # Hidden by default (Shot Mode)

        # Status filter (must match Pipeline Control statuses)
        self._status_combo = QComboBox()
        self._status_combo.addItem("All Statuses")
        self._status_combo.addItem("WIP")
        self._status_combo.addItem("In Review")
        self._status_combo.addItem("Needs Work")
        self._status_combo.addItem("Approved")
        self._status_combo.addItem("Final")
        self._status_combo.addItem("Blocked")
        self._status_combo.setFixedWidth(120)
        self._status_combo.setToolTip("Filter by shot status")

        # Folder filter toggle button
        self._folder_filter_btn = QPushButton("F")
        self._folder_filter_btn.setFixedSize(36, 28)
        self._folder_filter_btn.setCheckable(True)
        self._folder_filter_btn.setChecked(False)
        self._folder_filter_btn.setToolTip("Filter shots by folder — click a folder in the tree to filter")
        self._folder_filter_btn.setStyleSheet(f"""
            QPushButton {{ {get_font_stylesheet(Fonts.BUTTON)} }}
            QPushButton:checked {{ background-color: #5b8cc9; color: white; }}
        """)

        # Pipeline Mode indicator (hidden by default, shown in Pipeline Mode)
        self._pipeline_indicator = QLabel("Pipeline")
        self._pipeline_indicator.setStyleSheet(f"""
            QLabel {{
                color: #3498DB;
                {get_font_stylesheet(Fonts.CAPTION)}
                padding: 3px 8px;
                background: rgba(52, 152, 219, 0.15);
                border: 1px solid rgba(52, 152, 219, 0.3);
            }}
        """)
        self._pipeline_indicator.setToolTip("Status controlled by Pipeline Control")
        self._pipeline_indicator.setVisible(False)

        # About button
        self._about_btn = QPushButton()
        about_icon_path = IconLoader.get("sl_icon")
        about_icon = colorize_white_svg(about_icon_path, icon_color)
        self._about_btn.setIcon(about_icon)
        self._about_btn.setIconSize(QSize(24, 24))
        self._about_btn.setFixedSize(40, 40)
        self._about_btn.setToolTip("About Shot Library")

        # Console button
        self._console_btn = QPushButton()
        console_icon_path = IconLoader.get("console")
        console_icon = colorize_white_svg(console_icon_path, icon_color)
        self._console_btn.setIcon(console_icon)
        self._console_btn.setIconSize(QSize(24, 24))
        self._console_btn.setFixedSize(40, 40)
        self._console_btn.setToolTip("Console & Logs")

        # Settings button
        self._settings_btn = QPushButton()
        settings_icon_path = IconLoader.get("settings")
        settings_icon = colorize_white_svg(settings_icon_path, icon_color)
        self._settings_btn.setIcon(settings_icon)
        self._settings_btn.setIconSize(QSize(24, 24))
        self._settings_btn.setFixedSize(40, 40)
        self._settings_btn.setToolTip("Settings")

    def _create_layout(self):
        """Create toolbar layout"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(8)

        # Left: Mode selector
        layout.addWidget(self._mode_combo)
        layout.addSpacing(8)

        # Folder browsing dropdown
        layout.addWidget(self._folder_dropdown)
        layout.addSpacing(16)

        # Middle: Search and filters
        layout.addWidget(self._search_box)
        layout.addWidget(self._status_combo)
        layout.addWidget(self._folder_filter_btn)
        layout.addWidget(self._pipeline_indicator)
        layout.addSpacing(8)

        layout.addWidget(self._rescan_btn)
        layout.addSpacing(16)

        # View controls
        layout.addWidget(self._view_mode_btn)
        layout.addSpacing(4)
        layout.addWidget(self._grid_icon_label)
        layout.addWidget(self._size_slider)
        layout.addSpacing(8)

        # Preview mode toggle (PB/LD/RD)
        layout.addWidget(self._pb_btn)
        layout.addWidget(self._ld_btn)
        layout.addWidget(self._rd_btn)
        layout.addSpacing(8)

        # Sequence Review button
        layout.addWidget(self._review_btn)

        # Render Manager button
        layout.addWidget(self._rm_btn)

        # Clip Extractor button (Analysis Mode)
        layout.addWidget(self._clip_extractor_btn)

        # Stretch
        layout.addStretch()

        # Right: System buttons
        layout.addWidget(self._about_btn)
        layout.addSpacing(4)
        layout.addWidget(self._console_btn)
        layout.addSpacing(4)
        layout.addWidget(self._settings_btn)

    def _connect_signals(self):
        """Connect signals"""
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._folder_dropdown.clicked.connect(self._on_browse_clicked)
        self._search_box.textChanged.connect(self._on_search_changed)
        self._rescan_btn.clicked.connect(self._on_rescan_clicked)
        self._view_mode_btn.clicked.connect(self._on_view_mode_clicked)
        self._size_slider.valueChanged.connect(self._on_card_size_changed)
        self._status_combo.currentIndexChanged.connect(self._on_status_filter_changed)
        self._folder_filter_btn.clicked.connect(self._on_folder_filter_toggled)
        self._pb_btn.clicked.connect(self._on_pb_clicked)
        self._ld_btn.clicked.connect(self._on_ld_clicked)
        self._review_btn.clicked.connect(self.sequence_review_clicked.emit)
        self._rd_btn.clicked.connect(self._on_rd_clicked)
        self._rm_btn.clicked.connect(self.render_manager_clicked.emit)
        self._clip_extractor_btn.clicked.connect(self.clip_extractor_clicked.emit)
        self._settings_btn.clicked.connect(self.settings_clicked.emit)
        self._about_btn.clicked.connect(self._on_about_clicked)
        self._console_btn.clicked.connect(self._on_console_clicked)

        # Theme changes
        self._theme_manager.theme_changed.connect(self._on_theme_changed)

    def _refresh_folder_menu(self):
        """Refresh the folder dropdown menu with recent folders."""
        self._folder_menu.clear()

        data = Config.load_recent_folders()
        recent = data.get('recent', [])

        # Add recent folders with submenus for remove option
        for folder_path in recent:
            folder_name = Path(folder_path).name

            # Create submenu for this folder
            submenu = QMenu(folder_name, self._folder_menu)
            submenu.setToolTip(folder_path)

            # Open action
            open_action = submenu.addAction("Open")
            open_action.triggered.connect(lambda checked, p=folder_path: self._select_folder(p))

            submenu.addSeparator()

            # Remove action
            remove_action = submenu.addAction("Remove from History")
            remove_action.triggered.connect(lambda checked, p=folder_path: self._remove_folder(p))

            self._folder_menu.addMenu(submenu)

        # Add separator and browse option
        if recent:
            self._folder_menu.addSeparator()
        self._folder_menu.addAction("Browse...").triggered.connect(self._on_browse_clicked)

    def _remove_folder(self, folder_path: str):
        """Remove a folder from the recent history."""
        Config.remove_recent_folder(folder_path)
        self._refresh_folder_menu()

    def _select_folder(self, folder_path: str):
        """Select a folder from the dropdown menu or browse dialog."""
        if Path(folder_path).exists():
            self._current_folder = folder_path
            folder_name = Path(folder_path).name
            self._folder_dropdown.setText(folder_name)
            self._folder_dropdown.setToolTip(folder_path)
            Config.add_recent_folder(folder_path)
            self.scan_folder_clicked.emit(folder_path)
            self._refresh_folder_menu()

    def _on_mode_changed(self, index: int):
        """Handle app mode change."""
        mode = self._mode_combo.currentData()
        if mode and mode != self._app_mode:
            self._app_mode = mode
            self._update_ui_for_mode(mode)
            self.app_mode_changed.emit(mode)

    def _update_ui_for_mode(self, mode: str):
        """Update UI elements based on current mode."""
        if mode == "analysis":
            # Analysis mode: simpler UI
            self._folder_dropdown.setToolTip("Select a folder with reference videos")
            self._search_box.setPlaceholderText("Filter videos...")
            # Hide shot-specific controls
            self._status_combo.setVisible(False)
            self._folder_filter_btn.setVisible(False)
            self._pb_btn.setVisible(False)
            self._ld_btn.setVisible(False)
            self._rd_btn.setVisible(False)
            self._review_btn.setVisible(False)
            self._rm_btn.setVisible(False)
            # Show analysis-specific controls
            self._clip_extractor_btn.setVisible(True)
        else:
            # Shot mode: full UI
            self._folder_dropdown.setToolTip("Select a production folder to browse shots")
            self._search_box.setPlaceholderText("Filter shots...")
            # Show shot-specific controls
            self._status_combo.setVisible(True)
            self._folder_filter_btn.setVisible(True)
            self._pb_btn.setVisible(True)
            self._ld_btn.setVisible(True)
            self._rd_btn.setVisible(True)
            self._review_btn.setVisible(True)
            self._rm_btn.setVisible(True)
            # Hide analysis-specific controls
            self._clip_extractor_btn.setVisible(False)

    def _on_browse_clicked(self):
        """Handle browse folder button click."""
        # Start from last active folder if available
        start = str(Config.get_last_active_folder() or Path.home())
        title = "Select Reference Folder" if self._app_mode == "analysis" else "Select Production Folder"
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            start,
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self._select_folder(folder)

    def _on_search_changed(self, text: str):
        """Handle search text change"""
        self.search_text_changed.emit(text)

    def _on_rescan_clicked(self):
        """Handle rescan button"""
        if self._current_folder:
            self.scan_folder_clicked.emit(self._current_folder)
        self.refresh_clicked.emit()
        self.refresh_library_clicked.emit()  # Compatibility

    def _on_view_mode_clicked(self):
        """Handle view mode toggle"""
        if self._view_mode == "grid":
            self._view_mode = "list"
            self._size_slider.setEnabled(False)
        else:
            self._view_mode = "grid"
            self._size_slider.setEnabled(True)

        self._view_mode_btn.setChecked(self._view_mode == "grid")
        self.view_mode_changed.emit(self._view_mode)

    def _on_card_size_changed(self, size: int):
        """Handle card size change"""
        self._card_size = size
        self.card_size_changed.emit(size)

    def _on_status_filter_changed(self, index: int):
        """Handle status filter change"""
        # Emit event for filtering - shots stay in editorial order
        status = self._status_combo.currentText() if index > 0 else None
        self._event_bus.filter_changed.emit({"status": status})

    def _on_pb_clicked(self):
        """Handle Playblast button click"""
        self._preview_mode = "playblast"
        self._pb_btn.setChecked(True)
        self._ld_btn.setChecked(False)
        self._rd_btn.setChecked(False)
        self.preview_mode_changed.emit("playblast")

    def _on_ld_clicked(self):
        """Handle Lookdev button click"""
        self._preview_mode = "lookdev"
        self._pb_btn.setChecked(False)
        self._ld_btn.setChecked(True)
        self._rd_btn.setChecked(False)
        self.preview_mode_changed.emit("lookdev")

    def _on_rd_clicked(self):
        """Handle Render button click - switch preview mode to render."""
        self._preview_mode = "render"
        self._pb_btn.setChecked(False)
        self._ld_btn.setChecked(False)
        self._rd_btn.setChecked(True)
        self.preview_mode_changed.emit("render")

    def _on_folder_filter_toggled(self, checked: bool):
        """Handle folder filter toggle."""
        self.folder_filter_toggled.emit(checked)

    def is_folder_filter_active(self) -> bool:
        """Check if folder filter toggle is active."""
        return self._folder_filter_btn.isChecked()

    def _on_about_clicked(self):
        """Show about dialog"""
        from .dialogs.about_dialog import AboutDialog
        dialog = AboutDialog(self, self._theme_manager)
        dialog.exec()

    def _on_console_clicked(self):
        """Show console dialog"""
        from .dialogs.log_console_dialog import LogConsoleDialog
        dialog = LogConsoleDialog(self, self._theme_manager)
        dialog.exec()

    def _on_theme_changed(self, theme_name: str):
        """Reload icons on theme change"""
        theme = self._theme_manager.get_current_theme()
        if not theme:
            return

        icon_color = theme.palette.header_icon_color

        rescan_icon = colorize_white_svg(IconLoader.get("refresh"), icon_color)
        self._rescan_btn.setIcon(rescan_icon)

        view_mode_icon = colorize_white_svg(IconLoader.get("view_mode"), icon_color)
        self._view_mode_btn.setIcon(view_mode_icon)

        grid_icon = colorize_white_svg(IconLoader.get("resize_grid"), icon_color)
        self._grid_icon_label.setPixmap(grid_icon.pixmap(20, 20))

        about_icon = colorize_white_svg(IconLoader.get("sl_icon"), icon_color)
        self._about_btn.setIcon(about_icon)

        console_icon = colorize_white_svg(IconLoader.get("console"), icon_color)
        self._console_btn.setIcon(console_icon)

        settings_icon = colorize_white_svg(IconLoader.get("settings"), icon_color)
        self._settings_btn.setIcon(settings_icon)

        review_icon = colorize_white_svg(IconLoader.get("play"), icon_color)
        self._review_btn.setIcon(review_icon)

        clip_icon = colorize_white_svg(IconLoader.get("edit"), icon_color)
        self._clip_extractor_btn.setIcon(clip_icon)

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def get_current_folder(self) -> str:
        """Get currently selected folder path"""
        return self._current_folder

    def set_folder(self, folder_path: str):
        """Set the current folder programmatically"""
        self._current_folder = folder_path
        if folder_path:
            folder_name = Path(folder_path).name
            self._folder_dropdown.setText(folder_name)
            self._folder_dropdown.setToolTip(folder_path)
        else:
            self._folder_dropdown.setText("Browse Folder...")
            self._folder_dropdown.setToolTip("Select a production folder to browse shots")

    # App mode methods
    def get_app_mode(self) -> str:
        """Get current app mode ('shot' or 'analysis')."""
        return self._app_mode

    def set_app_mode(self, mode: str):
        """Set app mode programmatically."""
        if mode in ("shot", "analysis"):
            index = 0 if mode == "shot" else 1
            self._mode_combo.setCurrentIndex(index)

    # Operation Mode (Pipeline Control integration)
    def update_operation_mode_indicator(self):
        """Update the Pipeline Mode indicator visibility based on current mode."""
        from ..services.control_authority import get_control_authority
        
        control_authority = get_control_authority()
        is_pipeline = control_authority.is_pipeline_mode()
        self._pipeline_indicator.setVisible(is_pipeline)

    def refresh_operation_mode(self):
        """Refresh the operation mode indicator (call after settings change)."""
        self.update_operation_mode_indicator()

    # Compatibility stubs
    def _refresh_filter_data(self):
        """Stub for compatibility"""
        pass

    def refresh_filters(self):
        """Stub for compatibility"""
        pass


__all__ = ['HeaderToolbar']
