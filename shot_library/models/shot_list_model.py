"""
ShotListModel - Qt Model for shot data

Pattern: Model/View architecture with QAbstractListModel
Adapted from: AnimationListModel for shot domain
"""

import time
from enum import IntEnum
from pathlib import Path
from typing import List, Dict, Any, Optional
from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, QMimeData, QByteArray
)

from ..config import Config
from ..services.database_service import get_database_service


class ShotRole(IntEnum):
    """Custom Qt roles for shot data"""

    # Required fields
    UUIDRole = Qt.ItemDataRole.UserRole + 1
    NameRole = Qt.ItemDataRole.UserRole + 2
    FolderPathRole = Qt.ItemDataRole.UserRole + 3
    BlendFileRole = Qt.ItemDataRole.UserRole + 4

    # Shot identity (from parsing)
    EpisodeNumRole = Qt.ItemDataRole.UserRole + 10
    SequenceNumRole = Qt.ItemDataRole.UserRole + 11
    SceneNumRole = Qt.ItemDataRole.UserRole + 12
    ShotNumRole = Qt.ItemDataRole.UserRole + 13
    EditorialOrderRole = Qt.ItemDataRole.UserRole + 14

    # Production status
    StatusRole = Qt.ItemDataRole.UserRole + 20
    ParseWarningRole = Qt.ItemDataRole.UserRole + 21

    # Playblast info
    LatestPlayblastPathRole = Qt.ItemDataRole.UserRole + 30
    LatestPlayblastVersionRole = Qt.ItemDataRole.UserRole + 31
    PlayblastCountRole = Qt.ItemDataRole.UserRole + 32
    HasPlayblastRole = Qt.ItemDataRole.UserRole + 33

    # Preview paths (for thumbnails/video)
    ThumbnailPathRole = Qt.ItemDataRole.UserRole + 40
    PreviewPathRole = Qt.ItemDataRole.UserRole + 41

    # Timing (from latest playblast)
    DurationMsRole = Qt.ItemDataRole.UserRole + 50
    FPSRole = Qt.ItemDataRole.UserRole + 51
    FrameCountRole = Qt.ItemDataRole.UserRole + 52
    WidthRole = Qt.ItemDataRole.UserRole + 53
    HeightRole = Qt.ItemDataRole.UserRole + 54

    # Timestamps
    CreatedDateRole = Qt.ItemDataRole.UserRole + 60
    ModifiedDateRole = Qt.ItemDataRole.UserRole + 61

    # Review notes indicators
    HasNotesRole = Qt.ItemDataRole.UserRole + 70
    UnresolvedCommentCountRole = Qt.ItemDataRole.UserRole + 71

    # Shot version grouping roles
    BaseShotNameRole = Qt.ItemDataRole.UserRole + 80
    ShotVersionRole = Qt.ItemDataRole.UserRole + 81
    VersionGroupIdRole = Qt.ItemDataRole.UserRole + 82
    IsLatestShotVersionRole = Qt.ItemDataRole.UserRole + 83
    VersionCountRole = Qt.ItemDataRole.UserRole + 84

    # Complete data dict
    ShotDataRole = Qt.ItemDataRole.UserRole + 100

    # Lookdev info (parallel to playblast)
    LatestLookdevPathRole = Qt.ItemDataRole.UserRole + 130
    LatestLookdevVersionRole = Qt.ItemDataRole.UserRole + 131
    LookdevCountRole = Qt.ItemDataRole.UserRole + 132
    HasLookdevRole = Qt.ItemDataRole.UserRole + 133

    # Preview mode toggle (playblast or lookdev)
    PreviewModeRole = Qt.ItemDataRole.UserRole + 140

    # Task/Assignment roles (from Pipeline Control integration)
    AssignedToRole = Qt.ItemDataRole.UserRole + 150
    AssignedToNameRole = Qt.ItemDataRole.UserRole + 151
    TaskPriorityRole = Qt.ItemDataRole.UserRole + 152
    TaskDueDateRole = Qt.ItemDataRole.UserRole + 153
    TaskStatusRole = Qt.ItemDataRole.UserRole + 154
    TaskIdRole = Qt.ItemDataRole.UserRole + 155

    # Multi-camera reference file roles (v9)
    ShotRoleRole = Qt.ItemDataRole.UserRole + 160  # 'standalone', 'master', or 'view'
    MasterShotIdRole = Qt.ItemDataRole.UserRole + 161  # For views, ID of master shot
    ViewCountRole = Qt.ItemDataRole.UserRole + 162  # For masters, number of views
    HasViewsRole = Qt.ItemDataRole.UserRole + 163  # True if shot is master with views
    CombinedPlayblastPathRole = Qt.ItemDataRole.UserRole + 164  # Path to stitched playblast
    CombinedLookdevPathRole = Qt.ItemDataRole.UserRole + 165  # Path to stitched lookdev
    ViewNameRole = Qt.ItemDataRole.UserRole + 166  # For views, e.g., "ref01", "cam02"

    # Render info (folder-based versioning with proxy)
    RenderProxyPathRole = Qt.ItemDataRole.UserRole + 170  # Path to render proxy MP4
    HasRenderRole = Qt.ItemDataRole.UserRole + 171  # True if has render with proxy


