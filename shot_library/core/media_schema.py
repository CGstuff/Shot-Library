"""
Media Schema - Unified schema utilities for all media types.

Consolidates duplicate code from playblast_schema.py and lookdev_schema.py:
- find_project_schema() - 100% identical
- load_project_schema() - 100% identical
- load_metadata_dict() - 100% identical

Enhanced with MediaType-aware functions for unified media handling.

Usage:
    from shot_library.core.media_schema import get_media_config_for_type
    from shot_library.core.media_types import MediaType

    # Get config for a specific media type
    config = get_media_config_for_type(shot_folder, MediaType.PLAYBLAST)

    # Generate filename
    filename = get_media_filename_for_type(MediaType.PLAYBLAST, "shot_010", 1)
    # Returns: "shot_010_PB_v001.mp4"
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .media_types import MediaType

SCHEMA_FILENAME = ".shot_library.json"


def find_project_schema(start_path: Path) -> Optional[Path]:
    """
    Walk up from start_path to find .shot_library.json

    Args:
        start_path: Starting path (file or directory)

    Returns:
        Path to schema file or None if not found
    """
    current = start_path if start_path.is_dir() else start_path.parent
    for _ in range(10):  # Max 10 levels up
        schema_path = current / SCHEMA_FILENAME
        if schema_path.exists():
            return schema_path
        if current.parent == current:
            break
        current = current.parent
    return None


def load_project_schema(start_path: Path, default_schema: Optional[Dict] = None) -> Dict:
    """
    Load project schema or return defaults

    Args:
        start_path: Starting path to search from
        default_schema: Default schema to return if not found (or empty dict)

    Returns:
        Schema dictionary (either loaded or defaults)
    """
    schema_path = find_project_schema(start_path)
    if schema_path:
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return (default_schema.copy() if default_schema else {})


def load_metadata_dict(json_path: Path) -> Optional[dict]:
    """
    Load metadata from JSON file as raw dictionary

    Args:
        json_path: Path to the JSON file

    Returns:
        Metadata dictionary or None if file doesn't exist/is invalid
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def get_metadata_path_for_media(media_path: Path) -> Path:
    """
    Get the companion JSON metadata path for a media file.

    Args:
        media_path: Path to the MP4 file

    Returns:
        Path to the companion JSON file (same name, .json extension)
    """
    return media_path.with_suffix('.json')


def get_media_filename(
    config: Dict,
    blend_name: str,
    version: int,
    default_pattern: str = "{filename}_v{version:03d}"
) -> str:
    """
    Generate media filename using config pattern

    Args:
        config: Configuration dictionary
        blend_name: Name of the blend file (without extension)
        version: Version number
        default_pattern: Default naming pattern

    Returns:
        Complete filename with extension (e.g., "shot_010_PB_v001.mp4")
    """
    pattern = config.get("naming_pattern", default_pattern)
    ext = config.get("file_extension", ".mp4")
    return pattern.format(filename=blend_name, version=version) + ext


def get_metadata_filename(
    config: Dict,
    blend_name: str,
    version: int,
    default_pattern: str = "{filename}_v{version:03d}"
) -> str:
    """
    Generate metadata filename (same as media but .json)

    Args:
        config: Configuration dictionary
        blend_name: Name of the blend file (without extension)
        version: Version number
        default_pattern: Default naming pattern

    Returns:
        JSON filename (e.g., "shot_010_PB_v001.json")
    """
    pattern = config.get("naming_pattern", default_pattern)
    return pattern.format(filename=blend_name, version=version) + ".json"


def get_media_config_for_type(start_path: Path, media_type: 'MediaType') -> Dict[str, Any]:
    """
    Get configuration for a specific media type, merging project schema with defaults.

    Args:
        start_path: Starting path to search for project schema
        media_type: The MediaType to get config for

    Returns:
        Configuration dict with folder_name, archive_folder, naming_pattern, file_extension
    """
    from .media_types import get_media_config

    # Get defaults from MediaType config
    media_config = get_media_config(media_type)
    defaults = {
        'folder_name': media_config.folder_name,
        'archive_folder': media_config.archive_folder,
        'naming_pattern': media_config.naming_pattern,
        'file_extension': media_config.extension,
    }

    # Try to load project schema overrides
    schema = load_project_schema(start_path)
    if schema and media_type.value in schema:
        # Merge schema values over defaults
        project_config = schema[media_type.value]
        defaults.update({k: v for k, v in project_config.items() if v is not None})

    return defaults


