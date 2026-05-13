"""
MainWindow - Main application window for Shot Library

Pattern: QMainWindow with splitter layout
Adapted for Shot Library: Supports shot discovery and browsing in editorial order

Shot Library specific features:
- Shot scanning when production folders are selected
- 16:9 video-native shot cards
- Editorial order display (no sorting, filtering only)
"""

import sys
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QDialog, QMessageBox, QMenu
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QCloseEvent, QShortcut, QKeySequence
import json

from ..config import Config
from ..events.event_bus import get_event_bus
from ..services.database_service import get_database_service
from ..services.blender_service import get_blender_service
from ..services.thumbnail_loader import get_thumbnail_loader
from ..services.update_service import UpdateService
from ..services.utils.path_utils import normalize_path
from ..themes.theme_manager import get_theme_manager
import threading
# Shot Library specific imports
from ..core.shot_indexer import ShotIndexer, DiscoveredShot
from ..core.folder_schema_parser import FolderSchemaParser
from ..core.folder_observer import FolderObserver, ChangeType, FileSystemChange
from ..core.playblast_indexer import PlayblastIndexer
from ..core.lookdev_indexer import LookdevIndexer
# Analysis Mode imports
from ..core.reference_indexer import ReferenceIndexer, DiscoveredVideo
# Shot Library models for shot grid display
from ..models.shot_list_model import ShotListModel, ShotRole
from ..models.shot_filter_proxy_model import ShotFilterProxyModel
from ..views.shot_view import ShotView
from .header_toolbar import HeaderToolbar
from .folder_tree import FolderTree
from .metadata_panel import MetadataPanel
from .apply_panel import ApplyPanel
from .bulk_edit_toolbar import BulkEditToolbar
from .settings.settings_dialog import SettingsDialog
from .sequence_review_dialog import SequenceReviewDialog
from .clip_extractor import ClipExtractorDialog
from .render_manager import RenderManagerDialog
from .controllers import BulkEditController, FilterController
# Shot Library review imports (US3: T119-T122)
from ..services.review_service import ReviewService
from ..services.user_service import UserService
# Audit trail service
from ..services.audit_service import AuditService, AuditEntityType, AuditAction
# REST API server (embedded mode) - optional, requires fastapi
from ..api import EmbeddedAPIServer, API_AVAILABLE
# New refactored services
from ..services.discovery_service import DiscoveryService, get_discovery_service
from ..services.sync_service import SyncService, get_sync_service
from ..services.shot_data_service import get_shot_data_service
# New controllers (God Class elimination)
from ..controllers import ShotScanController, SelectionController, PreviewModeController
# Centralized constants
from ..constants import StatusConstants, DisplayModeConstants, ShotRoleConstants