class ShotListModel(QAbstractListModel):
    """
    Qt model for shot list

    Features:
    - Lightweight data storage
    - Custom Qt roles for all shot fields
    - Sparse data access with .get()
    - Performance logging
    - **Editorial order preservation**: Shots are stored and returned in editorial order
    - No drag & drop reordering (shots have fixed editorial order)

    Usage:
        model = ShotListModel()
        model.set_shots(shot_list)  # shots must be pre-sorted by editorial_order
        view.setModel(model)
    """

    def __init__(self, parent=None, db_service=None):
        super().__init__(parent)
        self._shots: List[Dict[str, Any]] = []
        self._db_service = db_service  # Lazy init - use get_db_service()

        # Performance monitoring
        self._load_time: float = 0.0
        self._data_access_count: int = 0

        # Cache for shots with notes (for badge display)
        self._shots_with_notes: set = set()
        self._unresolved_counts: dict = {}

        # uuid → row index, built lazily on first lookup, invalidated on mutation.
        # Avoids O(n) scan per thumbnail-load signal on large libraries.
        self._uuid_to_row: Optional[Dict[str, int]] = None

    def _invalidate_uuid_index(self):
        """Drop the uuid→row cache so the next get_row_for_uuid() rebuilds it."""
        self._uuid_to_row = None

    def get_row_for_uuid(self, uuid: str) -> int:
        """Return source row for a shot uuid, or -1 if not present. O(1) after first call."""
        if self._uuid_to_row is None:
            self._uuid_to_row = {}
            for i, shot in enumerate(self._shots):
                key = shot.get('uuid') or shot.get('id')
                if key:
                    self._uuid_to_row[key] = i
        return self._uuid_to_row.get(uuid, -1)

    def _get_db_service(self):
        """Get database service (lazy initialization)"""
        if self._db_service is None:
            self._db_service = get_database_service()
        return self._db_service

    def set_shots(self, shots: List[Dict[str, Any]]):
        """
        Set shot data.

        IMPORTANT: Shots should be pre-sorted by editorial_order.
        The model preserves this order - no resorting is done.

        Args:
            shots: List of shot dicts from database, already sorted by editorial_order
        """
        start_time = time.time()

        # Enrich master shots with view counts
        self._enrich_with_view_counts(shots)

        self.beginResetModel()
        self._shots = shots
        self._invalidate_uuid_index()
        self.endResetModel()

        self._load_time = (time.time() - start_time) * 1000  # Convert to ms

        # Refresh notes cache
        self.refresh_notes_cache()

    def _enrich_with_view_counts(self, shots: List[Dict[str, Any]]):
        """
        Enrich master shots with view count data.

        For each master shot, fetches the count of attached views
        and adds 'view_count' to the shot dict.

        Args:
            shots: List of shot dicts (modified in place)
        """
        db_service = self._get_db_service()

        for shot in shots:
            shot_role = shot.get('shot_role', 'standalone')
            if shot_role == 'master':
                shot_id = shot.get('id')
                if shot_id:
                    view_count = db_service.shots.get_view_count(shot_id)
                    shot['view_count'] = view_count

    def refresh_notes_cache(self, emit_change: bool = False):
        """
        Refresh the cache of shots with notes/drawovers and unresolved counts.

        Args:
            emit_change: If True, emit dataChanged for all items to trigger repaint
        """
        # TODO: Integrate with ReviewService when available
        try:
            # Placeholder for review service integration
            self._shots_with_notes = set()
            self._unresolved_counts = {}
        except Exception:
            self._shots_with_notes = set()
            self._unresolved_counts = {}

        if emit_change and len(self._shots) > 0:
            # Notify view that data changed (for badge updates)
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._shots) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right)

    def append_shot(self, shot: Dict[str, Any]):
        """
        Append single shot to model.

        Note: Caller is responsible for maintaining editorial order.
        New shots should be inserted at the correct position, not appended.

        Args:
            shot: Shot data dict
        """
        row = len(self._shots)
        self.beginInsertRows(QModelIndex(), row, row)
        self._shots.append(shot)
        self._invalidate_uuid_index()
        self.endInsertRows()

    def insert_shot_at_order(self, shot: Dict[str, Any]):
        """
        Insert shot at correct position based on editorial_order.

        Args:
            shot: Shot data dict with 'editorial_order' field
        """
        editorial_order = shot.get('editorial_order', '9999.9999.9999.9999')

        # Find correct insertion point
        insert_idx = 0
        for i, existing_shot in enumerate(self._shots):
            if existing_shot.get('editorial_order', '9999.9999.9999.9999') > editorial_order:
                insert_idx = i
                break
            insert_idx = i + 1

        self.beginInsertRows(QModelIndex(), insert_idx, insert_idx)
        self._shots.insert(insert_idx, shot)
        self._invalidate_uuid_index()
        self.endInsertRows()

    def remove_shot(self, uuid: str) -> bool:
        """
        Remove shot by UUID

        Args:
            uuid: Shot UUID

        Returns:
            True if removed, False if not found
        """
        for i, shot in enumerate(self._shots):
            if shot.get('uuid') == uuid or shot.get('id') == uuid:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._shots[i]
                self._invalidate_uuid_index()
                self.endRemoveRows()
                return True
        return False

    def update_shot(self, uuid: str, updates: Dict[str, Any]) -> bool:
        """
        Update shot data

        Args:
            uuid: Shot UUID
            updates: Dict of fields to update

        Returns:
            True if updated, False if not found
        """
        for i, shot in enumerate(self._shots):
            if shot.get('uuid') == uuid or shot.get('id') == uuid:
                shot.update(updates)
                # Emit dataChanged for this row
                index = self.index(i, 0)
                self.dataChanged.emit(index, index)
                return True
        return False

    def refresh_shot(self, uuid: str) -> bool:
        """
        Refresh shot data from database

        Args:
            uuid: Shot UUID

        Returns:
            True if refreshed, False if not found
        """
        db_service = self._get_db_service()
        updated_data = db_service.get_shot_by_uuid(uuid)

        if updated_data:
            for i, shot in enumerate(self._shots):
                if shot.get('uuid') == uuid or shot.get('id') == uuid:
                    # Merge updated DB data into existing shot dict
                    # This preserves model-specific fields (playblast_count, etc.)
                    # while updating DB fields (status, etc.)
                    shot.update(updated_data)
                    # Ensure uuid key exists (DB uses 'id')
                    shot['uuid'] = uuid
                    # Sync display_mode to preview_mode (card reads preview_mode)
                    if 'display_mode' in updated_data:
                        shot['preview_mode'] = updated_data['display_mode']
                    # Emit dataChanged for this row
                    index = self.index(i, 0)
                    self.dataChanged.emit(index, index)
                    return True
        return False

    def get_shot_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Get shot data by UUID

        Args:
            uuid: Shot UUID

        Returns:
            Shot dict or None
        """
        for shot in self._shots:
            if shot.get('uuid') == uuid:
                return shot
        return None

    def get_shot_at_index(self, row: int) -> Optional[Dict[str, Any]]:
        """
        Get shot data at row index

        Args:
            row: Row index

        Returns:
            Shot dict or None
        """
        if 0 <= row < len(self._shots):
            return self._shots[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of shots"""
        if parent.isValid():
            return 0
        return len(self._shots)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """
        Get data for index and role

        Args:
            index: Model index
            role: Data role

        Returns:
            Data for role or None
        """
        if not index.isValid() or index.row() >= len(self._shots):
            return None

        shot = self._shots[index.row()]
        self._data_access_count += 1

        # Sparse data access - use .get() for optional fields
        if role == Qt.ItemDataRole.DisplayRole:
            return shot.get('shot_name', 'Unknown')

        elif role == ShotRole.UUIDRole:
            return shot.get('uuid') or shot.get('id')

        elif role == ShotRole.NameRole:
            return shot.get('shot_name', 'Unknown')

        elif role == ShotRole.FolderPathRole:
            return shot.get('folder_path')

        elif role == ShotRole.BlendFileRole:
            return shot.get('blend_file')

        elif role == ShotRole.EpisodeNumRole:
            return shot.get('episode_num')

        elif role == ShotRole.SequenceNumRole:
            return shot.get('sequence_num')

        elif role == ShotRole.SceneNumRole:
            return shot.get('scene_num')

        elif role == ShotRole.ShotNumRole:
            return shot.get('shot_num')

        elif role == ShotRole.EditorialOrderRole:
            return shot.get('editorial_order', '9999.9999.9999.9999')

        elif role == ShotRole.StatusRole:
            return shot.get('status', 'WIP')

        elif role == ShotRole.ParseWarningRole:
            return shot.get('parse_warning')

        elif role == ShotRole.LatestPlayblastPathRole:
            return shot.get('latest_playblast_path')

        elif role == ShotRole.LatestPlayblastVersionRole:
            return shot.get('latest_playblast_version')

        elif role == ShotRole.PlayblastCountRole:
            return shot.get('playblast_count', 0)

        elif role == ShotRole.HasPlayblastRole:
            # NOTE: ShotRole.HasPlayblastRole (UserRole+33) == AnimationRole.ThumbnailPathRole
            # The AnimationCardDelegate requests ThumbnailPathRole, so return the path string
            # not a boolean. This handles both use cases since a truthy path string works
            # for HasPlayblast checks and also provides the path for thumbnail rendering.
            return shot.get('thumbnail_path') or shot.get('latest_playblast_path')

        elif role == ShotRole.ThumbnailPathRole:
            # Use thumbnail from playblast if available
            return shot.get('thumbnail_path') or shot.get('latest_playblast_path')

        elif role == ShotRole.PreviewPathRole:
            return shot.get('latest_playblast_path')

        elif role == ShotRole.DurationMsRole:
            return shot.get('duration_ms')

        elif role == ShotRole.FPSRole:
            return shot.get('fps')

        elif role == ShotRole.FrameCountRole:
            return shot.get('frame_count')

        elif role == ShotRole.WidthRole:
            return shot.get('width')

        elif role == ShotRole.HeightRole:
            return shot.get('height')

        elif role == ShotRole.CreatedDateRole:
            return shot.get('created_at')

        elif role == ShotRole.ModifiedDateRole:
            return shot.get('updated_at')

        elif role == ShotRole.HasNotesRole:
            uuid = shot.get('uuid') or shot.get('id')
            return uuid in self._shots_with_notes if uuid else False

        elif role == ShotRole.UnresolvedCommentCountRole:
            uuid = shot.get('uuid') or shot.get('id')
            return self._unresolved_counts.get(uuid, 0) if uuid else 0

        # Shot version grouping roles
        elif role == ShotRole.BaseShotNameRole:
            return shot.get('base_shot_name')

        elif role == ShotRole.ShotVersionRole:
            return shot.get('shot_version')

        elif role == ShotRole.VersionGroupIdRole:
            return shot.get('version_group_id')

        elif role == ShotRole.IsLatestShotVersionRole:
            # Default to True for backwards compatibility (non-versioned shots)
            return shot.get('is_latest_shot_version', True)

        elif role == ShotRole.VersionCountRole:
            return shot.get('version_count', 1)

        elif role == ShotRole.ShotDataRole:
            return shot

        # Lookdev info roles (parallel to playblast)
        elif role == ShotRole.LatestLookdevPathRole:
            return shot.get('latest_lookdev_path')

        elif role == ShotRole.LatestLookdevVersionRole:
            return shot.get('latest_lookdev_version')

        elif role == ShotRole.LookdevCountRole:
            return shot.get('lookdev_count', 0)

        elif role == ShotRole.HasLookdevRole:
            return shot.get('latest_lookdev_path') is not None

        # Render info roles
        elif role == ShotRole.RenderProxyPathRole:
            return shot.get('render_proxy_path')

        elif role == ShotRole.HasRenderRole:
            return shot.get('render_proxy_path') is not None

        elif role == ShotRole.PreviewModeRole:
            # Default to playblast, can be overridden per-shot
            return shot.get('preview_mode', 'playblast')

        # Task/Assignment roles
        elif role == ShotRole.AssignedToRole:
            return shot.get('assigned_to')

        elif role == ShotRole.AssignedToNameRole:
            return shot.get('assigned_to_name')

        elif role == ShotRole.TaskPriorityRole:
            return shot.get('task_priority')

        elif role == ShotRole.TaskDueDateRole:
            return shot.get('task_due_date')

        elif role == ShotRole.TaskStatusRole:
            return shot.get('task_status')

        elif role == ShotRole.TaskIdRole:
            return shot.get('task_id')

        # Multi-camera reference file roles
        elif role == ShotRole.ShotRoleRole:
            return shot.get('shot_role', 'standalone')

        elif role == ShotRole.MasterShotIdRole:
            return shot.get('master_shot_id')

        elif role == ShotRole.ViewCountRole:
            return shot.get('view_count', 0)

        elif role == ShotRole.HasViewsRole:
            # True if shot is a master with attached views
            return shot.get('shot_role') == 'master' and shot.get('view_count', 0) > 0

        elif role == ShotRole.CombinedPlayblastPathRole:
            return shot.get('combined_playblast_path')

        elif role == ShotRole.CombinedLookdevPathRole:
            return shot.get('combined_lookdev_path')

        elif role == ShotRole.ViewNameRole:
            return shot.get('view_name')

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """
        Set data for index and role.

        Currently only supports setting PreviewModeRole.

        Args:
            index: Model index
            value: Value to set
            role: Data role

        Returns:
            True if data was set successfully
        """
        if not index.isValid() or index.row() >= len(self._shots):
            return False

        shot = self._shots[index.row()]

        if role == ShotRole.PreviewModeRole:
            if value in ('playblast', 'lookdev', 'render'):
                shot['preview_mode'] = value
                # Persist to database
                shot_id = shot.get('id') or shot.get('uuid')
                if shot_id:
                    try:
                        db_service = self._get_db_service()
                        db_service.shots.update(shot_id, display_mode=value)
                    except Exception as e:
                        pass
                self.dataChanged.emit(index, index, [role])
                return True
            return False

        return False

    def set_selected_preview_mode(self, indices: List[QModelIndex], mode: str) -> int:
        """
        Set preview mode for specific shots.

        Args:
            indices: List of model indices (source indices, not proxy)
            mode: 'playblast', 'lookdev', or 'render'

        Returns:
            Number of shots updated
        """
        if mode not in ('playblast', 'lookdev', 'render'):
            return 0

        count = 0
        for index in indices:
            if self.setData(index, mode, ShotRole.PreviewModeRole):
                count += 1

        return count

    def set_all_preview_mode(self, mode: str):
        """
        Set preview mode for all shots.

        Args:
            mode: 'playblast', 'lookdev', or 'render'
        """
        if mode not in ('playblast', 'lookdev', 'render'):
            return

        if not self._shots:
            return

        # Update all shots
        for shot in self._shots:
            shot['preview_mode'] = mode

        # Emit dataChanged for all rows
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._shots) - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [ShotRole.PreviewModeRole])

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """
        Return item flags.

        Note: Drag is disabled - shots have fixed editorial order.

        Args:
            index: Model index

        Returns:
            Item flags
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return (
            Qt.ItemFlag.ItemIsEnabled |
            Qt.ItemFlag.ItemIsSelectable
        )

    def supportedDragActions(self) -> Qt.DropAction:
        """
        Return supported drag actions.

        Note: Drag/drop reordering is disabled for shots.
        Shots maintain their editorial order from the filesystem.
        """
        return Qt.DropAction.IgnoreAction

    def mimeTypes(self) -> List[str]:
        """Return supported MIME types for drag & drop"""
        return ['application/x-shot-uuid']

    def mimeData(self, indexes: List[QModelIndex]) -> QMimeData:
        """
        Create MIME data for drag operation (for potential future use).

        Args:
            indexes: List of dragged indexes

        Returns:
            MIME data with shot UUIDs
        """
        mime_data = QMimeData()
        uuids = []

        for index in indexes:
            if index.isValid():
                uuid = self.data(index, ShotRole.UUIDRole)
                if uuid:
                    uuids.append(uuid)

        # Encode as newline-separated UUIDs
        mime_data.setData('application/x-shot-uuid', QByteArray('\n'.join(uuids).encode()))
        return mime_data

    # ==================== PERFORMANCE MONITORING ====================

    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics

        Returns:
            Dict with performance metrics
        """
        return {
            'shot_count': len(self._shots),
            'load_time_ms': self._load_time,
            'data_access_count': self._data_access_count,
        }

    def reset_performance_stats(self):
        """Reset performance counters"""
        self._data_access_count = 0
        self._load_time = 0.0


__all__ = ['ShotListModel', 'ShotRole']
