"""
FolderTree - Production folder navigation for Shot Library

Displays production folder structure for shot browsing.
Selecting a folder triggers shot discovery in that folder.

Shot Library specific:
- Browses production folder trees (read-only)
- No library organization (Archive, Trash, etc.)
- Folder selection triggers shot scanning
"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QMenu,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt, QDir, QSize
from PyQt6.QtGui import QIcon, QAction, QKeyEvent

import re
from ..config import Config
from ..events.event_bus import get_event_bus
from ..utils.icon_loader import IconLoader
from ..utils import colorize_white_svg
from ..themes.theme_manager import get_theme_manager
from ..themes.fonts import Fonts, get_font
from ..core.shot_version_parser import parse_shot_version


class FolderTree(QWidget):
    """
    Production folder tree for Shot Library.

    Allows browsing production folder structures and selecting
    folders to scan for shots.

    Layout:
        [Set Root Folder]
        Production Root
          ├─ Episode_01
          │   ├─ Seq_010
          │   │   ├─ Shot_0010
          │   │   └─ Shot_0020
          │   └─ Seq_020
          └─ Episode_02
    """

    # Signals
    folder_selected = pyqtSignal(int, str, bool)  # Compatibility: folder_id, folder_name, recursive
    scan_folder_requested = pyqtSignal(str)  # folder_path - trigger shot scan
    production_folder_selected = pyqtSignal(str)  # folder_path selected
    folder_clicked = pyqtSignal(str)  # folder_path when clicked (for folder filter)

    def __init__(self, parent=None, db_service=None, event_bus=None):
        super().__init__(parent)

        self._event_bus = event_bus or get_event_bus()
        self._theme_manager = get_theme_manager()
        self._root_path: Path = None

        # Filter state: "all", "blend", "mp4"
        self._file_filter = "all"
        # Latest only filter (shows only highest version of each file)
        self._show_latest_only = True  # Default ON to reduce confusion

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Create the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header row with label and filter buttons
        header_row = QWidget()
        header_row.setFixedHeight(36)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(8, 4, 4, 4)
        header_layout.setSpacing(8)

        # Current root label
        self._root_label = QLabel("No folder selected")
        self._root_label.setStyleSheet("color: #888; font-style: italic;")
        header_layout.addWidget(self._root_label)

        header_layout.addStretch()

        # Get theme icon color (use folder_icon_color for tree view)
        theme = self._theme_manager.get_current_theme()
        icon_color = theme.palette.folder_icon_color if theme else "#D4AF37"

        # Style for icon-only buttons (override global padding, sharp corners)
        icon_btn_style = """
            QPushButton {
                padding: 2px;
                min-height: 0px;
                min-width: 0px;
                border-radius: 0px;
            }
        """

        # Filter buttons (toggle style) with icons
        folder_icon = colorize_white_svg(IconLoader.get("folder_closed"), icon_color)
        self._filter_all_btn = QPushButton()
        self._filter_all_btn.setIcon(folder_icon)
        self._filter_all_btn.setIconSize(QSize(20, 20))
        self._filter_all_btn.setCheckable(True)
        self._filter_all_btn.setChecked(True)
        self._filter_all_btn.setFixedSize(28, 28)
        self._filter_all_btn.setStyleSheet(icon_btn_style)
        self._filter_all_btn.setToolTip("Show all files and folders")

        # Blend filter with icon
        blend_icon = colorize_white_svg(IconLoader.get("blend"), icon_color)
        self._filter_blend_btn = QPushButton()
        self._filter_blend_btn.setIcon(blend_icon)
        self._filter_blend_btn.setIconSize(QSize(20, 20))
        self._filter_blend_btn.setCheckable(True)
        self._filter_blend_btn.setFixedSize(28, 28)
        self._filter_blend_btn.setStyleSheet(icon_btn_style)
        self._filter_blend_btn.setToolTip("Show .blend files only")

        # MP4 filter with icon
        video_icon = colorize_white_svg(IconLoader.get("video"), icon_color)
        self._filter_mp4_btn = QPushButton()
        self._filter_mp4_btn.setIcon(video_icon)
        self._filter_mp4_btn.setIconSize(QSize(20, 20))
        self._filter_mp4_btn.setCheckable(True)
        self._filter_mp4_btn.setFixedSize(28, 28)
        self._filter_mp4_btn.setStyleSheet(icon_btn_style)
        self._filter_mp4_btn.setToolTip("Show .mp4 files only")

        # Latest only filter with icon
        latest_icon = colorize_white_svg(IconLoader.get("latest"), icon_color)
        self._filter_latest_btn = QPushButton()
        self._filter_latest_btn.setIcon(latest_icon)
        self._filter_latest_btn.setIconSize(QSize(20, 20))
        self._filter_latest_btn.setCheckable(True)
        self._filter_latest_btn.setChecked(True)  # Default ON to reduce confusion
        self._filter_latest_btn.setFixedSize(28, 28)
        self._filter_latest_btn.setStyleSheet(icon_btn_style)
        self._filter_latest_btn.setToolTip("Show latest versions only\n(highest version number)")

        header_layout.addWidget(self._filter_all_btn)
        header_layout.addWidget(self._filter_blend_btn)
        header_layout.addWidget(self._filter_mp4_btn)
        header_layout.addSpacing(4)
        header_layout.addWidget(self._filter_latest_btn)

        layout.addWidget(header_row)
        layout.addSpacing(4)

        # Tree widget for folder structure
        self._tree = QTreeWidget()
        self._tree.setFont(get_font(Fonts.FOLDER_TREE))
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setExpandsOnDoubleClick(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Style with branch lines using SVG files
        tree_icons = Config.ICONS_DIR / "tree"
        vline = str(tree_icons / "vline.svg").replace("\\", "/")
        branch_more = str(tree_icons / "branch-more.svg").replace("\\", "/")
        branch_end = str(tree_icons / "branch-end.svg").replace("\\", "/")

        # Chevron icons for expand/collapse indicators
        chevron_right = IconLoader.get("chevron_right")
        chevron_down = IconLoader.get("chevron_down")

        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: #1e1e1e;
                border: none;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 1px 4px;
                margin: 0px;
                border-radius: 0;
            }}
            QTreeWidget::item:selected {{
                background-color: #3a3a3a;
            }}
            QTreeWidget::item:hover {{
                background-color: #2a2a2a;
            }}
            /* Vertical line for items with siblings below */
            QTreeWidget::branch:has-siblings:!adjoins-item {{
                border-image: url({vline}) 0;
            }}
            /* T-junction: has siblings below and connects to item */
            QTreeWidget::branch:has-siblings:adjoins-item {{
                border-image: url({branch_more}) 0;
            }}
            /* L-corner: last child, no siblings below */
            QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {{
                border-image: url({branch_end}) 0;
            }}
            /* L-corner for parent nodes that are last child */
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:has-children:!has-siblings:open {{
                border-image: url({branch_end}) 0;
            }}
            /* T-junction for parent nodes with siblings */
            QTreeWidget::branch:has-children:has-siblings:closed,
            QTreeWidget::branch:has-children:has-siblings:open {{
                border-image: url({branch_more}) 0;
            }}
            /* Chevron icons for expandable folders */
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:has-children:has-siblings:closed {{
                image: url({chevron_right});
            }}
            QTreeWidget::branch:has-children:!has-siblings:open,
            QTreeWidget::branch:has-children:has-siblings:open {{
                image: url({chevron_down});
            }}
        """)

        layout.addWidget(self._tree)

    def _connect_signals(self):
        """Connect internal signals."""
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        # Filter button connections
        self._filter_all_btn.clicked.connect(lambda: self._set_filter("all"))
        self._filter_blend_btn.clicked.connect(lambda: self._set_filter("blend"))
        self._filter_mp4_btn.clicked.connect(lambda: self._set_filter("mp4"))
        self._filter_latest_btn.clicked.connect(self._toggle_latest_filter)

    def _set_filter(self, filter_type: str):
        """Set the file filter and refresh the tree."""
        self._file_filter = filter_type

        # Update button states (radio-button behavior for file type)
        self._filter_all_btn.setChecked(filter_type == "all")
        self._filter_blend_btn.setChecked(filter_type == "blend")
        self._filter_mp4_btn.setChecked(filter_type == "mp4")

        # Refresh tree with new filter
        self._populate_tree()

    def _toggle_latest_filter(self):
        """Toggle the latest-only filter."""
        self._show_latest_only = self._filter_latest_btn.isChecked()
        # Refresh tree with new filter
        self._populate_tree()

    def set_root_folder(self, folder_path: str):
        """
        Set the production root folder and populate the tree.

        This only updates the tree display - it does NOT trigger a scan.
        Scanning is handled by the header toolbar dropdown.

        Args:
            folder_path: Path to the production root folder
        """
        self._root_path = Path(folder_path)

        # Update label
        self._root_label.setText(self._root_path.name)
        self._root_label.setStyleSheet("color: #fff; font-weight: bold;")
        self._root_label.setToolTip(str(self._root_path))

        # Populate tree (display only, no scan)
        self._populate_tree()

    def _populate_tree(self):
        """Populate the tree with folder structure like Windows Explorer."""
        self._tree.clear()

        if not self._root_path or not self._root_path.exists():
            return

        # Create root item
        root_item = QTreeWidgetItem([self._root_path.name])
        root_item.setData(0, Qt.ItemDataRole.UserRole, str(self._root_path))
        root_item.setIcon(0, self._get_folder_icon())

        # For MP4 filter with "latest only", collect all MP4s first then filter globally
        if self._file_filter == "mp4" and self._show_latest_only:
            self._add_mp4s_filtered_globally(root_item, self._root_path)
        else:
            # Add subfolders and files normally
            # Note: depth 7 needed for PlayBlast/{blend_stem}/ subfolder structure
            self._add_children(root_item, self._root_path, max_depth=7)

        self._tree.addTopLevelItem(root_item)

        # Expand all items after adding to tree (setExpanded must happen after item is in tree)
        self._tree.expandAll()

    def _add_mp4s_filtered_globally(self, parent_item: QTreeWidgetItem, root_path: Path):
        """
        Collect all MP4s from the tree, filter globally for latest, then add to tree.

        This ensures "latest" shows only the latest shot version's latest playblast,
        not the latest from each subfolder.
        """
        # Collect all MP4 files recursively, excluding _archive folders
        all_mp4s = [f for f in root_path.rglob('*.mp4')
                    if '_archive' not in [p.name.lower() for p in f.parents]]

        # Also filter out files from old version folders
        all_mp4s = self._filter_files_from_old_version_folders(all_mp4s)

        # Filter to latest versions globally
        filtered_mp4s = self._filter_latest_versions(all_mp4s)

        # Sort by name
        filtered_mp4s = sorted(filtered_mp4s, key=lambda x: x.name.lower())

        # Add each MP4 directly under root
        for mp4_file in filtered_mp4s:
            item = QTreeWidgetItem([mp4_file.name])
            item.setData(0, Qt.ItemDataRole.UserRole, str(mp4_file))
            item.setIcon(0, self._get_video_icon())
            item.setFont(0, get_font(Fonts.FOLDER_TREE_FILE))
            parent_item.addChild(item)

    def _add_children(self, parent_item: QTreeWidgetItem, folder_path: Path, max_depth: int, current_depth: int = 0):
        """
        Recursively add folders and files to the tree (like Windows Explorer).

        Shows all folders and relevant files (.blend, .mp4) - no hiding.

        Args:
            parent_item: Parent tree item
            folder_path: Path to scan
            max_depth: Maximum recursion depth
            current_depth: Current depth level
        """
        if current_depth >= max_depth:
            return

        try:
            # Get all items, separate folders and files
            items = list(folder_path.iterdir())

            # Folders first, then files (like Windows Explorer)
            # Always skip _archive folders - they clutter the view
            folders = sorted([d for d in items if d.is_dir()
                             and not d.name.startswith('.')
                             and d.name.lower() != '_archive'],
                           key=lambda x: x.name.lower())

            # Filter version folders when "Latest Only" is enabled
            if self._show_latest_only:
                folders = self._filter_latest_version_folders(folders)

            # Get files based on filter
            blend_files = []
            mp4_files = []

            if self._file_filter in ("all", "blend"):
                blend_files = sorted([f for f in items if f.is_file() and f.suffix.lower() == '.blend'],
                                    key=lambda x: x.name.lower())
                if self._show_latest_only:
                    blend_files = self._filter_latest_versions(blend_files)

            if self._file_filter in ("all", "mp4"):
                mp4_files = sorted([f for f in items if f.is_file() and f.suffix.lower() == '.mp4'],
                                  key=lambda x: x.name.lower())
                # Note: When mp4 filter + show_latest_only, filtering happens globally
                # in _add_mp4s_filtered_globally(). This path is only used for "all" filter.

            # Only show folders when filter is "all"
            if self._file_filter == "all":
                for folder in folders:
                    item = QTreeWidgetItem([folder.name])
                    item.setData(0, Qt.ItemDataRole.UserRole, str(folder))
                    item.setIcon(0, self._get_folder_icon())

                    parent_item.addChild(item)

                    # Recurse into subdirectories
                    self._add_children(item, folder, max_depth, current_depth + 1)
            else:
                # When filtering, recurse into folders but don't show them
                # Only add files found in subfolders directly to parent
                for folder in folders:
                    self._add_children(parent_item, folder, max_depth, current_depth + 1)

            # Add .blend files with Blender icon
            for blend_file in blend_files:
                item = QTreeWidgetItem([blend_file.name])
                item.setData(0, Qt.ItemDataRole.UserRole, str(blend_file))
                item.setIcon(0, self._get_blender_icon())
                # Make files italic to distinguish from folders
                item.setFont(0, get_font(Fonts.FOLDER_TREE_FILE))
                parent_item.addChild(item)

            # Add .mp4 files with video icon
            for mp4_file in mp4_files:
                item = QTreeWidgetItem([mp4_file.name])
                item.setData(0, Qt.ItemDataRole.UserRole, str(mp4_file))
                item.setIcon(0, self._get_video_icon())
                # Make files italic to distinguish from folders
                item.setFont(0, get_font(Fonts.FOLDER_TREE_FILE))
                parent_item.addChild(item)

        except PermissionError:
            pass  # Skip folders we can't read

    def _filter_latest_versions(self, files: list) -> list:
        """
        Filter a list of files to show only the latest version of each.

        Handles double-version naming like: SH0010_v001_v003.mp4
        (shot version v001, playblast version v003)

        For "latest of latest":
        1. Group by base shot name (SH0010)
        2. Find latest shot version (v003)
        3. Among those, find latest playblast version (v004)

        Args:
            files: List of Path objects

        Returns:
            Filtered list with only latest versions
        """
        if not files:
            return files

        # Group files by base shot name, tracking both version levels
        groups = {}
        for file_path in files:
            stem = file_path.stem

            # Try to parse double version: base_v###_v### pattern
            # E.g., "SH0010_v001_v003" -> base="SH0010", shot_ver=1, pb_ver=3
            double_ver_match = re.match(r'^(.+?)_[vV](\d+)_[vV](\d+)$', stem)

            if double_ver_match:
                base_name = double_ver_match.group(1)
                shot_version = int(double_ver_match.group(2))
                playblast_version = int(double_ver_match.group(3))

                if base_name not in groups:
                    groups[base_name] = []
                groups[base_name].append((file_path, shot_version, playblast_version))
            else:
                # Fall back to single version parsing
                version_info = parse_shot_version(stem)
                base_name = version_info.base_name
                version = version_info.version

                if base_name not in groups:
                    groups[base_name] = []
                # Use version as both shot and playblast version for single-version files
                groups[base_name].append((file_path, version or 0, version or 0))

        # Select latest of latest from each group
        latest_files = []
        for base_name, file_versions in groups.items():
            if not file_versions:
                continue

            # Find the highest shot version
            max_shot_ver = max(fv[1] for fv in file_versions)

            # Among files with highest shot version, find highest playblast version
            latest_shot_files = [(f, sv, pv) for f, sv, pv in file_versions if sv == max_shot_ver]
            latest = max(latest_shot_files, key=lambda x: x[2])
            latest_files.append(latest[0])

        # Sort by name
        return sorted(latest_files, key=lambda x: x.name.lower())

    def _filter_latest_version_folders(self, folders: list) -> list:
        """
        Filter folders to show only latest version when _show_latest_only is True.

        Detects version patterns in folder names (e.g., SH0010_v001, SH0010_v002)
        and keeps only the highest version per base name.

        Args:
            folders: List of Path objects representing folders

        Returns:
            Filtered list with only latest version folders (and all non-versioned folders)
        """
        if not folders:
            return folders

        # Group folders by base name
        groups = {}
        non_versioned = []

        for folder in folders:
            version_info = parse_shot_version(folder.name)
            if version_info.is_versioned:
                base = version_info.base_name
                if base not in groups:
                    groups[base] = []
                groups[base].append((folder, version_info.version))
            else:
                non_versioned.append(folder)

        # Keep only latest version per group
        latest_folders = list(non_versioned)
        for base_name, folder_versions in groups.items():
            # Sort by version descending, keep highest
            folder_versions.sort(key=lambda x: x[1], reverse=True)
            latest_folders.append(folder_versions[0][0])

        return sorted(latest_folders, key=lambda x: x.name.lower())

    def _filter_files_from_old_version_folders(self, files: list) -> list:
        """
        Filter out files that are inside old version folders.

        For each file, check if any of its parent folders is a versioned folder.
        If so, only keep files from the latest version folder in each group.

        Args:
            files: List of Path objects

        Returns:
            Filtered list excluding files from old version folders
        """
        if not files:
            return files

        # First, collect all versioned parent folders from all files
        # Group them by (grandparent_path, base_name) to find latest per group
        folder_groups = {}  # (grandparent, base_name) -> [(folder_name, version)]

        for file_path in files:
            # Check each parent folder for version pattern
            for parent in file_path.parents:
                version_info = parse_shot_version(parent.name)
                if version_info.is_versioned:
                    grandparent = parent.parent
                    key = (str(grandparent), version_info.base_name)
                    if key not in folder_groups:
                        folder_groups[key] = set()
                    folder_groups[key].add((parent.name, version_info.version))

        # Determine which folder names are "latest" for each group
        latest_folder_names = set()
        for key, folder_versions in folder_groups.items():
            # Find highest version
            folder_versions_list = list(folder_versions)
            folder_versions_list.sort(key=lambda x: x[1], reverse=True)
            latest_folder_names.add(folder_versions_list[0][0])

        # Filter files: keep if no versioned parent, or if versioned parent is latest
        result = []
        for file_path in files:
            keep_file = True
            for parent in file_path.parents:
                version_info = parse_shot_version(parent.name)
                if version_info.is_versioned:
                    # This parent is versioned - check if it's the latest
                    if parent.name not in latest_folder_names:
                        keep_file = False
                        break

            if keep_file:
                result.append(file_path)

        return result

    def _get_folder_icon(self) -> QIcon:
        """Get the folder icon."""
        try:
            icon_path = IconLoader.get("folder_closed")
            if icon_path:
                return QIcon(icon_path)
        except Exception:
            pass
        return QIcon()

    def _get_blender_icon(self) -> QIcon:
        """Get icon for .blend files."""
        try:
            icon_path = IconLoader.get("apply_to_blender")
            if icon_path:
                return QIcon(icon_path)
        except Exception:
            pass
        return QIcon()

    def _get_video_icon(self) -> QIcon:
        """Get icon for .mp4 video files."""
        try:
            icon_path = IconLoader.get("play")
            if icon_path:
                return QIcon(icon_path)
        except Exception:
            pass
        return QIcon()

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click — emit folder path for filtering."""
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if folder_path:
            self.folder_clicked.emit(folder_path)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle folder double-click - expand/collapse."""
        item.setExpanded(not item.isExpanded())

    def _on_context_menu(self, pos):
        """Show context menu for folder operations."""
        item = self._tree.itemAt(pos)
        if not item:
            return

        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_path:
            return

        menu = QMenu(self)

        # Scan this folder
        scan_action = QAction("Scan for Shots", self)
        scan_action.triggered.connect(lambda: self.scan_folder_requested.emit(folder_path))
        menu.addAction(scan_action)

        # Refresh tree
        refresh_action = QAction("Refresh Tree", self)
        refresh_action.triggered.connect(self._populate_tree)
        menu.addAction(refresh_action)

        menu.addSeparator()

        # Open in explorer
        open_action = QAction("Open in Explorer", self)
        open_action.triggered.connect(lambda: self._open_in_explorer(folder_path))
        menu.addAction(open_action)

        menu.exec(self._tree.mapToGlobal(pos))

    def _open_in_explorer(self, folder_path: str):
        """Open folder in system file explorer."""
        import subprocess
        import sys

        path = Path(folder_path)
        if not path.exists():
            return

        if sys.platform == 'win32':
            subprocess.run(['explorer', str(path)])
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(path)])
        else:
            subprocess.run(['xdg-open', str(path)])

    def refresh(self):
        """Refresh the folder tree."""
        if self._root_path:
            self._populate_tree()

    def get_root_path(self) -> Path:
        """Get the current root folder path."""
        return self._root_path

    def selectedItems(self):
        """Return selected tree items."""
        return self._tree.selectedItems()

    def keyPressEvent(self, a0):
        """Handle keyboard shortcuts for expand/collapse."""
        if a0 is None:
            return

        modifiers = a0.modifiers()
        key = a0.key()

        # Shift + Plus or Numpad Plus: Expand one level
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_Plus or key == Qt.Key.Key_Equal:
                self.expand_one_level()
                a0.accept()
                return
            # Shift + Minus: Collapse one level
            elif key == Qt.Key.Key_Minus or key == Qt.Key.Key_Underscore:
                self.collapse_one_level()
                a0.accept()
                return

        # Numpad Plus/Minus without shift
        if key == Qt.Key.Key_Plus:
            self.expand_one_level()
            a0.accept()
            return
        elif key == Qt.Key.Key_Minus:
            self.collapse_one_level()
            a0.accept()
            return

        super().keyPressEvent(a0)

    def expand_all(self):
        """Expand all folders in the tree (legacy - kept for compatibility)."""
        self._tree.expandAll()

    def expand_one_level(self):
        """
        Expand one level deeper in the tree (like Blender outliner).

        Finds the deepest currently expanded level and expands all items
        at that level that have children.
        """
        root_item = self._tree.topLevelItem(0)
        if not root_item:
            return

        # Ensure root is expanded
        if not root_item.isExpanded():
            root_item.setExpanded(True)
            return

        # Find items at the deepest expanded level that have collapsed children
        items_to_expand = self._find_deepest_expandable_items(root_item)

        if items_to_expand:
            for item in items_to_expand:
                item.setExpanded(True)

    def _find_deepest_expandable_items(self, root_item: QTreeWidgetItem) -> list:
        """
        Find all items at the deepest expanded level that can be expanded.

        Returns items that are:
        - Currently expanded (visible)
        - Have children that are collapsed
        """
        # BFS to find deepest level with expandable items
        from collections import deque

        # Queue holds (item, depth)
        queue = deque([(root_item, 0)])
        deepest_expandable = []
        deepest_level = -1

        while queue:
            item, depth = queue.popleft()

            if item.isExpanded():
                has_collapsed_children = False
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child:
                        if child.childCount() > 0:  # Has grandchildren
                            if not child.isExpanded():
                                has_collapsed_children = True
                            else:
                                # Child is expanded, add to queue to check deeper
                                queue.append((child, depth + 1))

                # If this expanded item has collapsed children with grandchildren
                if has_collapsed_children:
                    if depth > deepest_level:
                        deepest_level = depth
                        deepest_expandable = []
                    if depth == deepest_level:
                        # Collect the collapsed children (not the parent)
                        for i in range(item.childCount()):
                            child = item.child(i)
                            if child and child.childCount() > 0 and not child.isExpanded():
                                deepest_expandable.append(child)

        return deepest_expandable

    def collapse_to_first_level(self):
        """
        Collapse all folders except immediate children of root (legacy).
        """
        root_item = self._tree.topLevelItem(0)
        if not root_item:
            return

        # Keep root expanded
        root_item.setExpanded(True)

        # Collapse all children of root (and their descendants)
        for i in range(root_item.childCount()):
            child = root_item.child(i)
            if child:
                self._collapse_recursive(child)

    def collapse_one_level(self):
        """
        Collapse one level in the tree (like Blender outliner).

        Finds the deepest currently expanded level and collapses all items
        at that level.
        """
        root_item = self._tree.topLevelItem(0)
        if not root_item:
            return

        # Find items at the deepest expanded level
        items_to_collapse = self._find_deepest_expanded_items(root_item)

        if items_to_collapse:
            for item in items_to_collapse:
                item.setExpanded(False)

    def _find_deepest_expanded_items(self, root_item: QTreeWidgetItem) -> list:
        """
        Find all expanded items at the deepest level.

        Returns items that are:
        - Currently expanded
        - At the deepest level of expansion
        - Not the root item (root stays expanded)
        """
        from collections import deque

        # Queue holds (item, depth)
        queue = deque([(root_item, 0)])
        deepest_expanded = []
        deepest_level = -1

        while queue:
            item, depth = queue.popleft()

            if item.isExpanded():
                has_expanded_children = False
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child and child.isExpanded():
                        has_expanded_children = True
                        queue.append((child, depth + 1))

                # If no expanded children, this is at the deepest level
                if not has_expanded_children and item != root_item:
                    if depth > deepest_level:
                        deepest_level = depth
                        deepest_expanded = []
                    if depth == deepest_level:
                        deepest_expanded.append(item)

        return deepest_expanded

    def _collapse_recursive(self, item: QTreeWidgetItem):
        """Recursively collapse an item and all its descendants."""
        item.setExpanded(False)
        for i in range(item.childCount()):
            child = item.child(i)
            if child:
                self._collapse_recursive(child)


__all__ = ['FolderTree']
