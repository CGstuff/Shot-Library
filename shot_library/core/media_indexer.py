"""
Media Indexer - Unified indexer for all media types (playblast, lookdev, render).

This module consolidates the previously duplicated PlayblastIndexer and LookdevIndexer
into a single generic implementation that uses MediaType configuration.

The old indexers are kept for backwards compatibility but now delegate to this implementation.

Usage:
    from shot_library.core.media_indexer import MediaIndexer
    from shot_library.core.media_types import MediaType

    # Create indexer for playblasts
    pb_indexer = MediaIndexer(MediaType.PLAYBLAST)
    playblasts = pb_indexer.discover_media(shot_folder)

    # Create indexer for lookdevs
    ld_indexer = MediaIndexer(MediaType.LOOKDEV)
    lookdevs = ld_indexer.discover_media(shot_folder)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, TypeVar, Generic

logger = logging.getLogger(__name__)
import re

from PyQt6.QtCore import QObject, pyqtSignal

from .media_types import MediaType, MediaConfig, get_media_config


@dataclass
class MediaMetadata:
    """
    Base metadata extracted from a video file using cv2.

    This is video-level metadata extracted directly from the file,
    separate from JSON sidecar metadata written at render time.
    """
    duration_ms: int
    fps: float
    width: int
    height: int
    frame_count: int


@dataclass
class DiscoveredMedia:
    """
    A media file discovered from the filesystem.

    Generic representation that works for all media types.
    """
    file_path: Path
    shot_folder: Path
    version: int
    is_latest: bool
    is_archived: bool
    metadata: Optional[MediaMetadata]  # Video metadata (from cv2)
    json_metadata: Optional[Dict[str, Any]]  # Render metadata (from JSON sidecar)
    created_at: datetime
    media_type: MediaType


# Type variable for subclass return types
T = TypeVar('T', bound=DiscoveredMedia)


class MediaIndexer(QObject):
    """
    Unified indexer for discovering versioned media files.

    Read-only: Never creates, modifies, or deletes production files.

    Uses MediaType configuration to parameterize behavior for different
    media types (playblast, lookdev, render).

    Signals:
        media_discovered: Emitted when a media file is found (shot_folder, DiscoveredMedia)
        version_added: Emitted when a new version is detected (shot_folder, version)
        media_archived: Emitted when media is archived (shot_folder, version)
    """

    # Generic signals that work for any media type
    media_discovered = pyqtSignal(str, object)  # shot_folder, DiscoveredMedia
    version_added = pyqtSignal(str, int)  # shot_folder, new_version
    media_archived = pyqtSignal(str, int)  # shot_folder, version

    def __init__(
        self,
        media_type: MediaType,
        folder_name_override: Optional[str] = None,
        archive_name_override: Optional[str] = None,
        version_pattern_override: Optional[str] = None,
        parent=None
    ):
        """
        Initialize indexer for a specific media type.

        Args:
            media_type: The MediaType to index (PLAYBLAST, LOOKDEV, RENDER)
            folder_name_override: Override default folder name from config
            archive_name_override: Override default archive folder name
            version_pattern_override: Override default version regex pattern
            parent: Qt parent object
        """
        super().__init__(parent)

        self._media_type = media_type
        self._config = get_media_config(media_type)

        # Allow overrides but default to config
        self._folder_name = folder_name_override or self._config.folder_name
        self._archive_name = archive_name_override or self._config.archive_folder
        self._version_pattern = re.compile(
            version_pattern_override or self._config.version_pattern
        )

    @property
    def media_type(self) -> MediaType:
        """Get the media type this indexer handles."""
        return self._media_type

    @property
    def config(self) -> MediaConfig:
        """Get the configuration for this media type."""
        return self._config

    def discover_media(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> List[DiscoveredMedia]:
        """
        Find all media files for a shot.

        Uses project schema to determine folder names and file patterns.
        Reads companion JSON metadata when available.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem (e.g., "SH0010_v002") to find
                        media in the version-specific subfolder.
                        If provided, looks in {folder_name}/{blend_stem}/
                        If None, looks in {folder_name}/ root (legacy fallback)

        Returns:
            List of discovered media sorted by version (descending)

        Raises:
            FileNotFoundError: If shot_folder doesn't exist
        """
        shot_folder = Path(shot_folder) if not isinstance(shot_folder, Path) else shot_folder

        if not shot_folder.exists():
            raise FileNotFoundError(f"Shot folder does not exist: {shot_folder}")

        # Get schema config if available (for project-specific overrides)
        folder_config = self._get_folder_config(shot_folder)
        folder_name = folder_config.get('folder_name', self._folder_name)
        archive_name = folder_config.get('archive_folder', self._archive_name)
        file_ext = folder_config.get('file_extension', self._config.extension)

        # Determine media folder path
        if blend_stem:
            media_folder = shot_folder / folder_name / blend_stem
            if not media_folder.exists():
                media_folder = shot_folder / folder_name
        else:
            media_folder = shot_folder / folder_name

        if not media_folder.exists():
            return []

        discovered: List[DiscoveredMedia] = []

        # Find media in main folder (non-archived)
        for media_file in media_folder.glob(f'*{file_ext}'):
            version = self._parse_version(media_file.name)
            if version is not None:
                json_path = self._get_metadata_path(media_file)
                json_metadata = self._load_json_metadata(json_path) if json_path.exists() else None

                discovered.append(DiscoveredMedia(
                    file_path=media_file,
                    shot_folder=shot_folder,
                    version=version,
                    is_latest=False,
                    is_archived=False,
                    metadata=self._extract_video_metadata(media_file),
                    json_metadata=json_metadata,
                    created_at=datetime.fromtimestamp(media_file.stat().st_mtime),
                    media_type=self._media_type,
                ))

        # Find archived media
        archive_folder = media_folder / archive_name
        if archive_folder.exists():
            for media_file in archive_folder.glob(f'*{file_ext}'):
                version = self._parse_version(media_file.name)
                if version is not None:
                    json_path = self._get_metadata_path(media_file)
                    json_metadata = self._load_json_metadata(json_path) if json_path.exists() else None

                    discovered.append(DiscoveredMedia(
                        file_path=media_file,
                        shot_folder=shot_folder,
                        version=version,
                        is_latest=False,
                        is_archived=True,
                        metadata=self._extract_video_metadata(media_file),
                        json_metadata=json_metadata,
                        created_at=datetime.fromtimestamp(media_file.stat().st_mtime),
                        media_type=self._media_type,
                    ))

        # Sort by version descending
        discovered.sort(key=lambda m: m.version, reverse=True)

        # Mark highest non-archived version as latest
        if discovered:
            non_archived = [m for m in discovered if not m.is_archived]
            if non_archived:
                non_archived[0].is_latest = True

        return discovered

    def get_latest(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> Optional[DiscoveredMedia]:
        """
        Get the most recent (highest version) media for a shot.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            Latest media or None if no media exist
        """
        media_list = self.discover_media(shot_folder, blend_stem)

        if not media_list:
            return None

        # Return first non-archived, or first overall
        for m in media_list:
            if not m.is_archived:
                return m

        return media_list[0]

    def get_version_lineage(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> List[DiscoveredMedia]:
        """
        Get complete version history for a shot's media.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            List of all versions including archived, sorted chronologically (oldest first)
        """
        media_list = self.discover_media(shot_folder, blend_stem)
        # Sort by version ascending (oldest first)
        media_list.sort(key=lambda m: m.version)
        return media_list

    def _get_folder_config(self, shot_folder: Path) -> Dict[str, Any]:
        """
        Get folder configuration, preferring project schema.

        Looks for .shot_library.json in shot folder and parent directories.

        Args:
            shot_folder: Path to shot folder

        Returns:
            Dict with folder_name, archive_folder, and file_extension keys
        """
        # Try to load project schema
        from .media_schema import load_project_schema

        schema = load_project_schema(shot_folder)
        media_key = self._media_type.value  # "playblast", "lookdev", "render"

        if schema and media_key in schema:
            return schema[media_key]

        # Return defaults from config
        return {
            'folder_name': self._folder_name,
            'archive_folder': self._archive_name,
            'file_extension': self._config.extension,
        }

    def _get_metadata_path(self, media_path: Path) -> Path:
        """
        Get the companion JSON metadata path for a media file.

        Args:
            media_path: Path to the media file

        Returns:
            Path to the companion JSON file (same name, .json extension)
        """
        return media_path.with_suffix('.json')

    def _load_json_metadata(self, json_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load metadata from JSON sidecar file.

        Args:
            json_path: Path to the JSON file

        Returns:
            Metadata dict or None if file doesn't exist/is invalid
        """
        try:
            import json
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _extract_video_metadata(self, media_path: Path) -> Optional[MediaMetadata]:
        """
        Extract video metadata from a media file.

        Uses opencv-python to read video properties.

        Args:
            media_path: Path to video file

        Returns:
            MediaMetadata or None if extraction fails
        """
        # Skip for image sequences
        if self._config.extension in ('.png', '.jpg', '.exr'):
            return None

        try:
            import cv2

            cap = cv2.VideoCapture(str(media_path))
            if not cap.isOpened():
                return None

            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Calculate duration
            duration_ms = int((frame_count / fps) * 1000) if fps > 0 else 0

            cap.release()

            return MediaMetadata(
                duration_ms=duration_ms,
                fps=fps,
                width=width,
                height=height,
                frame_count=frame_count
            )

        except ImportError:
            logger.warning("OpenCV not available; cannot extract video metadata")
            return None
        except Exception:
            logger.warning("Failed to extract metadata from %s", media_path, exc_info=True)
            return None

    def _parse_version(self, filename: str) -> Optional[int]:
        """
        Parse version number from filename.

        Args:
            filename: Media filename

        Returns:
            Version number or None if unparseable
        """
        match = self._version_pattern.match(filename)
        if match:
            try:
                return int(match.group('version'))
            except (ValueError, IndexError):
                pass

        # Fallback: try to extract any number
        numbers = re.findall(r'\d+', filename)
        if numbers:
            try:
                return int(numbers[-1])
            except ValueError:
                pass

        return None


# Factory functions for convenience
def create_playblast_indexer(parent=None) -> MediaIndexer:
    """Create an indexer for playblast media."""
    return MediaIndexer(MediaType.PLAYBLAST, parent=parent)


def create_lookdev_indexer(parent=None) -> MediaIndexer:
    """Create an indexer for lookdev media."""
    return MediaIndexer(MediaType.LOOKDEV, parent=parent)


def create_render_indexer(parent=None) -> MediaIndexer:
    """Create an indexer for render media."""
    return MediaIndexer(MediaType.RENDER, parent=parent)


__all__ = [
    'MediaMetadata',
    'DiscoveredMedia',
    'MediaIndexer',
    'create_playblast_indexer',
    'create_lookdev_indexer',
    'create_render_indexer',
]
