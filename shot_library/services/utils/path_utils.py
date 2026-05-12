"""
Path Utilities - Shared folder path helpers for Shot Library services.

Shot Library is read-only - these utilities provide project path access only.
"""

from pathlib import Path
from typing import Optional, Union

from ...config import Config


def normalize_path(path: Union[str, Path]) -> str:
    """
    Normalize a path for reliable cross-platform comparison.

    This fixes the Windows path comparison bug where paths with different
    separators (backslash vs forward slash) fail to match even when they
    refer to the same file.

    Args:
        path: A path string or Path object

    Returns:
        Normalized path string with:
        - Resolved (absolute) path
        - Forward slashes only
        - Consistent casing (lowercased on Windows for case-insensitive comparison)

    Example:
        >>> normalize_path("E:\\Projects\\shot_010.blend")
        'e:/projects/shot_010.blend'
        >>> normalize_path("E:/Projects/shot_010.blend")
        'e:/projects/shot_010.blend'
    """
    import sys

    # Convert to Path, resolve to absolute, convert to string with forward slashes
    resolved = str(Path(path).resolve()).replace('\\', '/')

    # On Windows, lowercase for case-insensitive comparison
    if sys.platform == 'win32':
        resolved = resolved.lower()

    return resolved


def get_library_path() -> Optional[Path]:
    """
    Get configured project/library root path.

    Returns:
        Path to project root or None if not configured
    """
    return Config.load_library_path()


def get_cache_folder(ensure_exists: bool = True) -> Optional[Path]:
    """
    Get cache folder path for thumbnails and previews.

    Args:
        ensure_exists: If True, create folder if it doesn't exist

    Returns:
        Path to cache folder or None if not configured
    """
    return Config.get_cache_dir() if ensure_exists else Config.get_user_data_dir() / 'cache'


def get_queue_folder(ensure_exists: bool = True) -> Optional[Path]:
    """
    Get queue folder path (for Blender communication).

    Args:
        ensure_exists: If True, create folder if it doesn't exist (default: True)

    Returns:
        Path to queue folder or None if library not configured
    """
    library_path = get_library_path()
    if not library_path:
        return None

    queue_folder = library_path / ".queue"
    if ensure_exists:
        queue_folder.mkdir(parents=True, exist_ok=True)
    return queue_folder


__all__ = [
    'normalize_path',
    'get_library_path',
    'get_cache_folder',
    'get_queue_folder',
]
