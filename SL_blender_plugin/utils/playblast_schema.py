"""
Playblast schema reader + metadata utilities for Blender Plugin

Handles the two levels of configuration:
1. Project Schema (.shot_library.json) - Lives at project root, defines conventions
2. Playblast Metadata (per-file .json) - Lives next to each MP4, contains render-time metadata
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Tuple

from .schema_loader import (
    SCHEMA_FILENAME,
    find_project_schema,
    load_project_schema,
    save_metadata,
    load_metadata,
)

# Re-export for backwards compatibility
__all__ = [
    'SCHEMA_FILENAME',
    'DEFAULT_SCHEMA',
    'find_project_schema',
    'load_project_schema',
    'get_playblast_config',
    'get_playblast_filename',
    'get_metadata_filename',
    'create_playblast_metadata',
    'save_playblast_metadata',
    'load_playblast_metadata',
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
    pattern = config.get("naming_pattern", "{filename}_PB_v{version:03d}")
    ext = config.get("file_extension", ".mp4")
    return pattern.format(filename=blend_name, version=version) + ext


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
    pattern = config.get("naming_pattern", "{filename}_PB_v{version:03d}")
    return pattern.format(filename=blend_name, version=version) + ".json"


# === PLAYBLAST METADATA ===

def create_playblast_metadata(
    version: int,
    blend_file: str,
    frame_start: int,
    frame_end: int,
    resolution: Tuple[int, int],
    fps: float,
    quality: str
) -> dict:
    """
    Create playblast metadata dictionary

    Args:
        version: Playblast version number
        blend_file: Name of the source blend file
        frame_start: First frame rendered
        frame_end: Last frame rendered
        resolution: (width, height) tuple
        fps: Frames per second
        quality: Quality preset used (PREVIEW, HALF, FULL)

    Returns:
        Metadata dictionary ready for JSON serialization
    """
    frame_count = frame_end - frame_start + 1
    duration_ms = int((frame_count / fps) * 1000) if fps > 0 else 0
    return {
        "version": version,
        "blend_file": blend_file,
        "created_at": datetime.now().isoformat(),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "resolution": list(resolution),
        "fps": fps,
        "duration_ms": duration_ms,
        "quality": quality
    }


def save_playblast_metadata(metadata: dict, json_path: Path) -> bool:
    """
    Save metadata to JSON file

    Args:
        metadata: Metadata dictionary
        json_path: Path where to save the JSON file

    Returns:
        True if successful, False otherwise
    """
    return save_metadata(metadata, json_path)


def load_playblast_metadata(json_path: Path) -> Optional[dict]:
    """
    Load metadata from JSON file

    Args:
        json_path: Path to the JSON file

    Returns:
        Metadata dictionary or None if file doesn't exist/is invalid
    """
    return load_metadata(json_path)