class MainWindow(QMainWindow):
    """
    Main application window

    Features:
    - 3-panel layout (folder tree, animation grid, metadata panel)
    - Splitter with persistent state
    - Header toolbar with search and controls
    - Bulk edit toolbar (shown in edit mode)
    - Status bar
    - Window state persistence
    - Event bus integration

    Layout:
        +------------------------------------------+
        |  HeaderToolbar                           |
        +------------------------------------------+
        |  BulkEditToolbar (edit mode only)        |
        +------------------------------------------+
        | FolderTree | AnimationView | Metadata   |
        |            |               | Panel       |
        |            |               |             |
        +------------------------------------------+
        |  StatusBar                               |
        +------------------------------------------+
    """

    def __init__(self, parent=None, db_service=None, blender_service=None,
                 event_bus=None, thumbnail_loader=None, theme_manager=None):
        super().__init__(parent)

        # Track if we've restored the last folder
        self._restored_last_folder = False

        # Services and event bus (injectable for testing)
        self._event_bus = event_bus or get_event_bus()
        self._db_service = db_service or get_database_service()
        self._blender_service = blender_service or get_blender_service()
        self._thumbnail_loader = thumbnail_loader or get_thumbnail_loader()
        self._theme_manager = theme_manager or get_theme_manager()
        
        # Initialize control authority with database service
        from ..services.control_authority import get_control_authority
        self._control_authority = get_control_authority()
        self._control_authority.set_db_service(self._db_service)

        # Shot Library: Shot-specific models for shot grid display
        self._shot_model = ShotListModel(db_service=self._db_service)
        self._shot_proxy_model = ShotFilterProxyModel()
        self._shot_proxy_model.setSourceModel(self._shot_model)

        # App mode state: "shot" or "analysis"
        self._app_mode: str = "shot"

        # Shot Library: Initialize shot indexer with default schema
        self._init_shot_indexer()

        # Analysis Mode: Initialize reference indexer
        self._init_reference_indexer()

        # Shot Library: Initialize folder observer for automatic re-indexing (T152)
        self._init_folder_observer()

        # Shot Library: Initialize review services (US3: T119-T122)
        self._init_review_services()

        # Initialize new controllers (God Class elimination)
        self._init_new_controllers()

        # Setup window
        self._setup_window()
        self._create_widgets()
        self._create_layout()
        self._init_controllers()
        self._connect_signals()
        self._inject_services()  # Inject services into widgets
        self._load_settings()
        self._load_animations()
        self._setup_queue_watcher()

    def _setup_window(self):
        """Configure window properties"""

        self.setWindowTitle(f"{Config.APP_NAME} {Config.APP_VERSION}")
        self.setGeometry(100, 100, Config.DEFAULT_WINDOW_WIDTH, Config.DEFAULT_WINDOW_HEIGHT)

        # Set window icon (for title bar and taskbar)
        self._set_window_icon()

    def _create_widgets(self):
        """Create UI widgets"""

        # Header toolbar
        self._header_toolbar = HeaderToolbar()

        # Bulk edit toolbar (hidden by default)
        self._bulk_edit_toolbar = BulkEditToolbar()
        self._bulk_edit_toolbar.hide()

        # Folder tree (left panel)
        self._folder_tree = FolderTree()

        # Shot view (center panel) - displays shots with video thumbnails
        self._animation_view = ShotView()
        # Shot Library: Use shot_proxy_model instead of animation proxy
        self._animation_view.setModel(self._shot_proxy_model)

        # Metadata panel (right panel)
        self._metadata_panel = MetadataPanel()

        # Apply panel (below metadata)
        self._apply_panel = ApplyPanel()

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    def _create_layout(self):
        """Create window layout"""

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main vertical layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Add header toolbar
        main_layout.addWidget(self._header_toolbar)

        # Add bulk edit toolbar
        main_layout.addWidget(self._bulk_edit_toolbar)

        # Create horizontal splitter for 3-panel layout
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Right panel container (metadata + apply panel stacked vertically)
        right_panel = QWidget()
        right_panel.setMinimumWidth(300)  # Ensure right panel is always visible
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._metadata_panel, 1)  # Stretchy
        right_layout.addWidget(self._apply_panel, 0)     # Fixed

        # Add panels to splitter
        # Left panel: Folder tree for navigating production folder structure
        self._folder_tree.setMinimumWidth(200)
        self._splitter.addWidget(self._folder_tree)
        self._animation_view.setMinimumWidth(400)
        self._splitter.addWidget(self._animation_view)
        self._splitter.addWidget(right_panel)

        # Set initial splitter sizes (from config) - will be overridden by saved settings
        self._splitter.setSizes(Config.DEFAULT_SPLITTER_SIZES)

        # Set stretch factors (center panel gets most space)
        self._splitter.setStretchFactor(0, 0)  # Folder tree: fixed-ish
        self._splitter.setStretchFactor(1, 1)  # Animation view: stretchy
        self._splitter.setStretchFactor(2, 0)  # Metadata: fixed-ish

        # Ensure splitter handle is visible for resizing
        self._splitter.setHandleWidth(4)

        # Add splitter to layout
        main_layout.addWidget(self._splitter, 1)

    def _init_controllers(self):
        """Initialize controllers for delegated functionality"""

        # Filter controller - manages proxy model interactions for shots
        self._filter_ctrl = FilterController(self._shot_proxy_model, self._status_bar)

        # Bulk edit controller - manages bulk operations (stub for Shot Library)
        self._bulk_edit_ctrl = BulkEditController(
            parent=self,
            animation_view=self._animation_view,
            animation_model=self._shot_model,
            db_service=self._db_service,
            event_bus=self._event_bus,
            status_bar=self._status_bar,
            reload_animations_callback=self._reload_shots
        )

    def _reload_shots(self):
        """Reload shots - used by controllers (Shot Library stub)"""
        # Shot Library doesn't reload from DB, it re-scans folders
        pass

    def _connect_signals(self):
        """Connect signals and slots"""

        # Note: Folder tree is display-only - clicking items doesn't trigger scans
        # Only the header toolbar dropdown changes what shots are displayed

        # Animation view selection -> update metadata panel
        self._animation_view.selectionModel().selectionChanged.connect(
            self._on_animation_selection_changed
        )

        # Animation view selection -> update event bus (for bulk toolbar)
        self._animation_view.selectionModel().selectionChanged.connect(
            self._animation_view._on_selection_changed
        )

        # Shot view context menu -> show options
        self._animation_view.shot_context_menu.connect(self._on_shot_context_menu)

        # Header toolbar search -> filter shots (maintains editorial order)
        self._header_toolbar.search_text_changed.connect(self._on_search_text_changed)

        # Header toolbar view mode -> ShotView only supports grid mode (16:9 cards)
        # self._header_toolbar.view_mode_changed.connect(self._animation_view.set_view_mode)

        # Header toolbar card size -> update view
        self._header_toolbar.card_size_changed.connect(self._animation_view.set_card_size)

        # Header toolbar scan folder -> scan for shots (Shot Library)
        self._header_toolbar.scan_folder_clicked.connect(self._on_scan_folder_requested)
        # Also sync with folder tree
        self._header_toolbar.scan_folder_clicked.connect(self._folder_tree.set_root_folder)

        # Header toolbar settings -> show settings dialog
        self._header_toolbar.settings_clicked.connect(self._show_settings)

        # Header toolbar preview mode toggle -> update all shots
        self._header_toolbar.preview_mode_changed.connect(self._on_preview_mode_changed)

        # Header toolbar app mode change -> switch between Shot/Analysis modes
        self._header_toolbar.app_mode_changed.connect(self._on_app_mode_changed)

        # Header toolbar sequence review -> open review dialog
        self._header_toolbar.sequence_review_clicked.connect(self._on_sequence_review_clicked)

        # Header toolbar clip extractor -> open clip extractor dialog
        self._header_toolbar.clip_extractor_clicked.connect(self._on_clip_extractor_clicked)

        # Header toolbar render manager -> open render manager dialog
        self._header_toolbar.render_manager_clicked.connect(self._on_render_manager_clicked)

        # Folder filter toggle + tree click -> filter shots by folder path
        self._header_toolbar.folder_filter_toggled.connect(self._on_folder_filter_toggled)
        self._folder_tree.folder_clicked.connect(self._on_folder_tree_clicked)

        # Metadata panel notes changed -> refresh notes badges
        self._metadata_panel.notes_changed.connect(self._on_notes_changed)

        # Bulk edit toolbar signals
        self._bulk_edit_toolbar.remove_tags_clicked.connect(self._on_remove_tags)
        self._bulk_edit_toolbar.move_to_folder_clicked.connect(self._on_move_to_folder)
        self._bulk_edit_toolbar.gradient_preset_selected.connect(self._on_gradient_preset_selected)
        self._bulk_edit_toolbar.custom_gradient_clicked.connect(self._on_custom_gradient_clicked)
        self._bulk_edit_toolbar.restore_clicked.connect(self._on_restore_clicked)

        # Event bus signals
        self._event_bus.loading_started.connect(self._on_loading_started)
        self._event_bus.loading_finished.connect(self._on_loading_finished)
        self._event_bus.error_occurred.connect(self._on_error)
        self._event_bus.folder_changed.connect(self._on_folder_changed)
        self._event_bus.settings_changed.connect(self._on_settings_changed)
        self._event_bus.animation_updated.connect(self._on_animation_updated)
        self._event_bus.filter_changed.connect(self._on_filter_changed)

        # Setup global keyboard shortcuts
        self._setup_shortcuts()

    def _inject_services(self):
        """Inject services into widgets after all are created."""
        # Inject audit service into metadata panel for status change logging
        if hasattr(self, '_audit_service') and self._audit_service:
            self._metadata_panel.set_audit_service(self._audit_service)

            # Inject audit service into user service for user action logging
            if hasattr(self, '_user_service') and self._user_service:
                self._user_service.set_audit_service(self._audit_service)

        # Inject shot data service into metadata panel
        shot_data_service = get_shot_data_service()
        if hasattr(self._metadata_panel, '_shot_data_service'):
            self._metadata_panel._shot_data_service = shot_data_service

    def _setup_shortcuts(self):
        """Setup global keyboard shortcuts for folder tree expand/collapse."""
        # Shift + Plus (regular keyboard): Expand one level
        shortcut_expand = QShortcut(QKeySequence("Shift++"), self)
        shortcut_expand.activated.connect(self._folder_tree.expand_one_level)

        # Shift + Equal (for keyboards where + requires shift): Expand one level
        shortcut_expand_eq = QShortcut(QKeySequence("Shift+="), self)
        shortcut_expand_eq.activated.connect(self._folder_tree.expand_one_level)

        # Numpad Plus: Expand one level (no shift needed)
        shortcut_expand_num = QShortcut(QKeySequence(Qt.Key.Key_Plus), self)
        shortcut_expand_num.activated.connect(self._folder_tree.expand_one_level)

        # Shift + Minus (regular keyboard): Collapse one level
        shortcut_collapse = QShortcut(QKeySequence("Shift+-"), self)
        shortcut_collapse.activated.connect(self._folder_tree.collapse_one_level)

        # Shift + Underscore: Collapse one level
        shortcut_collapse_us = QShortcut(QKeySequence("Shift+_"), self)
        shortcut_collapse_us.activated.connect(self._folder_tree.collapse_one_level)

        # Numpad Minus: Collapse one level (no shift needed)
        shortcut_collapse_num = QShortcut(QKeySequence(Qt.Key.Key_Minus), self)
        shortcut_collapse_num.activated.connect(self._folder_tree.collapse_one_level)

    def _load_settings(self):
        """Load window and splitter settings"""

        settings = QSettings(Config.APP_AUTHOR, Config.APP_NAME)

        # Window geometry
        if settings.contains("window/geometry"):
            self.restoreGeometry(settings.value("window/geometry"))

        # Window state
        if settings.contains("window/state"):
            self.restoreState(settings.value("window/state"))

        # Splitter sizes - ensure all panels are visible
        if settings.contains("splitter/sizes"):
            sizes = settings.value("splitter/sizes")
            if sizes:
                try:
                    sizes = [int(s) for s in sizes]
                    # Ensure minimum sizes for all panels (left: 200, center: 400, right: 300)
                    if len(sizes) >= 3 and sizes[0] >= 150 and sizes[1] >= 300 and sizes[2] >= 200:
                        self._splitter.setSizes(sizes)
                    else:
                        # Reset to defaults if any panel is too small
                        self._splitter.setSizes(Config.DEFAULT_SPLITTER_SIZES)
                except (ValueError, TypeError):
                    self._splitter.setSizes(Config.DEFAULT_SPLITTER_SIZES)
        else:
            # No saved settings, use defaults
            self._splitter.setSizes(Config.DEFAULT_SPLITTER_SIZES)
        
        # Update operation mode indicator in header toolbar
        self._header_toolbar.update_operation_mode_indicator()

    def _save_settings(self):
        """Save window and splitter settings"""

        settings = QSettings(Config.APP_AUTHOR, Config.APP_NAME)

        # Window geometry
        settings.setValue("window/geometry", self.saveGeometry())

        # Window state
        settings.setValue("window/state", self.saveState())

        # Splitter sizes
        settings.setValue("splitter/sizes", self._splitter.sizes())

    def _load_animations(self):
        """Shot Library: Initialize shot display (no animation loading needed)"""
        # Shot Library uses folder scanning to discover shots
        # Animations are not loaded - shots are discovered on folder selection
        self._status_bar.showMessage("Ready - select a production folder to scan for shots")

    def _setup_queue_watcher(self):
        """Setup file system watcher for queue directory to detect Blender notifications"""
        self._queue_watcher = QFileSystemWatcher(self)
        self._queue_check_timer = QTimer(self)
        self._queue_check_timer.timeout.connect(self._check_queue_notifications)

        # Get queue directory path
        library_path = Config.load_library_path()
        if library_path:
            queue_dir = Path(library_path) / ".queue"
            queue_dir.mkdir(parents=True, exist_ok=True)

            # Watch the queue directory for changes
            self._queue_watcher.addPath(str(queue_dir))
            self._queue_watcher.directoryChanged.connect(self._on_queue_directory_changed)

            # Also start periodic check (backup in case watcher misses events)
            self._queue_check_timer.start(Config.QUEUE_CHECK_INTERVAL_MS)

    def _on_queue_directory_changed(self, path: str):
        """Handle changes in queue directory"""
        # Use a short delay to let file writes complete
        QTimer.singleShot(Config.QUEUE_NOTIFICATION_DELAY_MS, self._check_queue_notifications)

    def _check_queue_notifications(self):
        """Check for and process preview update notifications from Blender"""
        library_path = Config.load_library_path()
        if not library_path:
            return

        queue_dir = Path(library_path) / ".queue"
        if not queue_dir.exists():
            return

        # First, handle preview_updating_*.json files (release file locks before Blender renders)
        for notification_file in queue_dir.glob("preview_updating_*.json"):
            try:
                with open(notification_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                animation_id = data.get('animation_id')
                preview_path = data.get('preview_path', '')

                if animation_id:
                    # Release the video file if it's currently loaded
                    self._release_preview_file(animation_id, preview_path)

                # Delete notification file after processing
                notification_file.unlink()

            except Exception as e:
                try:
                    notification_file.unlink()
                except OSError:
                    pass

        # Find preview_updated_*.json files
        for notification_file in queue_dir.glob("preview_updated_*.json"):
            try:
                with open(notification_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                animation_id = data.get('animation_id')
                animation_name = data.get('animation_name', 'Unknown')

                if animation_id:
                    # Emit animation updated event to refresh the preview
                    self._event_bus.animation_updated.emit(animation_id)

                    # Update status bar
                    self._status_bar.showMessage(f"Preview updated: {animation_name}")

                    # Refresh the currently selected animation if it matches
                    self._refresh_animation_preview(animation_id)

                # Delete notification file after processing
                notification_file.unlink()

            except Exception as e:
                # Still try to delete the file to avoid infinite loop
                try:
                    notification_file.unlink()
                except OSError:
                    pass

    def _release_preview_file(self, animation_id: str, preview_path: str = ''):
        """Release video file lock so Blender can update it"""
        # Release from metadata panel if this animation is currently loaded
        if hasattr(self._metadata_panel, '_animation'):
            current = self._metadata_panel._animation
            if current and current.get('uuid') == animation_id:
                # Clear the video preview to release the file handle
                if hasattr(self._metadata_panel, '_video_preview'):
                    self._metadata_panel._video_preview.clear()

        # Also stop any hover preview that might have this file
        if hasattr(self._animation_view, '_hover_popup') and self._animation_view._hover_popup:
            self._animation_view._hover_popup.hide_preview()

    def _refresh_animation_preview(self, animation_id: str):
        """Refresh preview for a specific shot if it's currently displayed"""
        # Invalidate thumbnail cache so it reloads from disk
        self._thumbnail_loader.invalidate_shot(animation_id)

        # Refresh shot data in the model (triggers dataChanged)
        self._shot_model.refresh_shot(animation_id)

        # Force shot view to repaint with fresh thumbnails
        self._animation_view.viewport().update()

    def _show_settings(self):
        """Show settings dialog"""
        dialog = SettingsDialog(self._theme_manager, self)

        # Connect schema change signal (T153, T155)
        dialog.schema_changed.connect(self._on_schema_changed)
        
        # Connect operation mode change signal
        dialog.operation_mode_tab.mode_changed.connect(self._on_operation_mode_changed)

        dialog.exec()
        
        # After dialog closes, refresh operation mode indicator
        # (in case Apply was clicked or mode was changed)
        self._header_toolbar.update_operation_mode_indicator()
    
    def _on_operation_mode_changed(self, mode):
        """Handle operation mode change from settings."""
        # Update header toolbar indicator
        self._header_toolbar.update_operation_mode_indicator()
        
        # Clear control authority cache to ensure fresh read
        self._control_authority.clear_cache()

    # ==================== SLOT HANDLERS ====================

    def _on_folder_selected(self, folder_id: int, folder_name: str, recursive: bool = True):
        """Handle folder selection - Shot Library uses production folder browsing"""
        # Clear special filters
        self._filter_ctrl.clear_special_filters()
        self._filter_ctrl.update_status(folder_name)

    def _on_animation_selection_changed(self, selected, deselected):
        """Handle shot/animation selection change"""

        selected_indexes = self._animation_view.selectionModel().selectedIndexes()

        if selected_indexes:
            # Get first selected shot
            index = selected_indexes[0]
            source_index = self._shot_proxy_model.mapToSource(index)
            shot = self._shot_model.get_shot_at_index(source_index.row())

            if shot:
                # Map shot fields to animation fields for metadata panel compatibility
                # The panel expects 'preview_path', shots have 'latest_playblast_path'
                if shot.get('latest_playblast_path') and not shot.get('preview_path'):
                    shot['preview_path'] = shot['latest_playblast_path']
                if shot.get('shot_name') and not shot.get('name'):
                    shot['name'] = shot['shot_name']

                # Add version_label from latest_playblast_version for metadata display
                version = shot.get('latest_playblast_version', 1)
                if version:
                    shot['version_label'] = f"v{version:03d}"
                else:
                    shot['version_label'] = "v001"

                # Set version_group_id for lineage tracking (fallback to UUID if not set)
                if not shot.get('version_group_id'):
                    shot['version_group_id'] = shot.get('uuid')

                # Update metadata panel
                self._metadata_panel.set_animation(shot)

                # Update apply panel
                self._apply_panel.set_animation(shot)

                # Update status
                name = shot.get('shot_name', shot.get('name', 'Unknown'))
                self._status_bar.showMessage(f"Selected: {name}")
        else:
            # Clear metadata panel
            self._metadata_panel.clear()

            # Clear apply panel
            self._apply_panel.clear()

            self._status_bar.showMessage("Ready")

    def _on_notes_changed(self):
        """Handle notes changed - refresh view (Shot Library stub)"""
        # Shot Library doesn't use notes badges like Animation Library
        self._animation_view.viewport().update()

    def _on_animation_double_clicked(
        self,
        uuid: str,
        mirror: bool = False,
        use_slots: bool = False,
        insert_at_playhead: bool = False
    ):
        """Legacy animation double-click handler - Shot Library uses _on_shot_double_clicked instead"""
        # Shot Library is read-only and doesn't apply animations to Blender
        # This method is kept for interface compatibility but does nothing
        pass

    def _on_animation_context_menu(self, uuid: str, position):
        """Legacy animation context menu handler - Shot Library uses _on_shot_context_menu instead"""
        # Shot Library uses shot-specific context menu
        # This method is kept for interface compatibility but does nothing
        pass

    def _show_version_history(self, version_group_id: str, shot_folder=None, blend_stem=None):
        """Show version history dialog"""
        from .dialogs import VersionHistoryDialog

        # Check if we're in analysis mode
        analysis_mode = self._app_mode == "analysis"
        folder_videos = None

        if analysis_mode:
            # Get shot data to find the video path
            shot_data = self._shot_model.get_shot_by_uuid(version_group_id)
            if shot_data:
                video_path = shot_data.get('latest_playblast_path')
                if video_path and self._reference_indexer:
                    # Get all sibling videos in the same folder
                    from pathlib import Path
                    siblings = self._reference_indexer.get_sibling_videos(Path(video_path))
                    folder_videos = [str(v.file_path) for v in siblings]
                    shot_folder = str(Path(video_path).parent)

        dialog = VersionHistoryDialog(
            version_group_id,
            parent=self,
            theme_manager=self._theme_manager,
            shot_folder=shot_folder,
            blend_stem=blend_stem,
            analysis_mode=analysis_mode,
            folder_videos=folder_videos
        )

        # Connect signals
        dialog.version_selected.connect(self._on_version_selected)

        dialog.exec()

    def _on_version_selected(self, uuid: str):
        """Handle version selection from history dialog - apply it"""
        self._on_animation_double_clicked(uuid)

    def _toggle_favorite(self, uuid: str):
        """Toggle favorite status (Shot Library stub - favorites not implemented for shots)"""
        # Shot Library doesn't use favorites for shots
        pass

    def _on_search_text_changed(self, text: str):
        """Handle search text change"""
        self._filter_ctrl.set_search_text(text)

    def _on_preview_mode_changed(self, mode: str):
        """
        Handle Preview Mode toggle from header toolbar (PB/LD/RD buttons).

        This is ALWAYS global - affects all cards regardless of selection.
        For per-card toggle, use the eye icon in the metadata panel.

        Args:
            mode: "playblast", "lookdev", or "render"
        """
        # Always apply to ALL shots (global toggle)
        self._shot_model.set_all_preview_mode(mode)

        # Update global mode in controller
        if self._preview_mode_controller:
            self._preview_mode_controller.set_global_mode(mode)

        # Update metadata panel to match global mode
        self._metadata_panel.set_preview_mode(mode)

        # Update status bar
        mode_labels = {"playblast": "Playblast", "lookdev": "Lookdev", "render": "Render"}
        mode_label = mode_labels.get(mode, mode.capitalize())
        self._status_bar.showMessage(f"Preview mode: {mode_label} (all shots)")

        # Force view repaint
        self._animation_view.viewport().update()

    def _on_app_mode_changed(self, mode: str):
        """
        Handle App Mode change from header toolbar (Shot Mode / Analysis Mode).

        In Shot Mode: Normal shot management workflow
        In Analysis Mode: Reference video analysis (like SyncSketch/Keyframe Pro)

        Args:
            mode: "shot" or "analysis"
        """
        if mode == self._app_mode:
            return

        self._app_mode = mode

        # Clear current view
        self._shot_model.set_shots([])  # Clear by setting empty list
        self._metadata_panel.clear()
        self._apply_panel.clear()

        # Update metadata panel mode (changes button text)
        self._metadata_panel.set_analysis_mode(mode == "analysis")

        # Analysis Mode: Disable filters that would hide reference videos
        if mode == "analysis":
            self._shot_proxy_model.set_show_latest_only(False)
            self._shot_proxy_model.set_require_mp4(False)  # Don't require playblast field
            self._shot_proxy_model.set_require_blend(False)  # Don't require blend file
            self._shot_proxy_model.clear_all_filters()  # Clear all other filters too
        else:
            # Shot Mode: Restore default filters
            self._shot_proxy_model.set_show_latest_only(True)
            self._shot_proxy_model.set_require_mp4(True)
            self._shot_proxy_model.set_require_blend(True)

        # Update status bar
        if mode == "analysis":
            self._status_bar.showMessage("Analysis Mode - select a folder with reference videos")
        else:
            self._status_bar.showMessage("Shot Mode - select a production folder to scan for shots")

        # Rescan current folder with new mode if a folder is selected
        current_folder = self._header_toolbar.get_current_folder()
        if current_folder:
            self._on_scan_folder_requested(current_folder)

    def _on_sequence_review_clicked(self):
        """
        Handle Sequence Review button click.

        Opens a fullscreen dialog to review all currently visible shots
        in editorial order with auto-play capability.
        """
        # Get filtered shots from proxy model (respects all active filters)
        shots = []
        proxy = self._shot_proxy_model
        for row in range(proxy.rowCount()):
            index = proxy.index(row, 0)
            # Get shot data from the model
            source_index = proxy.mapToSource(index)
            shot_data = self._shot_model.get_shot_at_index(source_index.row())
            if shot_data:
                shots.append(shot_data)

        if not shots:
            # Show message - no shots to review
            QMessageBox.information(
                self,
                "No Shots",
                "No shots available to review.\n\n"
                "Load a project folder with playblasts first."
            )
            return

        # Get currently selected shot index (if any)
        current_index = 0
        selected = self._animation_view.selectionModel().selectedIndexes()
        if selected:
            # Find the selected shot's position in the filtered list
            selected_proxy_row = selected[0].row()
            selected_source_index = proxy.mapToSource(selected[0])
            selected_shot = self._shot_model.get_shot_at_index(selected_source_index.row())
            if selected_shot:
                selected_uuid = selected_shot.get('uuid')
                for i, shot in enumerate(shots):
                    if shot.get('uuid') == selected_uuid:
                        current_index = i
                        break

        # Open the sequence review dialog
        dialog = SequenceReviewDialog(shots, current_index, self)
        dialog.exec()

    def _on_clip_extractor_clicked(self):
        """Open Clip Extractor for the currently selected video card."""
        selected = self._animation_view.get_selected_uuids()
        if not selected:
            self._status_bar.showMessage("Select a video first", 3000)
            return
        uuid = selected[0]
        shot = self._shot_model.get_shot_by_uuid(uuid)
        if not shot:
            return
        video_path = shot.get('latest_playblast_path')
        if not video_path or not Path(video_path).exists():
            self._status_bar.showMessage("No video file found", 3000)
            return
        dialog = ClipExtractorDialog(
            video_path=Path(video_path),
            video_name=shot.get('shot_name', 'video'),
            parent=self,
        )
        dialog.exec()

    def _on_render_manager_clicked(self):
        """
        Handle Render Manager button click.

        Opens the Render Manager dialog for managing PNG/EXR image sequences
        with proxy generation and version management.
        """
        # Get filtered shots from proxy model (respects all active filters)
        shots = []
        proxy = self._shot_proxy_model
        for row in range(proxy.rowCount()):
            index = proxy.index(row, 0)
            source_index = proxy.mapToSource(index)
            shot_data = self._shot_model.get_shot_at_index(source_index.row())
            if shot_data:
                shots.append(shot_data)

        if not shots:
            QMessageBox.information(
                self,
                "No Shots",
                "No shots available.\n\n"
                "Load a project folder with shots first."
            )
            return

        # Open the render manager dialog
        dialog = RenderManagerDialog(shots, self)
        dialog.exec()

    def _on_folder_filter_toggled(self, active: bool):
        """Handle folder filter toggle."""
        if not active:
            self._shot_proxy_model.clear_folder_filter()

    def _on_folder_tree_clicked(self, folder_path: str):
        """Handle folder tree click — filter if toggle is active."""
        if self._header_toolbar.is_folder_filter_active():
            self._shot_proxy_model.set_folder_filter(folder_path)

    def _on_sort_changed(self, sort_by: str, sort_order: str):
        """Handle sort option change from toolbar"""
        self._filter_ctrl.set_sort_config(sort_by, sort_order)

    def _on_edit_mode_changed(self, enabled: bool):
        """Handle edit mode toggle"""

        if enabled:
            self._bulk_edit_toolbar.show()
        else:
            self._bulk_edit_toolbar.hide()

    def _on_restore_clicked(self):
        """Handle restore button click in bulk edit toolbar (no-op for Shot Library)"""
        pass

    def _on_apply_with_options(self, options: dict):
        """Legacy apply handler - Shot Library is read-only"""
        # Shot Library doesn't apply animations - this is a no-op
        pass

    def _on_refresh_library(self):
        """Handle refresh library button click - rescan current folder for shots"""
        # Shot Library: Trigger rescan of current watched folder
        self._trigger_rescan()

        # Refresh folder tree to show any new folders
        self._folder_tree.refresh()

        self._status_bar.showMessage("Library refreshed")

    def _on_create_folder(self):
        """Handle create new folder request from header button"""
        # Delegate to folder tree widget
        self._folder_tree.create_folder_with_dialog()

    def _on_remove_tags(self):
        """Handle remove tags from selected animations"""
        self._bulk_edit_ctrl.remove_tags()

    def _on_gradient_preset_selected(self, name: str, top_color: tuple, bottom_color: tuple):
        """Handle gradient preset selection from dropdown"""
        self._bulk_edit_ctrl.apply_gradient_preset(name, top_color, bottom_color)

    def _on_custom_gradient_clicked(self):
        """Handle custom gradient selection - opens color picker dialog"""
        self._bulk_edit_ctrl.apply_custom_gradient()

    def _on_move_to_folder(self):
        """Handle move selected animations to folder"""
        self._bulk_edit_ctrl.move_to_folder()

    def _on_loading_started(self, operation: str):
        """Handle loading started"""
        self._status_bar.showMessage(f"{operation}...")

    def _on_loading_finished(self, operation: str):
        """Handle loading finished"""
        count = self._shot_proxy_model.rowCount()
        self._status_bar.showMessage(f"{count} shots")

    def _on_error(self, error_type: str, error_message: str):
        """Handle error"""
        self._status_bar.showMessage(f"Error: {error_message}")

    def _on_settings_changed(self, setting_name: str, value):
        """Handle settings changes from settings dialog"""
        if setting_name == "hide_shortcut_toggles":
            # Update apply panel toggles visibility
            self._apply_panel.set_shortcut_toggles_visible(not value)

    def _on_folder_changed(self, folder_id: int):
        """Handle folder changed - Shot Library triggers rescan"""
        # Shot Library: Rescan current folder to pick up changes
        self._trigger_rescan()

    def _on_animation_updated(self, uuid: str):
        """Handle shot updated event - refresh the card in the view"""
        if uuid:
            # Refresh the shot in the model to update the card
            self._shot_model.refresh_shot(uuid)

    def _on_filter_changed(self, filter_criteria: dict):
        """Handle filter change from header toolbar or status change"""
        if 'status' in filter_criteria:
            # Set status filter (from dropdown)
            status = filter_criteria['status']
            if status and status != "All Statuses":
                # Apply single status filter
                self._shot_proxy_model.set_status_filter({status})
            else:
                # Clear status filter
                self._shot_proxy_model.clear_status_filter()
        elif 'add_status' in filter_criteria:
            # Add status to filter (from status badge change)
            # This keeps the shot visible after changing its status
            status = filter_criteria['add_status']
            current_filter = self._shot_proxy_model.get_status_filter()
            if current_filter:  # Only if a filter is active
                self._shot_proxy_model.add_status_filter(status)

    # ==================== SHOT LIBRARY: SHOT INDEXING ====================

    def _init_shot_indexer(self):
        """Initialize the shot indexer with active folder schema from DB, or fallback to default"""
        try:
            # Try loading the active schema from the project database
            schema_parser = None
            try:
                from ..services.database.folder_schemas import FolderSchemaRepository
                if self._db_service and self._db_service._connection:
                    repo = FolderSchemaRepository(self._db_service._connection)
                    active = repo.get_active()
                    if active:
                        schema_parser = FolderSchemaParser.from_dict(active['config'])
            except Exception as e:
                pass

            # Fallback to simple_shot preset
            if schema_parser is None:
                schema_parser = FolderSchemaParser.from_preset('simple_shot')

            self._schema_parser = schema_parser
            self._shot_indexer = ShotIndexer(self._schema_parser)

            # Create playblast indexer for finding MP4s
            self._playblast_indexer = PlayblastIndexer()

            # Create lookdev indexer for finding rendered previews
            self._lookdev_indexer = LookdevIndexer()

            # Create unified services (refactored architecture)
            self._discovery_service = DiscoveryService(
                shot_indexer=self._shot_indexer,
                playblast_indexer=self._playblast_indexer,
                lookdev_indexer=self._lookdev_indexer,
            )
            self._sync_service = SyncService(db_service=self._db_service)

            # Note: Shot indexer signals are now handled by ShotScanController
            # which wraps discovery_service (which uses shot_indexer internally)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._schema_parser = None
            self._shot_indexer = None
            self._playblast_indexer = None
            self._lookdev_indexer = None
            self._discovery_service = None
            self._sync_service = None

    def _init_reference_indexer(self):
        """Initialize the reference indexer for Analysis Mode."""
        try:
            self._reference_indexer = ReferenceIndexer()
        except Exception as e:
            self._reference_indexer = None

    def _init_folder_observer(self):
        """
        Initialize the folder observer for automatic re-indexing (T152).

        The FolderObserver watches production folder trees for changes and
        triggers automatic shot re-indexing when .blend or .mp4 files change.
        """
        try:
            from ..core.folder_observer import FolderObserver

            self._folder_observer = FolderObserver(
                debounce_ms=Config.FOLDER_OBSERVER_DEBOUNCE_MS if hasattr(Config, 'FOLDER_OBSERVER_DEBOUNCE_MS') else 250,
                recursive=True
            )

            # Connect folder observer signals (T152)
            self._folder_observer.changes_detected.connect(self._on_filesystem_changes)
            self._folder_observer.watch_error.connect(self._on_folder_observer_error)
            self._folder_observer.buffer_overflow.connect(self._on_folder_observer_overflow)

            # Track current watched path
            self._current_watch_id: Optional[str] = None
            self._current_watched_path: Optional[Path] = None

        except Exception as e:
            self._folder_observer = None
            self._current_watch_id = None
            self._current_watched_path = None

    def _init_review_services(self):
        """
        Initialize review services for shot review workflow (US3: T119-T122).

        Creates:
        - UserService for author attribution
        - ReviewService for comment persistence
        - AuditService for audit trail logging
        - EmbeddedAPIServer for REST API access
        """
        try:
            # Initialize user service (T121)
            self._user_service = UserService(self._db_service)

            # Initialize review service (T120)
            self._review_service = ReviewService()

            # Initialize audit service for audit trail
            self._audit_service = AuditService(
                db_service=self._db_service,
                user_service=self._user_service
            )

            # Initialize embedded API server
            self._init_api_server()

        except Exception as e:
            self._user_service = None
            self._review_service = None
            self._audit_service = None
            self._api_server = None

    def _init_new_controllers(self):
        """
        Initialize new controllers for God Class elimination.

        Creates:
        - ShotScanController: Orchestrates shot discovery and sync
        - SelectionController: Manages selection state
        - PreviewModeController: Manages preview mode (playblast/lookdev)
        """
        try:
            # Check required services exist before creating controller
            if not hasattr(self, '_discovery_service') or self._discovery_service is None:
                self._scan_controller = None
            elif not hasattr(self, '_sync_service') or self._sync_service is None:
                self._scan_controller = None
            else:
                # Create shot scan controller with services
                self._scan_controller = ShotScanController(
                    discovery_service=self._discovery_service,
                    sync_service=self._sync_service,
                    shot_model=self._shot_model,
                    db_service=self._db_service,
                    audit_service=getattr(self, '_audit_service', None),
                    parent=self
                )

                # Connect scan controller signals
                self._scan_controller.scan_started.connect(self._on_scan_started)
                self._scan_controller.scan_progress.connect(self._on_scan_progress)
                self._scan_controller.scan_complete.connect(self._on_scan_complete)
                self._scan_controller.scan_error.connect(self._on_scan_error)
                self._scan_controller.shots_ready.connect(self._on_shots_ready)

            # Create selection controller
            self._selection_controller = SelectionController(
                event_bus=self._event_bus,
                parent=self
            )

            # Create preview mode controller
            self._preview_mode_controller = PreviewModeController(
                db_service=self._db_service,
                event_bus=self._event_bus,
                parent=self
            )


        except Exception as e:
            import traceback
            traceback.print_exc()
            self._scan_controller = None
            self._selection_controller = None
            self._preview_mode_controller = None

    def _on_scan_started(self, folder_path: str):
        """Handle scan started from controller."""
        self._event_bus.start_loading("Scanning for shots")
        self._status_bar.showMessage(f"Scanning: {Path(folder_path).name}...")

    def _on_scan_progress(self, current: int, total: int):
        """Handle scan progress from controller."""
        self._status_bar.showMessage(f"Scanning shots: {current}/{total}")

    def _on_scan_complete(self, result):
        """Handle scan complete from controller."""
        self._event_bus.finish_loading("Scanning for shots")

        # Update status bar
        if result.shots_with_media == 0:
            self._status_bar.showMessage(
                f"Found {result.total_shots} shots but no playblasts yet"
            )
        else:
            self._status_bar.showMessage(
                f"Loaded {result.shots_with_media} playblasts ({result.total_shots} shots total)"
            )

        # Start watching folder for changes
        if result.folder_path:
            self._start_watching_folder(result.folder_path)

        # Set audit service project path
        if hasattr(self, '_audit_service') and self._audit_service and result.folder_path:
            self._audit_service.set_project_path(str(result.folder_path))

    def _on_scan_error(self, error: str):
        """Handle scan error from controller."""
        self._event_bus.finish_loading("Scanning for shots")
        self._status_bar.showMessage(f"Scan error: {error}")

    def _on_shots_ready(self, shot_dicts: list):
        """Handle shots ready from controller - update model."""
        if shot_dicts:
            self._shot_model.set_shots(shot_dicts)

    def _set_window_icon(self):
        """Set the window icon for title bar and taskbar."""
        import sys
        from pathlib import Path
        from PyQt6.QtGui import QIcon

        # Find icon path - check multiple locations
        icon_paths = []

        if getattr(sys, 'frozen', False):
            # Running as bundled exe
            base_path = Path(sys._MEIPASS)
            icon_paths.append(base_path / 'assets' / 'Icon.png')
        else:
            # Running from source
            icon_paths.append(Config.ASSETS_DIR / 'Icon.png')
            icon_paths.append(Path(__file__).parent.parent.parent / 'Icon.png')

        for icon_path in icon_paths:
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                return

    def _init_api_server(self):
        """
        Initialize and start the embedded REST API server.

        The API runs on http://localhost:8765 by default.
        External apps (like the orchestration app) can connect to this.
        """
        if not API_AVAILABLE or EmbeddedAPIServer is None:
            self._api_server = None
            return

        try:
            self._api_server = EmbeddedAPIServer(
                db_service=self._db_service,
                user_service=self._user_service,
                audit_service=self._audit_service
            )

            # Start on port 8765
            self._api_server.start(host="127.0.0.1", port=8765)

        except Exception:
            self._api_server = None

    def _on_shot_context_menu(self, uuid: str, position):
        """
        Handle shot card right-click context menu from ShotView.

        Args:
            uuid: Shot UUID from the shot_context_menu signal
            position: QPoint for menu position
        """
        shot_data = self._shot_model.get_shot_by_uuid(uuid)
        if not shot_data:
            return

        name = shot_data.get('shot_name', 'Unknown Shot')

        # Determine the target set: full multi-selection if the right-clicked
        # shot is part of it, otherwise just the right-clicked shot.
        selected_uuids = self._animation_view.get_selected_uuids()
        if uuid in selected_uuids and len(selected_uuids) > 1:
            target_uuids = selected_uuids
        else:
            target_uuids = [uuid]

        # Create context menu
        menu = QMenu(self)

        # View Lineage action - opens version history dialog
        lineage_action = menu.addAction("View Lineage")
        lineage_action.triggered.connect(lambda: self._show_version_history(uuid))

        menu.addSeparator()

        # Set Priority submenu (v12) — works on the full selection
        priority_menu_label = (
            f"Set Priority for {len(target_uuids)} shots"
            if len(target_uuids) > 1
            else "Set Priority"
        )
        priority_menu = menu.addMenu(priority_menu_label)
        for label, value in (("Low", 1), ("Normal", 2), ("Urgent", 3)):
            action = priority_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, v=value, ids=list(target_uuids): self._on_bulk_priority_set(ids, v)
            )

        menu.addSeparator()

        # Show playblast info if available
        playblast_path = shot_data.get('latest_playblast_path')
        if playblast_path:
            playblast_version = shot_data.get('latest_playblast_version', 0)
            info_action = menu.addAction(f"Playblast v{playblast_version}")
            info_action.setEnabled(False)  # Info only, not clickable

        # Show menu at cursor position
        menu.exec(position)

    def _on_bulk_priority_set(self, shot_uuids: list, priority: int):
        """Apply a priority value to many shots and surface the result count."""
        shot_data_service = get_shot_data_service()
        audit_service = getattr(self, '_audit_service', None)
        count = shot_data_service.bulk_set_priority(shot_uuids, priority, audit_service=audit_service)
        priority_label = {1: 'Low', 2: 'Normal', 3: 'Urgent'}.get(priority, str(priority))
        if count > 0:
            self._status_bar.showMessage(
                f"{count} shot{'s' if count != 1 else ''} updated to priority {priority_label}",
                5000,
            )
        else:
            self._status_bar.showMessage("No priority changes applied", 3000)

    def _on_scan_folder_requested(self, folder_path: str):
        """
        Handle folder scan request from header toolbar.

        In Shot Mode: Triggers shot discovery for the selected production folder
        using the ShotScanController.
        In Analysis Mode: Discovers all video files in the selected folder.

        Args:
            folder_path: Path to the folder to scan
        """
        if not folder_path:
            return

        from pathlib import Path
        path = Path(folder_path)

        if not path.exists():
            self._status_bar.showMessage(f"Folder not found: {folder_path}")
            return

        # Analysis Mode: Discover all video files
        if self._app_mode == "analysis":
            self._scan_folder_for_videos(path)
            return

        # Shot Mode: Use ShotScanController for discovery
        # Controller handles everything: discovery, sync, stitching, enrichment
        # Results come back via signals (_on_scan_complete, _on_shots_ready)
        if self._scan_controller is None:
            self._status_bar.showMessage("Error: Scan controller not initialized")
            return

        self._scan_controller.scan_folder(
            path,
            require_media=True,
            include_views=True,
            stitch_videos=True,
            enrich_tasks=True
        )


    def _on_shot_discovered(self, shot: 'DiscoveredShot'):
        """Handle individual shot discovery during scan"""
        # This can be used to progressively update the UI
        # For now, just log the discovery

    def _convert_discovered_shot_to_dict(self, shot: 'DiscoveredShot') -> dict:
        """
        Convert a DiscoveredShot to dict format for ShotListModel.

        Args:
            shot: DiscoveredShot instance from shot indexer

        Returns:
            Dict with shot data for the model
        """
        import uuid

        # Generate deterministic UUID based on folder path AND blend file
        # This ensures each shot version (each blend file) gets a unique UUID
        # so playblasts stored in DB can be found by shot_id
        namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # URL namespace
        # Include blend_file path to make UUID unique per shot version
        blend_file_str = str(shot.blend_file).replace('\\', '/') if shot.blend_file else ''
        shot_uuid = str(uuid.uuid5(namespace, blend_file_str))

        # Get blend_stem for playblast subfolder lookup
        blend_stem = shot.blend_file.stem if shot.blend_file else None

        return {
            'uuid': shot_uuid,
            'id': shot_uuid,
            'folder_path': str(shot.folder_path),
            'blend_file': str(shot.blend_file),
            'blend_stem': blend_stem,  # For playblast subfolder lookup
            'shot_name': shot.identity.shot_name,
            'episode_num': shot.identity.episode_num,
            'sequence_num': shot.identity.sequence_num,
            'scene_num': shot.identity.scene_num,
            'shot_num': shot.identity.shot_num,
            'editorial_order': shot.identity.editorial_order,
            'status': shot.status.value,
            'parse_warning': shot.identity.parse_warning,
            'created_at': shot.discovered_at.isoformat(),
            'updated_at': shot.discovered_at.isoformat(),
            # Playblast info - to be populated later
            'latest_playblast_path': None,
            'latest_playblast_version': None,
            'playblast_count': 0,
            'thumbnail_path': None,
            # Lookdev info - to be populated later
            'latest_lookdev_path': None,
            'latest_lookdev_version': None,
            'lookdev_count': 0,
            # Preview mode (playblast or lookdev) - default to playblast
            'preview_mode': 'playblast',
            # Shot version grouping
            'base_shot_name': shot.identity.base_shot_name,
            'shot_version': shot.identity.shot_version,
            'version_group_id': shot.identity.version_group_id,
            'is_latest_shot_version': shot.identity.is_latest_shot_version,
            'version_count': 1,  # Will be updated after grouping
            # Multi-camera reference file fields
            'shot_role': shot.identity.shot_role,
            'master_blend_file': shot.identity.master_blend_file,
            'view_name': shot.identity.view_name,
            'master_shot_id': None,  # Will be resolved after all shots synced
            'view_count': 0,  # Will be populated for masters
        }

    # ==================== ANALYSIS MODE: VIDEO INDEXING ====================

    def _scan_folder_for_videos(self, folder_path: Path):
        """
        Scan folder for all video files (Analysis Mode).

        Unlike Shot Mode, this discovers ALL video files without naming
        conventions or playblast requirements.

        Args:
            folder_path: Path to the folder to scan
        """
        if not self._reference_indexer:
            self._status_bar.showMessage("Reference indexer not initialized")
            return

        self._event_bus.start_loading("Scanning for videos")
        self._status_bar.showMessage(f"Scanning: {folder_path.name}...")

        try:
            # Discover all video files (recursive to find videos in subfolders)
            videos = self._reference_indexer.discover_videos(folder_path, recursive=True)

            # Convert to shot model format for display
            video_dicts = []
            for video in videos:
                try:
                    video_dict = self._convert_discovered_video_to_dict(video)
                    video_dicts.append(video_dict)
                except Exception:
                    pass


            # Set in model
            self._shot_model.set_shots(video_dicts)

            # Force proxy to re-filter
            self._shot_proxy_model.invalidateFilter()

            # Force view update
            self._animation_view.viewport().update()

            # Store current folder for analysis mode
            self._current_analysis_folder = folder_path

            # Update status
            self._status_bar.showMessage(f"Found {len(videos)} videos in {folder_path.name}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._status_bar.showMessage(f"Scan error: {e}")

        self._event_bus.finish_loading("Scanning for videos")

    def _convert_discovered_video_to_dict(self, video: 'DiscoveredVideo') -> dict:
        """
        Convert a DiscoveredVideo to dict format for ShotListModel.

        Uses the video path hash as UUID for consistency with reference
        database storage.

        Args:
            video: DiscoveredVideo instance from reference indexer

        Returns:
            Dict with video data formatted for ShotListModel
        """
        from ..services.reference_database import ReferenceDatabase

        # Use video path hash as stable identifier
        video_id = ReferenceDatabase.get_video_id(str(video.file_path))

        return {
            'uuid': video_id,
            'id': video_id,
            'folder_path': str(video.file_path.parent),
            'shot_name': video.name,
            'name': video.name,
            # Use video path as preview path
            'preview_path': str(video.file_path),
            'latest_playblast_path': str(video.file_path),
            'latest_playblast_version': 1,
            'playblast_count': 1,
            # No lookdev for reference videos
            'latest_lookdev_path': None,
            'latest_lookdev_version': None,
            'lookdev_count': 0,
            # Default preview mode
            'preview_mode': 'playblast',
            # Video metadata
            'fps': video.metadata.fps if video.metadata else None,
            'frame_count': video.metadata.frame_count if video.metadata else None,
            'width': video.metadata.width if video.metadata else None,
            'height': video.metadata.height if video.metadata else None,
            'duration_ms': video.metadata.duration_ms if video.metadata else None,
            # Timestamps
            'created_at': video.created_at.isoformat(),
            'updated_at': video.created_at.isoformat(),
            # No versioning in analysis mode
            'editorial_order': 0,
            'status': 'reference',
            'is_latest_shot_version': True,
            'version_count': 1,
            # Flag for analysis mode
            'is_reference_video': True,
        }

    # ==================== FOLDER OBSERVER HANDLERS (T152) ====================

    def _on_filesystem_changes(self, changes: list):
        """
        Handle filesystem changes detected by FolderObserver (T152).

        This triggers incremental re-indexing when .blend or .mp4 files change.

        Args:
            changes: List of FileSystemChange objects
        """
        if not self._shot_indexer or not self._current_watched_path:
            return

        # Check if any changes are relevant (shots or playblasts)
        shot_changes = []
        playblast_changes = []

        for change in changes:
            path_str = str(change.path)
            if path_str.endswith('.blend'):
                shot_changes.append(change)
            elif path_str.endswith('.mp4'):
                playblast_changes.append(change)

        if not shot_changes and not playblast_changes:
            return

        # Log the changes

        # Re-index the current folder
        # Use incremental update via detect_changes if available
        if hasattr(self._shot_indexer, 'detect_changes') and shot_changes:
            try:
                # Get known shots from the model
                known_shots = [str(s.get('folder_path', '')) for s in self._shot_model.get_all_shots()]
                new_shots, removed_paths, modified_paths = self._shot_indexer.detect_changes(
                    self._current_watched_path,
                    known_shots
                )
                # Update the model incrementally
                if new_shots:
                    for shot in new_shots:
                        shot_dict = self._convert_discovered_shot_to_dict(shot)
                        self._shot_model.add_shot(shot_dict)
                if removed_paths:
                    for path in removed_paths:
                        self._shot_model.remove_shot_by_path(str(path))

                self._status_bar.showMessage(f"Updated: +{len(new_shots)} -{len(removed_paths)} shots")
            except Exception as e:
                self._trigger_rescan()
        else:
            # Fall back to full rescan
            self._trigger_rescan()

    def _on_folder_observer_error(self, watch_id: str, error):
        """Handle folder observer error."""
        self._status_bar.showMessage(f"Folder watch error: {error}")

    def _on_folder_observer_overflow(self, watch_id: str):
        """Handle folder observer buffer overflow (T150)."""
        self._status_bar.showMessage("High filesystem activity - using polling mode")

    def _start_watching_folder(self, folder_path: Path):
        """
        Start watching a folder for changes (T152).

        Args:
            folder_path: Path to watch for changes
        """
        if not self._folder_observer:
            return

        # Stop watching previous folder if any
        self._stop_watching_folder()

        try:
            self._current_watch_id = self._folder_observer.start_watching(
                folder_path,
                on_changes=self._on_filesystem_changes
            )
            self._current_watched_path = folder_path
        except Exception as e:
            self._current_watch_id = None
            self._current_watched_path = None

    def _stop_watching_folder(self):
        """Stop watching the current folder."""
        if self._folder_observer and self._current_watch_id:
            self._folder_observer.stop_watching(self._current_watch_id)
            self._current_watch_id = None
            self._current_watched_path = None

    def _trigger_rescan(self):
        """
        Trigger a full rescan of the current watched folder (T155).

        This is called when schema changes or when incremental updates fail.
        """
        if self._current_watched_path:
            self._on_scan_folder_requested(str(self._current_watched_path))

    # ==================== SCHEMA CONFIGURATION (T153, T155) ====================

    def _show_schema_config(self):
        """
        Show schema configuration dialog (T153).

        Opens the dialog to configure folder schemas for shot discovery.
        """
        from .dialogs.schema_config_dialog import SchemaConfigDialog

        dialog = SchemaConfigDialog(db_service=self._db_service, parent=self)

        # Connect schema change signal (T155)
        dialog.schema_changed.connect(self._on_schema_changed)

        dialog.exec()

    def _on_schema_changed(self, schema_id: str):
        """
        Handle schema change - trigger rescan (T155).

        When the active schema changes, we need to:
        1. Reload the schema parser
        2. Rescan the current folder with the new schema

        Args:
            schema_id: ID of the newly active schema
        """
        if not self._db_service:
            return

        try:
            # Load the new schema from database
            from ..services.database.folder_schemas import FolderSchemaRepository
            repo = FolderSchemaRepository(self._db_service._connection)
            schema = repo.get_by_id(schema_id)

            if schema:
                # Update the schema parser
                self._schema_parser = FolderSchemaParser.from_dict(schema['config'])

                # Update the shot indexer with new parser
                self._shot_indexer = ShotIndexer(self._schema_parser)

                # Update discovery service with new indexer
                self._discovery_service = DiscoveryService(
                    shot_indexer=self._shot_indexer,
                    playblast_indexer=self._playblast_indexer,
                    lookdev_indexer=self._lookdev_indexer,
                )

                # Update scan controller with new discovery service
                if self._scan_controller:
                    self._scan_controller._discovery_service = self._discovery_service

                self._status_bar.showMessage(f"Schema changed to: {schema['name']}")

                # Trigger rescan if we're watching a folder (T155)
                self._trigger_rescan()

                # Emit via event bus
                self._event_bus.schema_changed.emit(schema_id)

        except Exception as e:
            self._status_bar.showMessage(f"Failed to reload schema: {e}")

    # ==================== EVENTS ====================

    def showEvent(self, event):
        """Handle window show - auto-restore last folder on first show."""
        super().showEvent(event)

        if not self._restored_last_folder:
            self._restored_last_folder = True
            last = Config.get_last_active_folder()
            if last:
                # Update toolbar
                self._header_toolbar.set_folder(str(last))
                # Restore folder tree structure
                self._folder_tree.set_root_folder(str(last))
                # Trigger scan for shots
                self._on_scan_folder_requested(str(last))

    def keyPressEvent(self, event):
        """Handle global key presses"""
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """Handle window close"""

        # Stop folder observer (T152)
        if hasattr(self, '_folder_observer') and self._folder_observer:
            self._folder_observer.stop_all()

        # Stop API server
        if hasattr(self, '_api_server') and self._api_server:
            self._api_server.stop()

        # Save settings
        self._save_settings()

        # Accept close
        event.accept()


__all__ = ['MainWindow']
