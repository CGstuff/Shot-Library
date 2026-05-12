"""
Lookdev schema reader + metadata utilities for Blender Plugin

Handles the two levels of configuration:
1. Project Schema (.shot_library.json) - Lives at project root, defines conventions
2. Lookdev Metadata (per-file .json) - Lives next to each MP4, contains render-time metadata

Parallel implementation to playblast_schema.py for lookdev renders.
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
    'DEFAULT_LOOKDEV_SCHEMA',
    'find_project_schema',
    'load_project_schema',
    'get_lookdev_config',
    'get_lookdev_filename',
    'get_metadata_filename',
    'create_lookdev_metadata',
    'save_lookdev_metadata',
    'load_lookdev_metadata',
]

# === DEFAULT VALUES (used if no project schema found) ===
DEFAULT_LOOKDEV_SCHEMA = {
    "folder_name": "Lookdev",
    "archive_folder": "_archive",
    "naming_pattern": "{filename}_LD_v{version:03d}",
    "file_extension": ".mp4"
}


def get_lookdev_config(start_path: Path) -> Dict:
    """
    Get lookdev config from project schema

    Args:
        start_path: Starting path to search from

    Returns:
        Lookdev configuration dictionary
    """
    schema = load_project_schema(start_path)
    return schema.get("lookdev", DEFAULT_LOOKDEV_SCHEMA.copy())


def get_lookdev_filename(config: Dict, blend_name: str, version: int) -> str:
    """
    Generate lookdev filename using config pattern

    Args:
        config: Lookdev configuration dictionary
        blend_name: Name of the blend file (without extension)
        version: Version number

    Returns:
        Complete filename with extension (e.g., "shot_010_LD_v001.mp4")
    """
    pattern = config.get("naming_pattern", "{filename}_LD_v{version:03d}")
    ext = config.get("file_extension", ".mp4")
    return pattern.format(filename=blend_name, version=version) + ext


def get_metadata_filename(config: Dict, blend_name: str, version: int) -> str:
    """
    Generate metadata filename (same as lookdev but .json)

    Args:
        config: Lookdev configuration dictionary
        blend_name: Name of the blend file (without extension)
        version: Version number

    Returns:
        JSON filename (e.g., "shot_010_LD_v001.json")
    """
    pattern = config.get("naming_pattern", "{filename}_LD_v{version:03d}")
    return pattern.format(filename=blend_name, version=version) + ".json"


# === LOOKDEV METADATA ===

def create_lookdev_metadata(
    version: int,
    blend_file: str,
    frame_start: int,
    frame_end: int,
    resolution: Tuple[int, int],
    fps: float,
    render_engine: str,
    samples: int,
    render_time_seconds: float = 0.0
) -> dict:
    """
    Create lookdev metadata dictionary

    Args:
        version: Lookdev version number
        blend_file: Name of the source blend file
        frame_start: First frame rendered
        frame_end: Last frame rendered
        resolution: (width, height) tuple
        fps: Frames per second
        render_engine: Render engine used (CYCLES, BLENDER_EEVEE, etc.)
        samples: Number of render samples used
        render_time_seconds: Total render time in seconds

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
        "render_engine": render_engine,
        "samples": samples,
        "render_time_seconds": render_time_seconds,
        "type": "lookdev"  # Distinguish from playblast
    }


def save_lookdev_metadata(metadata: dict, json_path: Path) -> bool:
    """
    Save metadata to JSON file

    Args:
        metadata: Metadata dictionary
        json_path: Path where to save the JSON file

    Returns:
        True if successful, False otherwise
    """
    return save_metadata(metadata, json_path)


def load_lookdev_metadata(json_path: Path) -> Optional[dict]:
    """
    Load metadata from JSON file

    Args:
        json_path: Path to the JSON file

    Returns:
        Metadata dictionary or None if file doesn't exist/is invalid
    """
    return load_metadata(json_path)
