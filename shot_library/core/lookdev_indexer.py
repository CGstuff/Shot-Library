"""
Lookdev Indexer

Discovers and tracks versioned lookdev render files.
Implements the lookdev-indexer contract parallel to playblast-indexer.

Uses project schema (.shot_library.json) to understand:
- Folder naming conventions
- File naming patterns
- Reads companion JSON metadata for render-time info
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from PyQt6.QtCore import pyqtSignal

from .base_media_indexer import BaseMediaIndexer, MediaMetadata
from .lookdev_schema import (
    get_lookdev_config,
    get_metadata_path_for_lookdev,
    load_lookdev_metadata,
    LookdevJsonMetadata,
)


# Alias for backwards compatibility
LookdevMetadata = MediaMetadata


@dataclass
class DiscoveredLookdev:
    """A lookdev render file discovered from the filesystem."""
    file_path: Path
    shot_folder: Path
    version: int
    is_latest: bool
    is_archived: bool
    metadata: Optional[LookdevMetadata]  # Video metadata (from cv2)
    json_metadata: Optional[LookdevJsonMetadata]  # Render metadata (from JSON)
    created_at: datetime


class LookdevIndexer(BaseMediaIndexer):
    """
    Discovers and tracks lookdev versions in Lookdev/ folders.

    Read-only: Never creates, modifies, or deletes production files.

    Uses project schema (.shot_library.json) when available to understand
    folder naming and file patterns. Falls back to defaults if no schema found.
    """

    # Signals
    lookdev_discovered = pyqtSignal(str, object)  # shot_folder, DiscoveredLookdev
    lookdev_version_added = pyqtSignal(str, int)  # shot_folder, new_version
    lookdev_archived = pyqtSignal(str, int)  # shot_folder, version

    def __init__(
        self,
        lookdev_folder_name: Optional[str] = None,
        archive_folder_name: Optional[str] = None,
        version_pattern: Optional[str] = None,
        parent=None
    ):
        """
        Initialize indexer with lookdev folder naming convention.

        Args:
            lookdev_folder_name: Name of lookdev subfolder (None = use schema/default)
            archive_folder_name: Name of archive subfolder (None = use schema/default)
            version_pattern: Regex pattern for version filenames
        """
        # Default version pattern - matches formats:
        # - v001.mp4 (old format)
        # - shotname_v001.mp4 (legacy format)
        # - shotname_LD_v001.mp4 (new format with LD suffix)
        default_pattern = r'^(?P<name>.+_)?(LD_)?v(?P<version>\d{3})\.mp4$'
        super().__init__(
            default_folder_name=lookdev_folder_name,
            default_archive_name=archive_folder_name,
            version_pattern=version_pattern or default_pattern,
            type_prefix="LD",
            parent=parent
        )

    def _get_config(self, shot_folder: Path) -> Dict:
        """Get lookdev config from project schema."""
        return get_lookdev_config(shot_folder)

    def _get_metadata_path(self, media_path: Path) -> Path:
        """Get companion JSON metadata path for lookdev."""
        return get_metadata_path_for_lookdev(media_path)

    def _load_json_metadata(self, json_path: Path) -> Optional[LookdevJsonMetadata]:
        """Load lookdev JSON metadata."""
        return load_lookdev_metadata(json_path)

    def _create_discovered_media(
        self,
        file_path: Path,
        shot_folder: Path,
        version: int,
        is_latest: bool,
        is_archived: bool,
        metadata: Optional[MediaMetadata],
        json_metadata: Optional[LookdevJsonMetadata],
        created_at: datetime
    ) -> DiscoveredLookdev:
        """Create DiscoveredLookdev object."""
        return DiscoveredLookdev(
            file_path=file_path,
            shot_folder=shot_folder,
            version=version,
            is_latest=is_latest,
            is_archived=is_archived,
            metadata=metadata,
            json_metadata=json_metadata,
            created_at=created_at
        )

    # Convenience methods with lookdev-specific names
    def discover_lookdevs(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> List[DiscoveredLookdev]:
        """
        Find all lookdev renders for a shot version.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            List of lookdevs sorted by version (descending)
        """
        return self.discover_media(shot_folder, blend_stem)

    def get_latest_lookdev(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> Optional[DiscoveredLookdev]:
        """
        Get the most recent (highest version) lookdev for a shot version.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            Latest lookdev or None if no lookdevs exist
        """
        return self.get_latest(shot_folder, blend_stem)


__all__ = [
    'LookdevMetadata',
    'LookdevJsonMetadata',
    'DiscoveredLookdev',
    'LookdevIndexer',
]
