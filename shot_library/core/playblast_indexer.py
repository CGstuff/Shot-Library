"""
Playblast Indexer

Discovers and tracks versioned playblast files.
Implements the playblast-indexer contract.

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
from .playblast_schema import (
    get_playblast_config,
    get_metadata_path_for_playblast,
    load_playblast_metadata,
    PlayblastJsonMetadata,
)


# Alias for backwards compatibility
PlayblastMetadata = MediaMetadata


@dataclass
class DiscoveredPlayblast:
    """A playblast file discovered from the filesystem."""
    file_path: Path
    shot_folder: Path
    version: int
    is_latest: bool
    is_archived: bool
    metadata: Optional[PlayblastMetadata]  # Video metadata (from cv2)
    json_metadata: Optional[PlayblastJsonMetadata]  # Render metadata (from JSON)
    created_at: datetime


class PlayblastIndexer(BaseMediaIndexer):
    """
    Discovers and tracks playblast versions in PlayBlast/ folders.

    Read-only: Never creates, modifies, or deletes production files.

    Uses project schema (.shot_library.json) when available to understand
    folder naming and file patterns. Falls back to defaults if no schema found.
    """

    # Signals
    playblast_discovered = pyqtSignal(str, object)  # shot_folder, DiscoveredPlayblast
    playblast_version_added = pyqtSignal(str, int)  # shot_folder, new_version
    playblast_archived = pyqtSignal(str, int)  # shot_folder, version

    def __init__(
        self,
        playblast_folder_name: Optional[str] = None,
        archive_folder_name: Optional[str] = None,
        version_pattern: Optional[str] = None,
        parent=None
    ):
        """
        Initialize indexer with playblast folder naming convention.

        Args:
            playblast_folder_name: Name of playblast subfolder (None = use schema/default)
            archive_folder_name: Name of archive subfolder (None = use schema/default)
            version_pattern: Regex pattern for version filenames
        """
        # Default version pattern - matches formats:
        # - v001.mp4 (old format)
        # - shotname_v001.mp4 (legacy format)
        # - shotname_PB_v001.mp4 (new format with PB suffix)
        default_pattern = r'^(?P<name>.+_)?(PB_)?v(?P<version>\d{3})\.mp4$'
        super().__init__(
            default_folder_name=playblast_folder_name,
            default_archive_name=archive_folder_name,
            version_pattern=version_pattern or default_pattern,
            type_prefix="PB",
            parent=parent
        )

    def _get_config(self, shot_folder: Path) -> Dict:
        """Get playblast config from project schema."""
        return get_playblast_config(shot_folder)

    def _get_metadata_path(self, media_path: Path) -> Path:
        """Get companion JSON metadata path for playblast."""
        return get_metadata_path_for_playblast(media_path)

    def _load_json_metadata(self, json_path: Path) -> Optional[PlayblastJsonMetadata]:
        """Load playblast JSON metadata."""
        return load_playblast_metadata(json_path)

    def _create_discovered_media(
        self,
        file_path: Path,
        shot_folder: Path,
        version: int,
        is_latest: bool,
        is_archived: bool,
        metadata: Optional[MediaMetadata],
        json_metadata: Optional[PlayblastJsonMetadata],
        created_at: datetime
    ) -> DiscoveredPlayblast:
        """Create DiscoveredPlayblast object."""
        return DiscoveredPlayblast(
            file_path=file_path,
            shot_folder=shot_folder,
            version=version,
            is_latest=is_latest,
            is_archived=is_archived,
            metadata=metadata,
            json_metadata=json_metadata,
            created_at=created_at
        )

    # Convenience methods with playblast-specific names
    def discover_playblasts(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> List[DiscoveredPlayblast]:
        """
        Find all playblasts for a shot version.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            List of playblasts sorted by version (descending)
        """
        return self.discover_media(shot_folder, blend_stem)

    def get_latest_playblast(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> Optional[DiscoveredPlayblast]:
        """
        Get the most recent (highest version) playblast for a shot version.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            Latest playblast or None if no playblasts exist
        """
        return self.get_latest(shot_folder, blend_stem)


__all__ = [
    'PlayblastMetadata',
    'PlayblastJsonMetadata',
    'DiscoveredPlayblast',
    'PlayblastIndexer',
]