def get_media_filename_for_type(
    media_type: 'MediaType',
    blend_name: str,
    version: int,
    start_path: Optional[Path] = None
) -> str:
    """
    Generate media filename for a specific type.

    Args:
        media_type: The MediaType (PLAYBLAST, LOOKDEV, RENDER)
        blend_name: Name of the blend file (without extension)
        version: Version number
        start_path: Optional path to search for project schema

    Returns:
        Complete filename with extension (e.g., "shot_010_PB_v001.mp4")
    """
    from .media_types import get_media_config

    if start_path:
        config = get_media_config_for_type(start_path, media_type)
    else:
        media_config = get_media_config(media_type)
        config = {
            'naming_pattern': media_config.naming_pattern,
            'file_extension': media_config.extension,
        }

    pattern = config['naming_pattern']
    ext = config['file_extension']

    # Replace {prefix} with actual prefix if present
    media_config = get_media_config(media_type)
    formatted = pattern.format(
        filename=blend_name,
        version=version,
        prefix=media_config.prefix
    )

    return formatted + ext


def get_metadata_filename_for_type(
    media_type: 'MediaType',
    blend_name: str,
    version: int,
    start_path: Optional[Path] = None
) -> str:
    """
    Generate metadata filename for a specific type.

    Args:
        media_type: The MediaType (PLAYBLAST, LOOKDEV, RENDER)
        blend_name: Name of the blend file (without extension)
        version: Version number
        start_path: Optional path to search for project schema

    Returns:
        JSON filename (e.g., "shot_010_PB_v001.json")
    """
    media_filename = get_media_filename_for_type(media_type, blend_name, version, start_path)
    return Path(media_filename).stem + ".json"


# ============================================================================
# Generic JSON Metadata Dataclass
# ============================================================================

@dataclass
class GenericJsonMetadata:
    """
    Generic metadata loaded from any media type's companion JSON file.

    This is the unified replacement for PlayblastJsonMetadata and LookdevJsonMetadata.
    Contains all common fields plus a dict for type-specific extra fields.
    """
    version: int
    blend_file: str
    created_at: datetime
    frame_start: int
    frame_end: int
    resolution: Tuple[int, int]
    fps: float
    duration_ms: int
    extra: Dict[str, Any]  # Type-specific fields (quality, render_engine, etc.)


def load_generic_metadata(json_path: Path) -> Optional[GenericJsonMetadata]:
    """
    Load metadata from JSON file as GenericJsonMetadata.

    Args:
        json_path: Path to the JSON file

    Returns:
        GenericJsonMetadata object or None if file doesn't exist/is invalid
    """
    data = load_metadata_dict(json_path)
    if not data:
        return None

    try:
        # Parse created_at as datetime
        created_at_str = data.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            logger.warning(
                "Malformed created_at %r in metadata %s; falling back to now",
                created_at_str, json_path,
            )
            created_at = datetime.now()

        # Common fields
        common_keys = {
            'version', 'blend_file', 'created_at',
            'frame_start', 'frame_end', 'resolution', 'fps', 'duration_ms'
        }

        # Extract extra fields (anything not in common set)
        extra = {k: v for k, v in data.items() if k not in common_keys}

        return GenericJsonMetadata(
            version=data.get("version", 0),
            blend_file=data.get("blend_file", ""),
            created_at=created_at,
            frame_start=data.get("frame_start", 0),
            frame_end=data.get("frame_end", 0),
            resolution=tuple(data.get("resolution", [0, 0])),
            fps=data.get("fps", 0.0),
            duration_ms=data.get("duration_ms", 0),
            extra=extra,
        )
    except Exception:
        return None


__all__ = [
    'SCHEMA_FILENAME',
    'find_project_schema',
    'load_project_schema',
    'load_metadata_dict',
    'get_metadata_path_for_media',
    'get_media_filename',
    'get_metadata_filename',
    # New MediaType-aware functions
    'get_media_config_for_type',
    'get_media_filename_for_type',
    'get_metadata_filename_for_type',
    'GenericJsonMetadata',
    'load_generic_metadata',
]
