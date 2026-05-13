"""
Sync Service - Handles database synchronization with verification.

This service extracts the sync logic from MainWindow, providing a clean
interface for:
- Syncing shots to database
- Resolving master/view relationships
- Verifying database updates

Usage:
    from shot_library.services.sync_service import SyncService
    from shot_library.services.database_service import get_database_service

    service = SyncService(db_service=get_database_service())

    # Sync shots to database
    result = service.sync_shots(shot_dicts)

    # Resolve master/view relationships
    service.resolve_master_view_relationships(shot_dicts)
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from .utils.path_utils import normalize_path


@dataclass
class SyncResult:
    """Result of a sync operation."""
    total_shots: int
    synced_shots: int
    synced_playblasts: int
    synced_lookdevs: int
    errors: List[str]
    auto_status_changes: List[Dict[str, Any]]


class SyncService(QObject):
    """
    Service for syncing discovered shots to the database.

    This service handles:
    - Upserting shots to database
    - Syncing playblast records
    - Syncing lookdev records
    - Resolving master/view relationships with verification
    - Auto-status changes for new playblasts

    Signals:
        sync_started: Emitted when sync begins
        shot_synced: Emitted for each shot synced (shot_uuid)
        sync_progress: Emitted with progress (current, total)
        sync_complete: Emitted when sync completes (SyncResult)
        sync_error: Emitted on errors (error_message)
    """

    sync_started = pyqtSignal()
    shot_synced = pyqtSignal(str)  # shot_uuid
    sync_progress = pyqtSignal(int, int)  # current, total
    sync_complete = pyqtSignal(object)  # SyncResult
    sync_error = pyqtSignal(str)

    def __init__(self, db_service=None, parent=None):
        """
        Initialize sync service.

        Args:
            db_service: Database service instance (uses singleton if None)
            parent: Qt parent object
        """
        super().__init__(parent)

        if db_service is None:
            from .database_service import get_database_service
            db_service = get_database_service()

        self._db_service = db_service

    def sync_shots(
        self,
        shot_dicts: List[Dict[str, Any]],
        playblasts_by_shot: Optional[Dict[str, List]] = None,
        lookdevs_by_shot: Optional[Dict[str, List]] = None,
        auto_status_on_new_playblast: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> SyncResult:
        """
        Sync shots and their media to the database.

        Args:
            shot_dicts: List of shot dicts to sync
            playblasts_by_shot: Optional dict mapping shot_uuid to list of DiscoveredPlayblast
            lookdevs_by_shot: Optional dict mapping shot_uuid to list of DiscoveredLookdev
            auto_status_on_new_playblast: If True, set status to "In Review" on new playblast
            progress_callback: Optional callback for progress updates (current, total)

        Returns:
            SyncResult with statistics and errors
        """
        self.sync_started.emit()

        playblasts_by_shot = playblasts_by_shot or {}
        lookdevs_by_shot = lookdevs_by_shot or {}

        errors = []
        auto_status_changes = []
        synced_shots = 0
        synced_playblasts = 0
        synced_lookdevs = 0

        total = len(shot_dicts)

        for i, shot_dict in enumerate(shot_dicts):
            shot_uuid = shot_dict.get('uuid') or shot_dict.get('id')

            # Progress update
            if progress_callback:
                progress_callback(i + 1, total)
            self.sync_progress.emit(i + 1, total)

            try:
                # Sync shot record
                self._sync_shot_record(shot_dict)
                synced_shots += 1
                self.shot_synced.emit(shot_uuid)

                # Sync playblasts for this shot
                playblasts = playblasts_by_shot.get(shot_uuid, [])
                for pb in playblasts:
                    try:
                        result = self._sync_playblast_record(shot_uuid, shot_dict, pb, auto_status_on_new_playblast)
                        synced_playblasts += 1
                        if result.get('status_changed'):
                            auto_status_changes.append(result)
                    except Exception as e:
                        errors.append(f"Failed to sync playblast: {e}")

                # Sync lookdevs for this shot
                lookdevs = lookdevs_by_shot.get(shot_uuid, [])
                for ld in lookdevs:
                    try:
                        self._sync_lookdev_record(shot_uuid, ld)
                        synced_lookdevs += 1
                    except Exception as e:
                        errors.append(f"Failed to sync lookdev: {e}")

            except Exception as e:
                error_msg = f"Failed to sync shot {shot_dict.get('shot_name')}: {e}"
                errors.append(error_msg)

        result = SyncResult(
            total_shots=total,
            synced_shots=synced_shots,
            synced_playblasts=synced_playblasts,
            synced_lookdevs=synced_lookdevs,
            errors=errors,
            auto_status_changes=auto_status_changes
        )

        self.sync_complete.emit(result)
        return result

    def _sync_shot_record(self, shot_dict: Dict[str, Any]) -> None:
        """
        Sync a single shot record to the database.

        Args:
            shot_dict: Shot dict to sync
        """
        shot_uuid = shot_dict.get('uuid') or shot_dict.get('id')

        # Check if shot exists to preserve status
        existing_shot = self._db_service.shots.get_by_id(shot_uuid)
        if existing_shot:
            status_to_use = existing_shot.get('status', 'WIP')
            display_mode_to_use = existing_shot.get('display_mode', 'playblast')
            # Preserve user-managed v12 metadata across re-indexing
            shot_dict['frame_in'] = existing_shot.get('frame_in')
            shot_dict['frame_out'] = existing_shot.get('frame_out')
            shot_dict['description'] = existing_shot.get('description', '')
            shot_dict['priority'] = existing_shot.get('priority', 2)
        else:
            status_to_use = shot_dict.get('status', 'WIP')
            display_mode_to_use = shot_dict.get('display_mode', 'playblast')

        # Update shot_dict so model has correct values
        shot_dict['status'] = status_to_use
        shot_dict['display_mode'] = display_mode_to_use
        shot_dict['preview_mode'] = display_mode_to_use

        # Pass v12 metadata as None for existing shots (upsert.update skips None),
        # so the preserved values above stay untouched. For new shots, pass the
        # discovery defaults so they land in the INSERT path.
        if existing_shot:
            frame_in_val = None
            frame_out_val = None
            description_val = None
            priority_val = None
        else:
            frame_in_val = shot_dict.get('frame_in')
            frame_out_val = shot_dict.get('frame_out')
            description_val = shot_dict.get('description')
            priority_val = shot_dict.get('priority')

        result = self._db_service.shots.upsert(
            shot_id=shot_uuid,
            folder_path=shot_dict['folder_path'],
            blend_file=shot_dict['blend_file'],
            shot_name=shot_dict['shot_name'],
            editorial_order=shot_dict['editorial_order'],
            sequence_num=shot_dict.get('sequence_num'),
            scene_num=shot_dict.get('scene_num'),
            shot_num=shot_dict.get('shot_num'),
            episode_num=shot_dict.get('episode_num'),
            status=status_to_use,
            parse_warning=shot_dict.get('parse_warning'),
            base_shot_name=shot_dict.get('base_shot_name'),
            shot_version=shot_dict.get('shot_version'),
            version_group_id=shot_dict.get('version_group_id'),
            is_latest_shot_version=shot_dict.get('is_latest_shot_version', True),
            display_mode=display_mode_to_use,
            shot_role=shot_dict.get('shot_role', 'standalone'),
            master_shot_id=shot_dict.get('master_shot_id'),
            view_name=shot_dict.get('view_name'),
            frame_in=frame_in_val,
            frame_out=frame_out_val,
            description=description_val,
            priority=priority_val,
        )

    def _sync_playblast_record(
        self,
        shot_uuid: str,
        shot_dict: Dict[str, Any],
        playblast,
        auto_status: bool
    ) -> Dict[str, Any]:
        """
        Sync a playblast record to the database.

        Args:
            shot_uuid: Shot UUID
            shot_dict: Shot dict (for status updates)
            playblast: DiscoveredPlayblast object
            auto_status: If True, update status on new playblast

        Returns:
            Dict with sync info and status_changed flag
        """
        result = {'status_changed': False}

        # Check if this is a new playblast
        existing_pb = self._db_service.playblasts.get_by_file_path(str(playblast.file_path))
        is_new_playblast = existing_pb is None

        self._db_service.playblasts.upsert(
            shot_id=shot_uuid,
            version=playblast.version,
            file_path=str(playblast.file_path),
            fps=playblast.metadata.fps if playblast.metadata else None,
            frame_count=playblast.metadata.frame_count if playblast.metadata else None,
            width=playblast.metadata.width if playblast.metadata else None,
            height=playblast.metadata.height if playblast.metadata else None,
            duration_ms=playblast.metadata.duration_ms if playblast.metadata else None,
            is_latest=playblast.is_latest,
            is_archived=playblast.is_archived,
        )

        # Auto-flag shot as "In Review" for new playblasts
        if auto_status and is_new_playblast and playblast.is_latest:
            current_status = shot_dict.get('status', 'WIP')
            if current_status not in ('In Review', 'Blocked'):
                self._db_service.shots.update(shot_uuid, status='In Review')
                old_status = shot_dict['status']
                shot_dict['status'] = 'In Review'

                result['status_changed'] = True
                result['shot_uuid'] = shot_uuid
                result['shot_name'] = shot_dict.get('shot_name', 'Unknown')
                result['old_status'] = old_status
                result['new_status'] = 'In Review'
                result['trigger'] = 'new_playblast'


        return result

    def _sync_lookdev_record(self, shot_uuid: str, lookdev) -> None:
        """
        Sync a lookdev record to the database.

        Args:
            shot_uuid: Shot UUID
            lookdev: DiscoveredLookdev object
        """
        # Check if lookdevs table exists (may not in all installations)
        if not hasattr(self._db_service, 'lookdevs'):
            return

        self._db_service.lookdevs.upsert(
            shot_id=shot_uuid,
            version=lookdev.version,
            file_path=str(lookdev.file_path),
            fps=lookdev.metadata.fps if lookdev.metadata else None,
            frame_count=lookdev.metadata.frame_count if lookdev.metadata else None,
            width=lookdev.metadata.width if lookdev.metadata else None,
            height=lookdev.metadata.height if lookdev.metadata else None,
            duration_ms=lookdev.metadata.duration_ms if lookdev.metadata else None,
            is_latest=lookdev.is_latest,
            is_archived=lookdev.is_archived,
        )

    def resolve_master_view_relationships(
        self,
        shot_dicts: List[Dict[str, Any]],
        verify: bool = True
    ) -> int:
        """
        Resolve master_shot_id for view shots after all shots are synced.

        Uses normalized paths for reliable Windows path comparison.

        Args:
            shot_dicts: List of shot dicts to process (modified in-place)
            verify: If True, verify the link persisted in database

        Returns:
            Number of view shots successfully linked
        """
        if not self._db_service:
            return 0

        linked_count = 0

        try:
            # Build lookup from NORMALIZED blend_file path to UUID
            blend_to_uuid: Dict[str, str] = {}
            for sd in shot_dicts:
                blend_file = sd.get('blend_file')
                if blend_file:
                    normalized_key = normalize_path(blend_file)
                    blend_to_uuid[normalized_key] = sd.get('uuid') or sd.get('id')

            # Resolve master_shot_id for views
            for sd in shot_dicts:
                if sd.get('shot_role') == 'view':
                    master_blend = sd.get('master_blend_file')
                    if not master_blend:
                        continue

                    # Use normalized path for lookup
                    normalized_master = normalize_path(master_blend)
                    master_uuid = blend_to_uuid.get(normalized_master)


                    if master_uuid:
                        sd['master_shot_id'] = master_uuid
                        view_id = sd.get('uuid') or sd.get('id')

                        # Update in database with verification
                        success = self._db_service.shots.set_as_view(view_id, master_uuid)

                        if success and verify:
                            # Verify the link persisted
                            view_shot = self._db_service.shots.get_by_id(view_id)
                            if view_shot and view_shot.get('master_shot_id') == master_uuid:
                                linked_count += 1
                        elif success:
                            linked_count += 1

            # Calculate view counts for masters
            self._update_view_counts(shot_dicts)

        except Exception as e:
            pass

        return linked_count

    def _update_view_counts(self, shot_dicts: List[Dict[str, Any]]) -> None:
        """
        Update view_count for master shots.

        Args:
            shot_dicts: List of shot dicts (modified in-place)
        """
        master_view_counts: Dict[str, int] = {}
        master_view_playblasts: Dict[str, List[Dict[str, Any]]] = {}

        for sd in shot_dicts:
            master_id = sd.get('master_shot_id')
            if master_id and sd.get('shot_role') == 'view':
                master_view_counts[master_id] = master_view_counts.get(master_id, 0) + 1

                # Collect view playblast info for the master
                if sd.get('latest_playblast_path'):
                    if master_id not in master_view_playblasts:
                        master_view_playblasts[master_id] = []
                    master_view_playblasts[master_id].append({
                        'view_name': sd.get('view_name') or sd.get('shot_name'),
                        'playblast_path': sd.get('latest_playblast_path'),
                        'playblast_version': sd.get('latest_playblast_version'),
                    })

        # Apply view counts and fallback playblast to masters
        for sd in shot_dicts:
            shot_id = sd.get('uuid') or sd.get('id')
            if sd.get('shot_role') == 'master':
                if shot_id in master_view_counts:
                    sd['view_count'] = master_view_counts[shot_id]

                # If master has no playblast but views do, use first view's playblast
                if not sd.get('latest_playblast_path') and shot_id in master_view_playblasts:
                    view_pbs = sorted(
                        master_view_playblasts[shot_id],
                        key=lambda x: x['view_name'] or ''
                    )
                    if view_pbs:
                        first_view = view_pbs[0]
                        sd['latest_playblast_path'] = first_view['playblast_path']
                        sd['latest_playblast_version'] = first_view['playblast_version']
                        sd['playblast_count'] = len(view_pbs)
                        sd['has_view_playblasts'] = True


# Singleton instance
_sync_service: Optional[SyncService] = None


def get_sync_service() -> SyncService:
    """Get or create the sync service singleton."""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service


__all__ = [
    'SyncResult',
    'SyncService',
    'get_sync_service',
]
