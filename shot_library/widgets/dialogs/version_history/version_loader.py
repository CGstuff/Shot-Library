"""
Version loader for VersionHistoryDialog.

Handles loading version data from database and creating tree items.
"""

from typing import TYPE_CHECKING, Optional, List, Dict, Any, Callable, Tuple

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QTreeWidgetItem

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTreeWidget
    from ....services.database_service import DatabaseService


class VersionLoader:
    """
    Handles loading and displaying version history in a tree widget.

    Supports both hierarchical (shot versions with playblasts) and flat modes.
    """

    def __init__(
        self,
        tree: 'QTreeWidget',
        db_service: 'DatabaseService',
        get_themed_icon: Callable[[str], Any],
        load_thumbnail_async: Callable[[str, str, QTreeWidgetItem], None]
    ):
        """
        Initialize version loader.

        Args:
            tree: Tree widget to populate
            db_service: Database service for queries
            get_themed_icon: Callback to get themed icons
            load_thumbnail_async: Callback to load thumbnails asynchronously
        """
        self._tree = tree
        self._db = db_service
        self._get_icon = get_themed_icon
        self._load_thumbnail = load_thumbnail_async

        # State
        self._versions: List[Dict] = []
        self._hierarchy: Dict[str, Any] = {}

    @property
    def versions(self) -> List[Dict]:
        """Get flat list of all versions."""
        return self._versions

    @property
    def hierarchy(self) -> Dict[str, Any]:
        """Get hierarchical version data."""
        return self._hierarchy

    def load_versions(self, version_group_id: str) -> Tuple[str, Optional[QTreeWidgetItem]]:
        """
        Load hierarchical version history.

        Args:
            version_group_id: Version group ID to load

        Returns:
            Tuple of (base_name, latest_playblast_item)
        """
        self._hierarchy = self._db.get_hierarchical_version_history(version_group_id)
        shot_versions = self._hierarchy.get('shot_versions', [])
        base_name = self._hierarchy.get('base_shot_name', 'Unknown')

        if not shot_versions:
            return self.load_versions_flat(version_group_id)

        has_multiple = len(shot_versions) > 1
        self._tree.clear()
        self._versions = []
        latest_item = None

        if has_multiple:
            latest_item = self._load_hierarchical(shot_versions)
        else:
            latest_item = self._load_single_shot(shot_versions[0])

        return base_name, latest_item

    def load_versions_flat(self, version_group_id: str) -> Tuple[str, Optional[QTreeWidgetItem]]:
        """
        Load flat playblast list (fallback mode).

        Returns:
            Tuple of (base_name, latest_item)
        """
        self._versions = self._db.get_version_history(version_group_id)

        if not self._versions:
            return "No versions found", None

        self._tree.clear()
        latest_item = None

        for version in self._versions:
            resolved = self._db.animations.resolve_preview_file(version)
            if resolved:
                version['preview_path'] = str(resolved)

            is_latest = version.get('is_latest', 0)
            item = self._create_playblast_item(version, is_latest)
            self._tree.addTopLevelItem(item)

            if is_latest:
                latest_item = item

        base_name = self._versions[0].get('name', 'Unknown') if self._versions else 'Unknown'
        return base_name, latest_item

    def load_lookdev_versions(self, version_group_id: str) -> Tuple[str, Optional[QTreeWidgetItem]]:
        """
        Load lookdev versions.

        Returns:
            Tuple of (base_name, latest_item)
        """
        lookdevs = self._db.get_lookdev_versions(version_group_id)

        if not lookdevs:
            return "No lookdev versions", None

        self._tree.clear()
        latest_item = None

        for ld in lookdevs:
            item = self._create_lookdev_item(ld)
            self._tree.addTopLevelItem(item)

            if ld.is_latest:
                latest_item = item

        base_name = lookdevs[0].animation_name if lookdevs else 'Unknown'
        return base_name, latest_item

    def _load_hierarchical(self, shot_versions: List[Dict]) -> Optional[QTreeWidgetItem]:
        """Load hierarchical shot versions with playblast children."""
        latest_item = None

        for shot_ver in shot_versions:
            shot_id = shot_ver.get('shot_id')
            shot_name = shot_ver.get('shot_name', 'Unknown')
            shot_version_label = shot_ver.get('shot_version_label', 'v001')
            is_latest = shot_ver.get('is_latest_shot_version', False)
            status = shot_ver.get('status', 'WIP')
            playblasts = shot_ver.get('playblasts', [])

            # Create parent item
            parent = QTreeWidgetItem()

            blend_icon = self._get_icon("blend")
            if blend_icon and not blend_icon.isNull():
                parent.setIcon(0, blend_icon)

            label = f"Shot {shot_version_label}"
            if is_latest:
                label += " [LATEST]"

            parent.setText(1, label)
            parent.setText(2, status.upper())
            parent.setText(3, f"{len(playblasts)} pb")
            parent.setSizeHint(0, QSize(24, 24))

            parent.setData(0, Qt.ItemDataRole.UserRole, {
                'type': 'shot_version',
                'shot_id': shot_id,
                'shot_name': shot_name,
                'shot_version_label': shot_version_label,
                'is_latest_shot_version': is_latest,
            })

            font = parent.font(1)
            font.setBold(True)
            parent.setFont(1, font)

            if is_latest:
                parent.setForeground(1, QBrush(QColor("#4CAF50")))

            self._tree.addTopLevelItem(parent)

            # Add playblast children
            for pb in playblasts:
                version = self._map_playblast_to_version(pb, shot_name, status)
                resolved = self._db.animations.resolve_preview_file(version)
                if resolved:
                    version['preview_path'] = str(resolved)
                self._versions.append(version)

                child = self._create_playblast_item(version, pb.get('is_latest', False))
                parent.addChild(child)

                if is_latest and pb.get('is_latest', False):
                    latest_item = child

            if is_latest:
                parent.setExpanded(True)

        return latest_item

    def _load_single_shot(self, shot_ver: Dict) -> Optional[QTreeWidgetItem]:
        """Load single shot version (flat playblast list)."""
        shot_name = shot_ver.get('shot_name', 'Unknown')
        status = shot_ver.get('status', 'WIP')
        playblasts = shot_ver.get('playblasts', [])
        latest_item = None

        for pb in playblasts:
            version = self._map_playblast_to_version(pb, shot_name, status)
            resolved = self._db.animations.resolve_preview_file(version)
            if resolved:
                version['preview_path'] = str(resolved)
            self._versions.append(version)

            item = self._create_playblast_item(version, pb.get('is_latest', False))
            self._tree.addTopLevelItem(item)

            if pb.get('is_latest', False):
                latest_item = item

        return latest_item

    def _map_playblast_to_version(self, pb: Dict, shot_name: str, status: str) -> Dict:
        """Map playblast data to version dict for compatibility."""
        return {
            'uuid': pb.get('uuid'),
            'name': shot_name,
            'version_label': pb.get('version_label', 'v001'),
            'status': status,
            'is_latest': pb.get('is_latest', 0),
            'preview_path': pb.get('preview_path', ''),
            'thumbnail_path': pb.get('thumbnail_path', ''),
            'fps': pb.get('fps', 24),
            'frame_count': pb.get('frame_count', 0),
            'frame_start': pb.get('frame_start', 1),
            'frame_end': pb.get('frame_end', 100),
            'created_at': pb.get('created_at', ''),
            'notes': pb.get('notes', ''),
        }

    def _create_playblast_item(self, version: Dict, is_latest: bool) -> QTreeWidgetItem:
        """Create a tree item for a playblast version."""
        item = QTreeWidgetItem()

        uuid = version.get('uuid', '')
        version_label = version.get('version_label', 'v001')
        thumbnail_path = version.get('thumbnail_path', '')

        # Thumbnail placeholder
        item.setSizeHint(0, QSize(64, 48))

        # Version label with latest indicator
        label = version_label
        if is_latest:
            label += " ★"
        item.setText(1, label)

        # Frame range
        frame_start = version.get('frame_start', 1)
        frame_end = version.get('frame_end', 100)
        item.setText(3, f"{frame_start}-{frame_end}")

        # Store data
        item.setData(0, Qt.ItemDataRole.UserRole, {
            'type': 'playblast',
            'uuid': uuid,
            'version': version,
        })

        # Style latest
        if is_latest:
            item.setForeground(1, QBrush(QColor("#4CAF50")))

        # Load thumbnail async
        if thumbnail_path and uuid:
            self._load_thumbnail(uuid, thumbnail_path, item)

        return item

    def _create_lookdev_item(self, lookdev) -> QTreeWidgetItem:
        """Create a tree item for a lookdev version."""
        item = QTreeWidgetItem()

        version_label = f"v{lookdev.version:03d}"
        item.setSizeHint(0, QSize(64, 48))

        label = version_label
        if lookdev.is_latest:
            label += " ★"
        item.setText(1, label)

        status = lookdev.status or 'WIP'
        item.setText(2, status.upper())

        item.setData(0, Qt.ItemDataRole.UserRole, {
            'type': 'lookdev',
            'lookdev': lookdev,
            'uuid': f"lookdev_{lookdev.version}",
        })

        if lookdev.is_latest:
            item.setForeground(1, QBrush(QColor("#4CAF50")))

        # Load thumbnail
        if lookdev.thumbnail_path:
            self._load_thumbnail(f"lookdev_{lookdev.version}", lookdev.thumbnail_path, item)

        return item


__all__ = ['VersionLoader']
