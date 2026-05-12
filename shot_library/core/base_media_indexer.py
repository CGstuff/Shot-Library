"""
Base Media Indexer

Shared base class for PlayblastIndexer and LookdevIndexer.
Consolidates ~95% identical code between the two indexers.

Uses project schema (.shot_library.json) to understand:
- Folder naming conventions
- File naming patterns
- Reads companion JSON metadata for render-time info

Note: For new code, prefer using MediaIndexer from media_indexer.py which
uses the MediaType abstraction from media_types.py. This base class is
maintained for backwards compatibility with existing PlayblastIndexer and
LookdevIndexer implementations.

See Also:
    media_types.py - MediaType enum and MediaConfig for unified configuration
    media_indexer.py - Generic MediaIndexer that uses MediaType
"""

import logging
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Generic, TypeVar
import re

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.sip import wrappertype

logger = logging.getLogger(__name__)


@dataclass
class MediaMetadata:
    """Base metadata extracted from a video file using cv2."""
    duration_ms: int
    fps: float
    width: int
    height: int
    frame_count: int


# Type variable for discovered media (DiscoveredPlayblast or DiscoveredLookdev)
T = TypeVar('T')


# Combined metaclass for QObject and ABC
class QObjectABCMeta(wrappertype, ABCMeta):
    """Metaclass that combines QObject's metaclass with ABCMeta."""
    pass


