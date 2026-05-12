"""
Playblast schema reader + metadata utilities for Desktop App

Handles the two levels of configuration:
1. Project Schema (.shot_library.json) - Lives at project root, defines conventions
2. Playblast Metadata (per-file .json) - Lives next to each MP4, contains render-time metadata

This is the desktop app mirror of SL_blender_plugin/utils/playblast_schema.py
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

from .media_schema import (
    SCHEMA_FILENAME,
    find_project_schema,
    load_project_schema,
    load_metadata_dict,
    get_metadata_path_for_media,
    get_media_filename,
    get_metadata_filename as _get_metadata_filename,
)

# Re-export for backwards compatibility
__all__ = [
    'SCHEMA_FILENAME',
    'DEFAULT_SCHEMA',
    'PlayblastJsonMetadata',
    'find_project_schema',
    'load_project_schema',
    'get_playblast_config',
    'get_playblast_filename',
    'get_metadata_filename',
    'get_metadata_path_for_playblast',
    'load_playblast_metadata',
    'load_playblast_metadata_dict',
]

# === DEFAULT VALUES (used if no project schema found) ===
DEFAULT_SCHEMA = {
    "schema_version": 1,
    "playblast": {
        "folder_name": "PlayBlast",
        "archive_folder": "_archive",
        "naming_pattern": "{filename}_PB_v{version:03d}",
        "file_extension": ".mp4"
    }
}


@dataclass
class PlayblastJsonMetadata:
    """
    Metadata loaded from a playblast's companion JSON file.

    This is separate from PlayblastMetadata (extracted from video)
    as it contains render-time information from Blender.
    """
    version: int
    blend_file: str
    created_at: datetime
    frame_start: int
    frame_end: int
    resolution: Tuple[int, int]
    fps: float
    duration_ms: int
    quality: str


def get_playblast_config(start_path: Path) -> Dict:
    """
    Get playblast config from project schema

    Args:
        start_path: Starting path to search from

    Returns:
        Playblast configuration dictionary
    """
    schema = load_project_schema(start_path, DEFAULT_SCHEMA)
    return schema.get("playblast", DEFAULT_SCHEMA["playblast"].copy())


def get_playblast_filename(config: Dict, blend_name: str, version: int) -> str:
    """
    Generate playblast filename using config pattern

    Args:
        config: Playblast configuration dictionary
        blend_name: Name of the blend file (without extension)
        version: Version number

    Returns:
        Complete filename with extension (e.g., "shot_010_PB_v001.mp4")
    """
    return get_media_filename(config, blend_name, version, "{filename}_PB_v{version:03d}")


def get_metadata_filename(config: Dict, blend_name: str, version: int) -> str:
    """
    Generate metadata filename (same as playblast but .json)

    Args:
        config: Playblast configuration dictionary
        blend_name: Name of the blend file (without extension)
        version: Version number

    Returns:
        JSON filename (e.g., "shot_010_PB_v001.json")
    """
    return _get_metadata_filename(config, blend_name, version, "{filename}_PB_v{version:03d}")


def get_metadata_path_for_playblast(playblast_path: Path) -> Path:
    """
    Get the companion JSON metadata path for a playblast MP4.

    Args:
        playblast_path: Path to the MP4 file

    Returns:
        Path to the companion JSON file (same name, .json extension)
    """
    return get_metadata_path_for_media(playblast_path)


def load_playblast_metadata(json_path: Path) -> Optional[PlayblastJsonMetadata]:
    """
    Load metadata from JSON file

    Args:
        json_path: Path to the JSON file

    Returns:
        PlayblastJsonMetadata object or None if file doesn't exist/is invalid
    """
    data = load_metadata_dict(json_path)
    if not data:
        return None

    try:
        # Parse created_at as datetime
        created_at = datetime.fromisoformat(data.get("created_at", ""))

        return PlayblastJsonMetadata(
            version=data.get("version", 0),
            blend_file=data.get("blend_file", ""),
            created_at=created_at,
            frame_start=data.get("frame_start", 0),
            frame_end=data.get("frame_end", 0),
            resolution=tuple(data.get("resolution", [0, 0])),
            fps=data.get("fps", 0.0),
            duration_ms=data.get("duration_ms", 0),
            quality=data.get("quality", "UNKNOWN")
        )
    except Exception:
        return None


def load_playblast_metadata_dict(json_path: Path) -> Optional[dict]:
    """
    Load metadata from JSON file as raw dictionary

    Args:
        json_path: Path to the JSON file

    Returns:
        Metadata dictionary or None if file doesn't exist/is invalid
    """
    return load_metadata_dict(json_path)
