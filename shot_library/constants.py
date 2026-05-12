"""
Shot Library Constants - Single source of truth for magic strings and values.

This module centralizes all constants that were previously scattered across
15+ files, reducing duplication and making it easy to update values consistently.

Usage:
    from shot_library.constants import MediaConstants, VersionConstants, StatusConstants

    # Media folder names
    playblast_folder = MediaConstants.PLAYBLAST_FOLDER  # "PlayBlast"

    # Version formatting
    version_str = VersionConstants.format(3)  # "v003"

    # Status values
    if status in StatusConstants.ALL:
        ...
"""

from typing import Final, Tuple


class MediaConstants:
    """
    Constants for media folders and file naming.

    These are the default values used when no project schema (.shot_library.json)
    is present. Projects can override these via schema.
    """

    # Folder names (case-sensitive, used for folder creation/lookup)
    PLAYBLAST_FOLDER: Final[str] = "PlayBlast"
    LOOKDEV_FOLDER: Final[str] = "Lookdev"
    RENDER_FOLDER: Final[str] = "Render"
    ARCHIVE_FOLDER: Final[str] = "_archive"

    # File prefixes (used in filenames like "shot_010_PB_v001.mp4")
    PLAYBLAST_PREFIX: Final[str] = "PB"
    LOOKDEV_PREFIX: Final[str] = "LD"
    RENDER_PREFIX: Final[str] = "RD"

    # File extensions
    VIDEO_EXTENSION: Final[str] = ".mp4"
    IMAGE_EXTENSION: Final[str] = ".png"
    METADATA_EXTENSION: Final[str] = ".json"

    # Schema filename
    PROJECT_SCHEMA_FILE: Final[str] = ".shot_library.json"


class VersionConstants:
    """
    Constants for version numbering and formatting.
    """

    # Version format (3 digits, zero-padded)
    FORMAT: Final[str] = "v{:03d}"
    DIGITS: Final[int] = 3

    # Regex pattern for extracting version number
    # Matches: v001, v123, etc.
    PATTERN: Final[str] = r"v(\d{3})"

    # Full filename patterns for each media type
    PLAYBLAST_PATTERN: Final[str] = r'^(?P<name>.+_)?(PB_)?v(?P<version>\d{3})\.mp4$'
    LOOKDEV_PATTERN: Final[str] = r'^(?P<name>.+_)?(LD_)?v(?P<version>\d{3})\.mp4$'
    RENDER_PATTERN: Final[str] = r'^(?P<name>.+_)?(RD_)?v(?P<version>\d{3})(_\d+)?\.png$'

    @staticmethod
    def format(version: int) -> str:
        """
        Format a version number as a string.

        Args:
            version: Version number (1, 2, 3, etc.)

        Returns:
            Formatted string like "v001", "v002", "v003"
        """
        return f"v{version:03d}"

    @staticmethod
    def parse(version_str: str) -> int:
        """
        Parse a version string to an integer.

        Args:
            version_str: String like "v001" or just "001"

        Returns:
            Version number as integer

        Raises:
            ValueError: If string cannot be parsed
        """
        import re
        match = re.search(r'(\d+)', version_str)
        if match:
            return int(match.group(1))
        raise ValueError(f"Cannot parse version from: {version_str}")


class StatusConstants:
    """
    Constants for shot production status values.

    These match Pipeline Control's status values for integration.
    """

    # Individual status values
    WIP: Final[str] = "WIP"
    IN_REVIEW: Final[str] = "In Review"
    NEEDS_WORK: Final[str] = "Needs Work"
    APPROVED: Final[str] = "Approved"
    FINAL: Final[str] = "Final"
    BLOCKED: Final[str] = "Blocked"

    # All valid statuses (for validation)
    ALL: Final[Tuple[str, ...]] = (
        WIP,
        IN_REVIEW,
        NEEDS_WORK,
        APPROVED,
        FINAL,
        BLOCKED,
    )

    # Status colors (for UI display)
    COLORS: Final[dict] = {
        WIP: "#FF9800",        # Orange
        IN_REVIEW: "#2196F3",   # Blue
        NEEDS_WORK: "#FFC107",  # Yellow/Amber
        APPROVED: "#4CAF50",    # Green
        FINAL: "#9C27B0",       # Purple
        BLOCKED: "#F44336",     # Red
    }

    @classmethod
    def is_valid(cls, status: str) -> bool:
        """Check if a status value is valid."""
        return status in cls.ALL

    @classmethod
    def get_color(cls, status: str) -> str:
        """Get the color for a status value."""
        return cls.COLORS.get(status, "#808080")  # Gray default


class ShotRoleConstants:
    """
    Constants for shot role values (multi-camera support).
    """

    STANDALONE: Final[str] = "standalone"
    MASTER: Final[str] = "master"
    VIEW: Final[str] = "view"

    ALL: Final[Tuple[str, ...]] = (STANDALONE, MASTER, VIEW)


class DisplayModeConstants:
    """
    Constants for display mode (preview type).
    """

    PLAYBLAST: Final[str] = "playblast"
    LOOKDEV: Final[str] = "lookdev"

    ALL: Final[Tuple[str, ...]] = (PLAYBLAST, LOOKDEV)


class FolderConstants:
    """
    Constants for special folder names.
    """

    # Metadata and cache folders
    META_FOLDER: Final[str] = ".meta"
    CACHE_FOLDER: Final[str] = ".cache"
    QUEUE_FOLDER: Final[str] = ".queue"

    # Database files
    DATABASE_FILE: Final[str] = "database.db"
    REVIEW_DATABASE_FILE: Final[str] = "reviews.db"


class TimeFormatConstants:
    """
    Constants for time display format in review notes.
    """

    FRAME: Final[str] = "frame"        # Display as "f125"
    TIMECODE: Final[str] = "timecode"  # Display as "00:05:04"

    @staticmethod
    def format_frame(frame: int, fps: float = 24.0, use_timecode: bool = False) -> str:
        """
        Format a frame number as a display string.

        Args:
            frame: Frame number
            fps: Frames per second (for timecode conversion)
            use_timecode: If True, format as timecode; otherwise as frame number

        Returns:
            Formatted string like "f125" or "00:05:04"
        """
        if use_timecode and fps > 0:
            total_seconds = frame / fps
            minutes = int(total_seconds // 60)
            seconds = int(total_seconds % 60)

            if minutes >= 60:
                hours = minutes // 60
                minutes = minutes % 60
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                return f"{minutes:02d}:{seconds:02d}"
        else:
            return f"f{frame}"


__all__ = [
    'MediaConstants',
    'VersionConstants',
    'StatusConstants',
    'ShotRoleConstants',
    'DisplayModeConstants',
    'FolderConstants',
    'TimeFormatConstants',
]