class BaseMediaIndexer(QObject, ABC, metaclass=QObjectABCMeta):
    """
    Base class for media indexers (playblast and lookdev).

    Read-only: Never creates, modifies, or deletes production files.

    Uses project schema (.shot_library.json) when available to understand
    folder naming and file patterns. Falls back to defaults if no schema found.
    """

    # Subclasses should define their own signals with appropriate names
    # e.g., playblast_discovered, lookdev_discovered

    def __init__(
        self,
        default_folder_name: Optional[str] = None,
        default_archive_name: Optional[str] = None,
        version_pattern: Optional[str] = None,
        type_prefix: str = "PB",
        parent=None
    ):
        """
        Initialize indexer with folder naming convention.

        Args:
            default_folder_name: Name of media subfolder (None = use schema/default)
            default_archive_name: Name of archive subfolder (None = use schema/default)
            version_pattern: Regex pattern for version filenames
            type_prefix: "PB" for playblast, "LD" for lookdev
        """
        super().__init__(parent)
        self._default_folder_name = default_folder_name
        self._default_archive_name = default_archive_name
        self._type_prefix = type_prefix

        # Default version pattern - matches formats:
        # - v001.mp4 (old format)
        # - shotname_v001.mp4 (legacy format)
        # - shotname_PB_v001.mp4 or shotname_LD_v001.mp4 (new format)
        default_pattern = rf'^(?P<name>.+_)?({type_prefix}_)?v(?P<version>\d{{3}})\.mp4$'
        self.version_pattern = re.compile(version_pattern or default_pattern)

    @abstractmethod
    def _get_config(self, shot_folder: Path) -> Dict:
        """Get config from project schema. Implemented by subclasses."""
        pass

    @abstractmethod
    def _get_metadata_path(self, media_path: Path) -> Path:
        """Get companion JSON metadata path. Implemented by subclasses."""
        pass

    @abstractmethod
    def _load_json_metadata(self, json_path: Path):
        """Load JSON metadata. Returns type-specific metadata object."""
        pass

    @abstractmethod
    def _create_discovered_media(
        self,
        file_path: Path,
        shot_folder: Path,
        version: int,
        is_latest: bool,
        is_archived: bool,
        metadata: Optional[MediaMetadata],
        json_metadata,
        created_at: datetime
    ):
        """Create type-specific discovered media object."""
        pass

    def _get_folder_config(self, shot_folder: Path) -> Dict:
        """
        Get folder configuration, preferring project schema.

        Args:
            shot_folder: Path to shot folder

        Returns:
            Dict with folder_name, archive_folder, and file_extension keys
        """
        config = self._get_config(shot_folder)

        # Use MediaType config as fallback if available
        try:
            from .media_types import get_media_type_by_prefix, get_media_config
            media_type = get_media_type_by_prefix(self._type_prefix)
            if media_type:
                media_config = get_media_config(media_type)
                default_folder = media_config.folder_name
                default_archive = media_config.archive_folder
                default_ext = media_config.extension
            else:
                # Legacy fallback
                default_folder = "PlayBlast" if self._type_prefix == "PB" else "Lookdev"
                default_archive = "_archive"
                default_ext = ".mp4"
        except ImportError:
            # media_types not available, use legacy defaults
            default_folder = "PlayBlast" if self._type_prefix == "PB" else "Lookdev"
            default_archive = "_archive"
            default_ext = ".mp4"

        return {
            'folder_name': self._default_folder_name or config.get("folder_name", default_folder),
            'archive_folder': self._default_archive_name or config.get("archive_folder", default_archive),
            'file_extension': config.get("file_extension", default_ext),
        }

    def discover_media(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> List:
        """
        Find all media files for a shot version.

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

        config = self._get_folder_config(shot_folder)
        folder_name = config['folder_name']
        archive_name = config['archive_folder']
        file_ext = config['file_extension']

        # Determine media folder path
        if blend_stem:
            media_folder = shot_folder / folder_name / blend_stem
            if not media_folder.exists():
                media_folder = shot_folder / folder_name
        else:
            media_folder = shot_folder / folder_name

        if not media_folder.exists():
            return []

        discovered: List = []

        # Find media in main folder (non-archived)
        for mp4_file in media_folder.glob(f'*{file_ext}'):
            version = self._parse_version(mp4_file.name)
            if version is not None:
                json_path = self._get_metadata_path(mp4_file)
                json_metadata = self._load_json_metadata(json_path) if json_path.exists() else None

                discovered.append(self._create_discovered_media(
                    file_path=mp4_file,
                    shot_folder=shot_folder,
                    version=version,
                    is_latest=False,
                    is_archived=False,
                    metadata=self.extract_metadata(mp4_file),
                    json_metadata=json_metadata,
                    created_at=datetime.fromtimestamp(mp4_file.stat().st_mtime)
                ))

        # Find archived media
        archive_folder = media_folder / archive_name
        if archive_folder.exists():
            for mp4_file in archive_folder.glob(f'*{file_ext}'):
                version = self._parse_version(mp4_file.name)
                if version is not None:
                    json_path = self._get_metadata_path(mp4_file)
                    json_metadata = self._load_json_metadata(json_path) if json_path.exists() else None

                    discovered.append(self._create_discovered_media(
                        file_path=mp4_file,
                        shot_folder=shot_folder,
                        version=version,
                        is_latest=False,
                        is_archived=True,
                        metadata=self.extract_metadata(mp4_file),
                        json_metadata=json_metadata,
                        created_at=datetime.fromtimestamp(mp4_file.stat().st_mtime)
                    ))

        # Sort by version descending
        discovered.sort(key=lambda p: p.version, reverse=True)

        # Mark highest non-archived version as latest
        if discovered:
            non_archived = [p for p in discovered if not p.is_archived]
            if non_archived:
                non_archived[0].is_latest = True

        return discovered

    def get_latest(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ):
        """
        Get the most recent (highest version) media for a shot version.

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

    def extract_metadata(self, media_path: Path) -> Optional[MediaMetadata]:
        """
        Extract video metadata from a media file.

        Uses opencv-python to read video properties.

        Args:
            media_path: Path to MP4 file

        Returns:
            Metadata or None if extraction fails
        """
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

    def get_version_lineage(
        self,
        shot_folder: Path,
        blend_stem: Optional[str] = None
    ) -> List:
        """
        Get complete version history for a shot version's media.

        Args:
            shot_folder: Path to shot folder
            blend_stem: Optional blend file stem for version-specific lookup

        Returns:
            List of all versions including archived, sorted chronologically
        """
        media_list = self.discover_media(shot_folder, blend_stem)
        # Sort by version ascending (oldest first)
        media_list.sort(key=lambda p: p.version)
        return media_list

    def _parse_version(self, filename: str) -> Optional[int]:
        """
        Parse version number from filename.

        Args:
            filename: Media filename

        Returns:
            Version number or None if unparseable
        """
        match = self.version_pattern.match(filename)
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


__all__ = [
    'MediaMetadata',
    'BaseMediaIndexer',
]
