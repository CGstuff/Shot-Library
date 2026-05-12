"""
Discovery Service - Coordinates shot discovery and media enrichment.

This service extracts the discovery logic from MainWindow, providing a clean
interface for:
- Scanning folders for shots
- Enriching shots with playblast/lookdev media
- Converting discovered shots to model-compatible dicts

Usage:
    from shot_library.services.discovery_service import DiscoveryService
    from shot_library.core.shot_indexer import ShotIndexer
    from shot_library.core.media_indexer import create_playblast_indexer, create_lookdev_indexer

    service = DiscoveryService(
        shot_indexer=ShotIndexer(),
        playblast_indexer=create_playblast_indexer(),
        lookdev_indexer=create_lookdev_indexer(),
    )

    # Discover and enrich shots
    shot_dicts = service.discover_and_enrich(folder_path)
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.shot_indexer import ShotIndexer, DiscoveredShot
from ..core.playblast_indexer import PlayblastIndexer, DiscoveredPlayblast
from ..core.lookdev_indexer import LookdevIndexer, DiscoveredLookdev


@dataclass
class DiscoveryResult:
    """Result of a discovery operation."""
    total_shots: int
    shots_with_media: int
    shot_dicts: List[Dict[str, Any]]
    errors: List[str]
    # Maps shot_uuid -> List[DiscoveredPlayblast] for syncing to DB
    playblasts_by_shot: Dict[str, List] = None
    # Maps shot_uuid -> List[DiscoveredLookdev] for syncing to DB
    lookdevs_by_shot: Dict[str, List] = None

    def __post_init__(self):
        if self.playblasts_by_shot is None:
            self.playblasts_by_shot = {}
        if self.lookdevs_by_shot is None:
            self.lookdevs_by_shot = {}


class DiscoveryService(QObject):
    """
    Service for discovering shots and enriching them with media.

    This service coordinates:
    - Shot discovery via ShotIndexer
    - Playblast discovery via PlayblastIndexer
    - Lookdev discovery via LookdevIndexer

    Signals:
        discovery_started: Emitted when discovery begins
        shot_discovered: Emitted for each shot found (DiscoveredShot)
        discovery_progress: Emitted with progress (current, total)
        discovery_complete: Emitted when all shots are discovered (DiscoveryResult)
        discovery_error: Emitted on errors (error_message)
    """

    discovery_started = pyqtSignal()
    shot_discovered = pyqtSignal(object)  # DiscoveredShot
    discovery_progress = pyqtSignal(int, int)  # current, total
    discovery_complete = pyqtSignal(object)  # DiscoveryResult
    discovery_error = pyqtSignal(str)

    # UUID namespace for generating deterministic shot IDs
    UUID_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

    def __init__(
        self,
        shot_indexer: Optional[ShotIndexer] = None,
        playblast_indexer: Optional[PlayblastIndexer] = None,
        lookdev_indexer: Optional[LookdevIndexer] = None,
        parent=None
    ):
        """
        Initialize discovery service.

        Args:
            shot_indexer: ShotIndexer for discovering shots (creates new if None)
            playblast_indexer: PlayblastIndexer for discovering playblasts (creates new if None)
            lookdev_indexer: LookdevIndexer for discovering lookdevs (creates new if None)
            parent: Qt parent object
        """
        super().__init__(parent)

        self._shot_indexer = shot_indexer or ShotIndexer()
        self._playblast_indexer = playblast_indexer or PlayblastIndexer()
        self._lookdev_indexer = lookdev_indexer or LookdevIndexer()

    def discover_shots(self, folder_path: Path) -> List[DiscoveredShot]:
        """
        Discover shots in a folder.

        Args:
            folder_path: Path to scan for shots

        Returns:
            List of DiscoveredShot objects
        """
        return self._shot_indexer.scan_folder(folder_path)

    def discover_and_enrich(
        self,
        folder_path: Path,
        require_media: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> DiscoveryResult:
        """
        Discover shots and enrich with media information.

        This is the main entry point for discovery. It:
        1. Scans folder for shots
        2. Enriches each shot with playblast info
        3. Enriches each shot with lookdev info
        4. Converts to dict format for the model

        Args:
            folder_path: Path to scan for shots
            require_media: If True, only include shots with at least one playblast
            progress_callback: Optional callback for progress updates (current, total)

        Returns:
            DiscoveryResult with shot dicts and statistics
        """
        self.discovery_started.emit()

        errors = []
        folder_path = Path(folder_path)

        # Discover shots
        try:
            shots = self._shot_indexer.scan_folder(folder_path)
        except Exception as e:
            error_msg = f"Failed to scan folder: {e}"
            errors.append(error_msg)
            self.discovery_error.emit(error_msg)
            return DiscoveryResult(
                total_shots=0,
                shots_with_media=0,
                shot_dicts=[],
                errors=errors
            )

        total_shots = len(shots)
        shot_dicts = []
        playblasts_by_shot: Dict[str, List] = {}
        lookdevs_by_shot: Dict[str, List] = {}

        for i, shot in enumerate(shots):
            # Progress update
            if progress_callback:
                progress_callback(i + 1, total_shots)
            self.discovery_progress.emit(i + 1, total_shots)
            self.shot_discovered.emit(shot)

            try:
                shot_dict = self._convert_shot_to_dict(shot)
                shot_dict, playblasts = self._enrich_with_playblasts(shot, shot_dict)
                shot_dict, lookdevs = self._enrich_with_lookdevs(shot, shot_dict)
                shot_dict = self._enrich_with_renders(shot, shot_dict)

                # Store discovered media for syncing to DB
                shot_uuid = shot_dict.get('uuid')
                if playblasts:
                    playblasts_by_shot[shot_uuid] = playblasts
                if lookdevs:
                    lookdevs_by_shot[shot_uuid] = lookdevs

                # Only include if has media (or not required)
                has_media = shot_dict.get('playblast_count', 0) > 0 or shot_dict.get('lookdev_count', 0) > 0
                if not require_media or has_media:
                    shot_dicts.append(shot_dict)

            except Exception as e:
                error_msg = f"Failed to process shot {shot.identity.shot_name}: {e}"
                errors.append(error_msg)

        result = DiscoveryResult(
            total_shots=total_shots,
            shots_with_media=len(shot_dicts),
            shot_dicts=shot_dicts,
            errors=errors,
            playblasts_by_shot=playblasts_by_shot,
            lookdevs_by_shot=lookdevs_by_shot
        )

        self.discovery_complete.emit(result)
        return result

    def _convert_shot_to_dict(self, shot: DiscoveredShot) -> Dict[str, Any]:
        """
        Convert a DiscoveredShot to dict format for ShotListModel.

        Args:
            shot: DiscoveredShot instance from shot indexer

        Returns:
            Dict with shot data for the model
        """
        # Generate deterministic UUID based on blend file path
        blend_file_str = str(shot.blend_file).replace('\\', '/') if shot.blend_file else ''
        shot_uuid = str(uuid.uuid5(self.UUID_NAMESPACE, blend_file_str))

        # Get blend_stem for playblast subfolder lookup
        blend_stem = shot.blend_file.stem if shot.blend_file else None

        return {
            'uuid': shot_uuid,
            'id': shot_uuid,
            'folder_path': str(shot.folder_path),
            'blend_file': str(shot.blend_file),
            'blend_stem': blend_stem,
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
            # Playblast info - populated by _enrich_with_playblasts
            'latest_playblast_path': None,
            'latest_playblast_version': None,
            'playblast_count': 0,
            'thumbnail_path': None,
            # Lookdev info - populated by _enrich_with_lookdevs
            'latest_lookdev_path': None,
            'latest_lookdev_version': None,
            'lookdev_count': 0,
            # Render info - populated by _enrich_with_renders
            'render_proxy_path': None,
            'has_render': False,
            # Preview mode (playblast, lookdev, or render) - default to playblast
            'preview_mode': 'playblast',
            'display_mode': 'playblast',
            # Shot version grouping
            'base_shot_name': shot.identity.base_shot_name,
            'shot_version': shot.identity.shot_version,
            'version_group_id': shot.identity.version_group_id,
            'is_latest_shot_version': shot.identity.is_latest_shot_version,
            'version_count': 1,
            # Multi-camera reference file fields
            'shot_role': shot.identity.shot_role,
            'master_blend_file': shot.identity.master_blend_file,
            'view_name': shot.identity.view_name,
            'master_shot_id': None,  # Resolved by sync_service
            'view_count': 0,
        }

    def _enrich_with_playblasts(
        self,
        shot: DiscoveredShot,
        shot_dict: Dict[str, Any]
    ) -> tuple:
        """
        Enrich shot dict with playblast information.

        Args:
            shot: Original DiscoveredShot
            shot_dict: Shot dict to enrich (modified in-place)

        Returns:
            Tuple of (enriched shot dict, list of DiscoveredPlayblast objects)
        """
        blend_stem = shot_dict.get('blend_stem')
        playblasts = []

        try:
            playblasts = self._playblast_indexer.discover_playblasts(
                shot.folder_path,
                blend_stem
            )

            if playblasts:
                shot_dict['playblast_count'] = len(playblasts)

                # Find latest non-archived playblast
                latest = next((pb for pb in playblasts if pb.is_latest), None)
                if latest:
                    shot_dict['latest_playblast_path'] = str(latest.file_path)
                    shot_dict['latest_playblast_version'] = latest.version
                elif playblasts:
                    # Fall back to first (highest version)
                    shot_dict['latest_playblast_path'] = str(playblasts[0].file_path)
                    shot_dict['latest_playblast_version'] = playblasts[0].version

        except Exception as e:
            pass

        return shot_dict, playblasts

    def _enrich_with_lookdevs(
        self,
        shot: DiscoveredShot,
        shot_dict: Dict[str, Any]
    ) -> tuple:
        """
        Enrich shot dict with lookdev information.

        Args:
            shot: Original DiscoveredShot
            shot_dict: Shot dict to enrich (modified in-place)

        Returns:
            Tuple of (enriched shot dict, list of DiscoveredLookdev objects)
        """
        blend_stem = shot_dict.get('blend_stem')
        lookdevs = []

        try:
            lookdevs = self._lookdev_indexer.discover_lookdevs(
                shot.folder_path,
                blend_stem
            )

            if lookdevs:
                shot_dict['lookdev_count'] = len(lookdevs)

                # Find latest non-archived lookdev
                latest = next((ld for ld in lookdevs if ld.is_latest), None)
                if latest:
                    shot_dict['latest_lookdev_path'] = str(latest.file_path)
                    shot_dict['latest_lookdev_version'] = latest.version
                elif lookdevs:
                    # Fall back to first (highest version)
                    shot_dict['latest_lookdev_path'] = str(lookdevs[0].file_path)
                    shot_dict['latest_lookdev_version'] = lookdevs[0].version

        except Exception as e:
            pass

        return shot_dict, lookdevs

    def _enrich_with_renders(
        self,
        shot: DiscoveredShot,
        shot_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich shot dict with render proxy information.

        Checks for proxy MP4 in Render/ folder (not current/).
        Proxy naming: {shot_name}_RD_v001.mp4

        Args:
            shot: Original DiscoveredShot
            shot_dict: Shot dict to enrich (modified in-place)

        Returns:
            Enriched shot dict
        """
        render_folder = shot.folder_path / "Render"
        render_current = render_folder / "current"
        shot_name = shot_dict.get('shot_name', '')

        # Check if there's a render sequence in current/
        has_render_sequence = render_current.exists() and any(
            f.suffix.lower() in ('.png', '.exr', '.jpg', '.jpeg', '.tif', '.tiff')
            for f in render_current.iterdir() if f.is_file()
        )

        if has_render_sequence:
            shot_dict['has_render'] = True

        # Look for proxy MP4 in Render/ folder (NOT current/)
        # Pattern: {shot_name}_RD_v001.mp4
        if render_folder.exists():
            # First try exact pattern with shot name
            for proxy_file in sorted(render_folder.glob(f"{shot_name}_RD_v*.mp4"), reverse=True):
                shot_dict['render_proxy_path'] = str(proxy_file)
                shot_dict['has_render'] = True
                break
            else:
                # Fallback: any *_RD_v*.mp4 file
                for proxy_file in sorted(render_folder.glob("*_RD_v*.mp4"), reverse=True):
                    shot_dict['render_proxy_path'] = str(proxy_file)
                    shot_dict['has_render'] = True
                    break
                else:
                    # Legacy fallback: proxy.mp4 in current/
                    legacy_proxy = render_current / "proxy.mp4"
                    if legacy_proxy.exists():
                        shot_dict['render_proxy_path'] = str(legacy_proxy)
                        shot_dict['has_render'] = True

        return shot_dict

    def recalculate_latest_flags(self, shot_dicts: List[Dict[str, Any]]) -> None:
        """
        Recalculate is_latest_shot_version among shots with playblasts.

        The shot indexer marks the highest version in each group as "latest",
        but that version might not have playblasts. This method recalculates
        the latest flag among only the shots that will be displayed.

        Args:
            shot_dicts: List of shot dicts to process (modified in-place)
        """
        # Group by version_group_id
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for sd in shot_dicts:
            group_id = sd.get('version_group_id')
            if group_id:
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(sd)

        # For each group, mark only the highest version as latest
        for group_id, group_shots in groups.items():
            if len(group_shots) <= 1:
                if group_shots:
                    group_shots[0]['is_latest_shot_version'] = True
                continue

            # Find highest version among shots
            versioned = [s for s in group_shots if s.get('shot_version') is not None]
            if versioned:
                # Mark all as not latest
                for sd in group_shots:
                    sd['is_latest_shot_version'] = False
                # Mark highest as latest
                latest = max(versioned, key=lambda s: s.get('shot_version', 0))
                latest['is_latest_shot_version'] = True
            else:
                # No versioned shots - mark all as latest
                for sd in group_shots:
                    sd['is_latest_shot_version'] = True


# Singleton instance
_discovery_service: Optional[DiscoveryService] = None


def get_discovery_service() -> DiscoveryService:
    """Get or create the discovery service singleton."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = DiscoveryService()
    return _discovery_service


__all__ = [
    'DiscoveryResult',
    'DiscoveryService',
    'get_discovery_service',
]
