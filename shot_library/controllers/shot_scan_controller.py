"""
ShotScanController - Orchestrates shot discovery and sync workflow

This controller extracts the scanning logic from MainWindow into a focused
component that coordinates:
- Shot discovery via DiscoveryService
- Database sync via SyncService
- Master/view relationship resolution
- Video stitching for multi-camera setups
- Task enrichment

Usage:
    from shot_library.controllers import ShotScanController
    from shot_library.services.discovery_service import get_discovery_service
    from shot_library.services.sync_service import get_sync_service

    controller = ShotScanController(
        discovery_service=get_discovery_service(),
        sync_service=get_sync_service(),
        shot_model=shot_model,
    )

    # Connect to signals
    controller.scan_complete.connect(on_scan_complete)

    # Trigger scan
    controller.scan_folder(Path("/path/to/project"))
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from ..events.event_bus import get_event_bus
from ..services.discovery_service import DiscoveryService, DiscoveryResult
from ..services.sync_service import SyncService, SyncResult


@dataclass
class ScanResult:
    """Result of a complete scan operation."""
    folder_path: Path
    total_shots: int
    shots_with_media: int
    synced_to_db: int
    errors: List[str]
    shot_dicts: List[Dict[str, Any]]


class ShotScanController(QObject):
    """
    Controller for shot scanning workflow.

    This controller orchestrates the full scan process:
    1. Discover shots using DiscoveryService
    2. Sync to database using SyncService
    3. Resolve master/view relationships
    4. Stitch multi-camera videos
    5. Enrich with task data
    6. Emit results via signals

    Signals:
        scan_started: Emitted when scan begins (folder_path)
        scan_progress: Emitted with progress (current, total)
        scan_complete: Emitted when scan completes (ScanResult)
        scan_error: Emitted on errors (error_message)
        shots_ready: Emitted when shot_dicts are ready for model (List[Dict])
    """

    # Controller signals
    scan_started = pyqtSignal(str)  # folder_path
    scan_progress = pyqtSignal(int, int)  # current, total
    scan_complete = pyqtSignal(object)  # ScanResult
    scan_error = pyqtSignal(str)  # error_message
    shots_ready = pyqtSignal(list)  # List[Dict] - shot_dicts ready for model

    def __init__(
        self,
        discovery_service: Optional[DiscoveryService] = None,
        sync_service: Optional[SyncService] = None,
        shot_model=None,
        db_service=None,
        audit_service=None,
        parent=None
    ):
        """
        Initialize the scan controller.

        Args:
            discovery_service: Service for discovering shots (creates new if None)
            sync_service: Service for syncing to database (creates new if None)
            shot_model: ShotListModel instance (optional, for direct model updates)
            db_service: Database service (for task enrichment)
            audit_service: Audit service (for logging status changes)
            parent: Qt parent object
        """
        super().__init__(parent)

        # Services - MUST be provided, no fallback to singletons
        # (singletons require schema_parser which isn't available globally)
        if discovery_service is None:
            raise ValueError("ShotScanController requires discovery_service to be provided")
        self._discovery_service = discovery_service

        if sync_service is None:
            raise ValueError("ShotScanController requires sync_service to be provided")
        self._sync_service = sync_service

        if db_service is None:
            from ..services.database_service import get_database_service
            db_service = get_database_service()
        self._db_service = db_service

        self._audit_service = audit_service
        self._shot_model = shot_model

        # Event bus for broadcasting
        self._event_bus = get_event_bus()

        # State
        self._current_folder: Optional[Path] = None
        self._is_scanning = False

        # Connect discovery service signals
        self._discovery_service.discovery_progress.connect(self._on_discovery_progress)
        self._discovery_service.discovery_error.connect(self._on_discovery_error)

    @property
    def is_scanning(self) -> bool:
        """Return True if a scan is in progress."""
        return self._is_scanning

    @property
    def current_folder(self) -> Optional[Path]:
        """Return the currently scanned folder."""
        return self._current_folder

    def scan_folder(
        self,
        folder_path: Path,
        require_media: bool = True,
        include_views: bool = True,
        stitch_videos: bool = True,
        enrich_tasks: bool = True
    ) -> ScanResult:
        """
        Scan a folder for shots and sync to database.

        This is the main entry point for the scanning workflow.

        Args:
            folder_path: Path to the folder to scan
            require_media: If True, only include shots with playblasts
            include_views: If True, include master/view shots even without media
            stitch_videos: If True, auto-stitch multi-camera videos
            enrich_tasks: If True, enrich with Pipeline Control task data

        Returns:
            ScanResult with statistics and shot_dicts
        """
        folder_path = Path(folder_path)
        self._current_folder = folder_path
        self._is_scanning = True

        errors = []
        shot_dicts = []

        # Emit started signal
        self.scan_started.emit(str(folder_path))
        self._event_bus.shot_scan_started.emit(str(folder_path))

        try:
            # Step 1: Discover shots and enrich with media
            discovery_result = self._discovery_service.discover_and_enrich(
                folder_path,
                require_media=not include_views,  # Include all if views enabled
                progress_callback=self._on_progress
            )

            shot_dicts = discovery_result.shot_dicts
            errors.extend(discovery_result.errors)

            # Step 2: Filter based on require_media (if views were included)
            if include_views and require_media:
                shot_dicts = self._filter_shots_with_media_or_role(shot_dicts)

            # Step 3: Recalculate latest flags among filtered shots
            self._discovery_service.recalculate_latest_flags(shot_dicts)

            # Step 4: Sync to database (including playblasts and lookdevs)
            sync_result = self._sync_service.sync_shots(
                shot_dicts,
                playblasts_by_shot=discovery_result.playblasts_by_shot,
                lookdevs_by_shot=discovery_result.lookdevs_by_shot
            )
            errors.extend(sync_result.errors)

            # Log auto-status changes
            if self._audit_service:
                for change in sync_result.auto_status_changes:
                    if change.get('status_changed'):
                        self._audit_service.log_status_change(
                            shot_id=change['shot_uuid'],
                            shot_name=change['shot_name'],
                            old_status=change['old_status'],
                            new_status=change['new_status']
                        )

            # Step 5: Resolve master/view relationships
            self._sync_service.resolve_master_view_relationships(shot_dicts, verify=True)

            # Step 6: Stitch multi-camera videos
            if stitch_videos:
                self._stitch_master_videos(shot_dicts)

            # Step 7: Enrich with task data
            if enrich_tasks:
                self._enrich_with_tasks(shot_dicts)

            # Create result
            result = ScanResult(
                folder_path=folder_path,
                total_shots=discovery_result.total_shots,
                shots_with_media=len(shot_dicts),
                synced_to_db=sync_result.synced_shots,
                errors=errors,
                shot_dicts=shot_dicts
            )

            # Emit signals
            self.shots_ready.emit(shot_dicts)
            self._event_bus.shot_scan_complete.emit(result)
            self.scan_complete.emit(result)

            return result

        except Exception as e:
            error_msg = f"Scan failed: {e}"
            errors.append(error_msg)
            self.scan_error.emit(error_msg)
            self._event_bus.shot_scan_error.emit(error_msg)

            return ScanResult(
                folder_path=folder_path,
                total_shots=0,
                shots_with_media=0,
                synced_to_db=0,
                errors=errors,
                shot_dicts=[]
            )

        finally:
            self._is_scanning = False

    def _filter_shots_with_media_or_role(
        self,
        shot_dicts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter to include shots with media OR master/view role.

        Masters and views are included even without direct playblasts
        because masters get combined videos from views.

        Args:
            shot_dicts: List of shot dicts to filter

        Returns:
            Filtered list of shot dicts
        """
        filtered = []
        for sd in shot_dicts:
            has_media = (
                sd.get('playblast_count', 0) > 0 or
                sd.get('lookdev_count', 0) > 0
            )
            is_master_or_view = sd.get('shot_role') in ('master', 'view')

            if has_media or is_master_or_view:
                filtered.append(sd)

        return filtered

    def _stitch_master_videos(self, shot_dicts: List[Dict[str, Any]]) -> None:
        """
        Auto-stitch view playblasts/lookdevs into combined videos for masters.

        Args:
            shot_dicts: List of shot dicts (modified in-place)
        """
        try:
            from ..core.playblast_stitcher import get_playblast_stitcher, ViewPlayblast

            stitcher = get_playblast_stitcher()
            if not stitcher.is_ffmpeg_available():
                return

            # Find masters and collect their view videos
            for sd in shot_dicts:
                if sd.get('shot_role') != 'master':
                    continue

                shot_id = sd.get('uuid') or sd.get('id')
                shot_name = sd.get('shot_name', 'Unknown')
                folder_path = sd.get('folder_path')

                if not folder_path:
                    continue

                master_folder = Path(folder_path)

                # Collect view playblasts and lookdevs
                view_playblasts = []
                view_lookdevs = []

                for view_sd in shot_dicts:
                    if view_sd.get('master_shot_id') == shot_id and view_sd.get('shot_role') == 'view':
                        view_name = self._get_view_name(view_sd)

                        # Collect playblast
                        pb_path = view_sd.get('latest_playblast_path')
                        if pb_path:
                            view_playblasts.append(ViewPlayblast(
                                view_name=view_name,
                                playblast_path=Path(pb_path),
                                version=view_sd.get('latest_playblast_version', 1),
                                is_latest=True
                            ))

                        # Collect lookdev
                        ld_path = view_sd.get('latest_lookdev_path')
                        if ld_path:
                            view_lookdevs.append(ViewPlayblast(
                                view_name=view_name,
                                playblast_path=Path(ld_path),
                                version=view_sd.get('latest_lookdev_version', 1),
                                is_latest=True
                            ))

                # Stitch playblasts
                if view_playblasts:
                    combined = self._stitch_if_needed(
                        stitcher, master_folder, shot_name, view_playblasts, 'playblast'
                    )
                    if combined:
                        sd['combined_playblast_path'] = str(combined)
                        sd['latest_playblast_path'] = str(combined)

                # Stitch lookdevs
                if view_lookdevs:
                    combined = self._stitch_if_needed(
                        stitcher, master_folder, shot_name, view_lookdevs, 'lookdev'
                    )
                    if combined:
                        sd['combined_lookdev_path'] = str(combined)
                        sd['latest_lookdev_path'] = str(combined)

        except Exception as e:
            import traceback
            traceback.print_exc()

    def _get_view_name(self, view_sd: Dict[str, Any]) -> str:
        """Extract view name from shot dict."""
        view_name = view_sd.get('view_name')
        if not view_name:
            shot_name = view_sd.get('shot_name', '')
            if '_ref' in shot_name or '_cam' in shot_name:
                parts = shot_name.rsplit('_', 1)
                if len(parts) > 1:
                    view_name = parts[-1]
            if not view_name:
                view_name = shot_name
        return view_name

    def _stitch_if_needed(
        self,
        stitcher,
        master_folder: Path,
        shot_name: str,
        view_items: List,
        media_type: str
    ) -> Optional[Path]:
        """
        Stitch videos if needed, checking if existing combined is up-to-date.

        Args:
            stitcher: PlayblastStitcher instance
            master_folder: Master shot folder
            shot_name: Shot name
            view_items: List of ViewPlayblast items
            media_type: 'playblast' or 'lookdev'

        Returns:
            Path to combined video, or None
        """
        # Get existing combined video
        if media_type == 'playblast':
            existing = stitcher.get_latest_combined_playblast(master_folder, shot_name)
        else:
            existing = stitcher.get_latest_combined_lookdev(master_folder, shot_name)

        needs_restitch = True

        if existing and existing.exists():
            # Check if views changed
            current_views = sorted([vp.view_name for vp in view_items])
            segments = stitcher.load_segments_json(existing)
            if segments:
                existing_views = sorted([s.get('view_name') for s in segments])
                if current_views == existing_views:
                    needs_restitch = False

        if needs_restitch:
            # Create new combined video
            if media_type == 'playblast':
                result = stitcher.create_combined_playblast(
                    master_folder=master_folder,
                    shot_name=shot_name,
                    view_playblasts=view_items
                )
            else:
                result = stitcher.create_combined_lookdev(
                    master_folder=master_folder,
                    shot_name=shot_name,
                    view_lookdevs=view_items
                )
            return result.output_path if result else None
        else:
            return existing

    def _enrich_with_tasks(self, shot_dicts: List[Dict[str, Any]]) -> None:
        """
        Enrich shot dicts with task/assignment data from Pipeline Control.

        Args:
            shot_dicts: List of shot dicts to enrich (modified in-place)
        """
        if not self._db_service:
            return

        try:
            for sd in shot_dicts:
                shot_id = sd.get('uuid') or sd.get('id')
                if not shot_id:
                    continue

                task = self._db_service.tasks.get_by_shot_id(shot_id)
                if task:
                    sd['task_id'] = task.get('id')
                    sd['assigned_to'] = task.get('assigned_to')
                    sd['assigned_to_name'] = task.get('assigned_to_name')
                    sd['task_priority'] = task.get('priority')
                    sd['task_due_date'] = task.get('due_date')
                    sd['task_status'] = task.get('status')

        except Exception as e:
            pass

    def _on_progress(self, current: int, total: int) -> None:
        """Handle progress updates from discovery service."""
        self.scan_progress.emit(current, total)
        self._event_bus.shot_scan_progress.emit(current, total)

    def _on_discovery_progress(self, current: int, total: int) -> None:
        """Handle progress signal from discovery service."""
        self.scan_progress.emit(current, total)

    def _on_discovery_error(self, error: str) -> None:
        """Handle error signal from discovery service."""
        self.scan_error.emit(error)


__all__ = [
    'ScanResult',
    'ShotScanController',
]
