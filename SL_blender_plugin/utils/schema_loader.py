"""
Schema Loader - Shared schema loading utilities for Blender plugin

Consolidates duplicate code from playblast_schema.py and lookdev_schema.py:
- find_project_schema() - 100% identical
- load_project_schema() - 100% identical
"""

import json
from pathlib import Path
from typing import Optional, Dict

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


def save_metadata(metadata: dict, json_path: Path) -> bool:
    """
    Save metadata to JSON file

    Args:
        metadata: Metadata dictionary
        json_path: Path where to save the JSON file

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        return True
    except Exception:
        return False


def load_metadata(json_path: Path) -> Optional[dict]:
    """
    Load metadata from JSON file

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


__all__ = [
    'SCHEMA_FILENAME',
    'find_project_schema',
    'load_project_schema',
    'save_metadata',
    'load_metadata',
]
