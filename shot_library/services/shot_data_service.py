"""
ShotDataService - Central service for shot data access

This service enforces the service boundary pattern:
- Widgets use this service instead of calling DB directly
- All data mutations go through this service
- Signals are emitted when data changes

Usage:
    from shot_library.services.shot_data_service import get_shot_data_service

    service = get_shot_data_service()

    # Get shot data
    shot = service.get_shot(shot_uuid)

    # Update shot
    service.update_status(shot_uuid, 'review')

    # Listen for changes
    service.shot_updated.connect(on_shot_updated)
"""

from typing import Optional, Dict, Any, List, Set

from PyQt6.QtCore import QObject, pyqtSignal

from .database_service import get_database_service
from ..events.event_bus import get_event_bus


class ShotDataService(QObject):
    """
    Central service for shot data access.

    This service provides a clean interface for:
    - Reading shot data
    - Updating shot fields
    - Managing shot status
    - Resolving preview files
    - Accessing version history

    All mutations emit signals so UI components can react.

    Signals:
        shot_updated: Emitted when a shot is updated (shot_uuid)
        shot_status_changed: Emitted when status changes (shot_uuid, old_status, new_status)
        shot_deleted: Emitted when a shot is deleted (shot_uuid)
        shots_bulk_updated: Emitted when multiple shots change (List[shot_uuid])
    """

    # Signals
    shot_updated = pyqtSignal(str)  # shot_uuid
    shot_status_changed = pyqtSignal(str, str, str)  # shot_uuid, old_status, new_status
    shot_deleted = pyqtSignal(str)  # shot_uuid
    shots_bulk_updated = pyqtSignal(list)  # List[shot_uuid]

    def __init__(self, db_service=None, event_bus=None, parent=None):
        """
        Initialize shot data service.

        Args:
            db_service: Database service instance (uses singleton if None)
            event_bus: EventBus instance (uses singleton if None)
            parent: Qt parent object
        """
        super().__init__(parent)

        self._db_service = db_service or get_database_service()
        self._event_bus = event_bus or get_event_bus()

    # ==================== READ OPERATIONS ====================

    def get_shot(self, shot_uuid: str) -> Optional[Dict[str, Any]]:
        """
        Get shot data by UUID.

        Args:
            shot_uuid: Shot UUID

        Returns:
            Shot data dict, or None if not found
        """
        if not shot_uuid:
            return None

        try:
            return self._db_service.shots.get_by_id(shot_uuid)
        except Exception as e:
            return None

    def get_shot_by_path(self, folder_path: str, blend_file: str) -> Optional[Dict[str, Any]]:
        """
        Get shot by folder path and blend file.

        Args:
            folder_path: Shot folder path
            blend_file: Blend file name or path

        Returns:
            Shot data dict, or None if not found
        """
        try:
            return self._db_service.shots.get_by_path(folder_path, blend_file)
        except Exception as e:
            return None

    def get_version_count(self, version_group_id: str) -> int:
        """
        Get count of versions in a version group.

        Args:
            version_group_id: Version group UUID

        Returns:
            Number of versions in the group
        """
        if not version_group_id:
            return 1

        try:
            return self._db_service.get_version_count(version_group_id)
        except Exception as e:
            return 1

    def get_unresolved_notes_count(self, shot_uuid: str) -> int:
        """
        Get count of unresolved review notes for a shot.

        Args:
            shot_uuid: Shot UUID

        Returns:
            Count of unresolved notes
        """
        if not shot_uuid:
            return 0

        try:
            from .notes_database import get_notes_database
            notes_db = get_notes_database()
            return notes_db.get_unresolved_count(shot_uuid)
        except Exception as e:
            return 0

    def resolve_preview_file(self, shot_data: Dict[str, Any]) -> Optional[str]:
        """
        Resolve the preview file path for a shot.

        Handles archive location fallback if stored path doesn't exist.

        Args:
            shot_data: Shot data dict

        Returns:
            Resolved preview path, or None
        """
        try:
            return self._db_service.animations.resolve_preview_file(shot_data)
        except Exception as e:
            return None

    def get_views_for_master(self, master_shot_id: str) -> List[Dict[str, Any]]:
        """
        Get all view shots for a master shot.

        Args:
            master_shot_id: Master shot UUID

        Returns:
            List of view shot dicts
        """
        if not master_shot_id:
            return []

        try:
            return self._db_service.shots.get_views_for_master(master_shot_id)
        except Exception as e:
            return []

    def get_latest_playblast(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest playblast for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Playblast data dict, or None
        """
        if not shot_id:
            return None

        try:
            return self._db_service.playblasts.get_latest_for_shot(shot_id)
        except Exception as e:
            return None

    def get_latest_lookdev(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest lookdev for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Lookdev data dict, or None
        """
        if not shot_id:
            return None

        try:
            # Check if lookdevs repository exists (may not in all installations)
            if not hasattr(self._db_service, 'lookdevs'):
                return None
            return self._db_service.lookdevs.get_latest_for_shot(shot_id)
        except Exception as e:
            return None

    def get_task_for_shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task assignment data for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Task data dict, or None
        """
        if not shot_id:
            return None

        try:
            return self._db_service.tasks.get_by_shot_id(shot_id)
        except Exception as e:
            return None

    # ==================== WRITE OPERATIONS ====================

    def update_status(
        self,
        shot_uuid: str,
        new_status: str,
        audit_service=None
    ) -> bool:
        """
        Update shot status.

        Args:
            shot_uuid: Shot UUID
            new_status: New status value
            audit_service: Optional audit service for logging

        Returns:
            True if successful
        """
        if not shot_uuid:
            return False

        try:
            # Get current status for comparison
            shot = self.get_shot(shot_uuid)
            if not shot:
                return False

            old_status = shot.get('status', 'none')
            if old_status == new_status:
                return True  # No change needed

            # Update in database
            success = self._db_service.set_status(shot_uuid, new_status)

            if success:
                # Log to audit trail
                if audit_service:
                    shot_name = shot.get('shot_name') or shot.get('name', 'Unknown')
                    audit_service.log_status_change(
                        shot_id=shot_uuid,
                        shot_name=shot_name,
                        old_status=old_status,
                        new_status=new_status
                    )

                # Emit signals
                self.shot_status_changed.emit(shot_uuid, old_status, new_status)
                self._event_bus.shot_status_changed.emit(shot_uuid, old_status, new_status)
                self.shot_updated.emit(shot_uuid)
                self._event_bus.animation_updated.emit(shot_uuid)

            return success

        except Exception as e:
            return False

    def update_display_mode(self, shot_uuid: str, mode: str) -> bool:
        """
        Update shot display mode (playblast/lookdev/render).

        Args:
            shot_uuid: Shot UUID
            mode: 'playblast', 'lookdev', or 'render'

        Returns:
            True if successful
        """
        if not shot_uuid or mode not in ('playblast', 'lookdev', 'render'):
            return False

        try:
            # Check if shot exists in DB first
            existing = self._db_service.shots.get_by_id(shot_uuid)

            success = self._db_service.shots.update(shot_uuid, display_mode=mode)

            if success:
                self.shot_updated.emit(shot_uuid)
                self._event_bus.shot_preview_mode_changed.emit(shot_uuid, mode)
                self._event_bus.animation_updated.emit(shot_uuid)

            return success

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    def update_task_status(self, shot_uuid: str, task_status: str) -> bool:
        """
        Update task status for a shot.

        Args:
            shot_uuid: Shot UUID
            task_status: New task status ('pending', 'in_progress', 'done')

        Returns:
            True if successful
        """
        if not shot_uuid:
            return False

        try:
            task = self._db_service.tasks.get_by_shot_id(shot_uuid)
            if task:
                self._db_service.tasks.set_status(task['id'], task_status)
                self.shot_updated.emit(shot_uuid)
                return True
            return False

        except Exception as e:
            return False


# Singleton instance
_shot_data_service: Optional[ShotDataService] = None


def get_shot_data_service() -> ShotDataService:
    """Get or create the shot data service singleton."""
    global _shot_data_service
    if _shot_data_service is None:
        _shot_data_service = ShotDataService()
    return _shot_data_service


__all__ = [
    'ShotDataService',
    'get_shot_data_service',
]
