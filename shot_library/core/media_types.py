"""
Media Types - Unified abstraction for playblast, lookdev, and render media.

This module provides a single source of truth for media type configuration,
enabling the addition of new media types (like Render) without duplicating
indexer and schema code.

Usage:
    from shot_library.core.media_types import MediaType, get_media_config

    # Get config for a media type
    config = get_media_config(MediaType.PLAYBLAST)
    print(config.folder_name)  # "PlayBlast"
    print(config.prefix)       # "PB"

    # Iterate all media types
    for media_type in MediaType:
        config = get_media_config(media_type)
        print(f"{media_type.value}: {config.folder_name}")
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


class MediaType(Enum):
    """
    Enumeration of supported media types.

    Each type has associated configuration for folder names,
    file naming patterns, and metadata structure.
    """
    PLAYBLAST = "playblast"
    LOOKDEV = "lookdev"
    RENDER = "render"  # Future: image sequence renders


@dataclass(frozen=True)
class MediaConfig:
    """
    Configuration for a media type.

    Immutable configuration that defines how a media type is organized
    on disk and named in files.

    Attributes:
        media_type: The MediaType this config is for
        folder_name: Subfolder name under shot folder (e.g., "PlayBlast")
        prefix: Short prefix for filenames (e.g., "PB")
        extension: Default file extension (e.g., ".mp4")
        version_pattern: Regex pattern for extracting version from filename
        archive_folder: Name of archive subfolder (default: "_archive")
        naming_pattern: Format string for generating filenames
        extra_metadata_fields: Additional fields in JSON metadata (beyond common ones)
    """
    media_type: MediaType
    folder_name: str
    prefix: str
    extension: str
    version_pattern: str
    archive_folder: str = "_archive"
    naming_pattern: str = "{filename}_{prefix}_v{version:03d}"
    extra_metadata_fields: Tuple[str, ...] = ()


# Central registry of media type configurations
_MEDIA_CONFIGS: Dict[MediaType, MediaConfig] = {
    MediaType.PLAYBLAST: MediaConfig(
        media_type=MediaType.PLAYBLAST,
        folder_name="PlayBlast",
        prefix="PB",
        extension=".mp4",
        version_pattern=r'^(?P<name>.+_)?(PB_)?v(?P<version>\d{3})\.mp4$',
        archive_folder="_archive",
        naming_pattern="{filename}_PB_v{version:03d}",
        extra_metadata_fields=("quality",),
    ),
    MediaType.LOOKDEV: MediaConfig(
        media_type=MediaType.LOOKDEV,
        folder_name="Lookdev",
        prefix="LD",
        extension=".mp4",
        version_pattern=r'^(?P<name>.+_)?(LD_)?v(?P<version>\d{3})\.mp4$',
        archive_folder="_archive",
        naming_pattern="{filename}_LD_v{version:03d}",
        extra_metadata_fields=("render_engine", "samples", "render_time_seconds"),
    ),
    MediaType.RENDER: MediaConfig(
        media_type=MediaType.RENDER,
        folder_name="Render",
        prefix="RD",
        extension=".png",  # Image sequences
        version_pattern=r'^(?P<name>.+_)?(RD_)?v(?P<version>\d{3})(_\d+)?\.png$',
        archive_folder="_archive",
        naming_pattern="{filename}_RD_v{version:03d}",
        extra_metadata_fields=("render_engine", "samples", "render_time_seconds", "frame_padding"),
    ),
}


def get_media_config(media_type: MediaType) -> MediaConfig:
    """
    Get configuration for a media type.

    Args:
        media_type: The MediaType to get config for

    Returns:
        MediaConfig with all settings for that type

    Raises:
        KeyError: If media_type is not configured
    """
    return _MEDIA_CONFIGS[media_type]


def get_all_media_configs() -> Dict[MediaType, MediaConfig]:
    """
    Get all media type configurations.

    Returns:
        Dict mapping MediaType to MediaConfig
    """
    return _MEDIA_CONFIGS.copy()


def get_media_type_by_folder(folder_name: str) -> Optional[MediaType]:
    """
    Look up MediaType by folder name.

    Args:
        folder_name: Folder name like "PlayBlast" or "Lookdev"

    Returns:
        MediaType if found, None otherwise
    """
    for media_type, config in _MEDIA_CONFIGS.items():
        if config.folder_name.lower() == folder_name.lower():
            return media_type
    return None


def get_media_type_by_prefix(prefix: str) -> Optional[MediaType]:
    """
    Look up MediaType by file prefix.

    Args:
        prefix: File prefix like "PB" or "LD"

    Returns:
        MediaType if found, None otherwise
    """
    for media_type, config in _MEDIA_CONFIGS.items():
        if config.prefix.upper() == prefix.upper():
            return media_type
    return None


# Common metadata fields shared across all media types
COMMON_METADATA_FIELDS = (
    "version",
    "blend_file",
    "created_at",
    "frame_start",
    "frame_end",
    "resolution",
    "fps",
    "duration_ms",
)


__all__ = [
    'MediaType',
    'MediaConfig',
    'get_media_config',
    'get_all_media_configs',
    'get_media_type_by_folder',
    'get_media_type_by_prefix',
    'COMMON_METADATA_FIELDS',
]
