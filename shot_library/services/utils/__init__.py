"""
Services Utilities Package

Shared utilities for Shot Library services layer.
Shot Library is read-only - no file operations needed.
"""

from .path_utils import (
    get_library_path,
    get_cache_folder,
    get_queue_folder,
)

__all__ = [
    # Path utilities
    'get_library_path',
    'get_cache_folder',
    'get_queue_folder',
]
