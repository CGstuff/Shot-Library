"""
Version Manager - Shared version detection and archiving utilities

Consolidates duplicate version management logic from:
- SL_main_panel.py (_get_next_version, _get_next_lookdev_version)
- SL_playblast.py (_get_next_version, _archive_existing_versions)
- SL_lookdev.py (_get_next_version, _archive_existing_versions)
"""

import re
import shutil
from pathlib import Path
from typing import Optional

from .logger import get_logger

logger = get_logger()


def get_next_version(
    media_folder: Path,
    blend_name: str,
    config: dict,
    type_prefix: str = "PB"
) -> int:
    """
    Get next version number for media files (playblast or lookdev).

    Checks both main folder and _archive folder.

    Args:
        media_folder: Path to media folder (PlayBlast/{blend_stem}/ or Lookdev/{blend_stem}/)
        blend_name: Name of the blend file (without extension)
        config: Schema config dict with file_extension and archive_folder
        type_prefix: "PB" for playblast, "LD" for lookdev

    Returns:
        Next version number (max + 1)
    """
    ext = config.get("file_extension", ".mp4")
    archive_name = config.get("archive_folder", "_archive")

    # Match formats: v###.mp4, name_v###.mp4, name_PB_v###.mp4 (or LD)
    # Also check .json files for version tracking
    version_pattern = re.compile(
        rf'^({re.escape(blend_name)}_)?({type_prefix}_)?v(\d{{3}})(\.mp4|\.json|{re.escape(ext)})$',
        re.IGNORECASE
    )
    max_version = 0

    # Check both main folder and _archive folder
    archive_folder = media_folder / archive_name
    folders_to_check = [media_folder]
    if archive_folder.exists():
        folders_to_check.append(archive_folder)

    for folder in folders_to_check:
        if folder.exists():
            for file in folder.iterdir():
                if file.is_file():
                    match = version_pattern.match(file.name)
                    if match:
                        version = int(match.group(3))
                        max_version = max(max_version, version)

    return max_version + 1


def archive_existing_versions(
    media_folder: Path,
    archive_folder: Path,
    blend_name: str,
    config: dict,
    type_prefix: str = "PB"
) -> int:
    """
    Move all existing versioned files to _archive folder.

    Args:
        media_folder: Path to media folder
        archive_folder: Path to archive folder
        blend_name: Name of the blend file (without extension)
        config: Schema config dict with file_extension
        type_prefix: "PB" for playblast, "LD" for lookdev

    Returns:
        Number of files archived
    """
    ext = config.get("file_extension", ".mp4")

    # Match formats: v###.mp4, name_v###.mp4, name_PB_v###.mp4 (or LD)
    # Also match companion .json files
    version_pattern = re.compile(
        rf'^({re.escape(blend_name)}_)?({type_prefix}_)?v(\d{{3}})(\.mp4|\.json|{re.escape(ext)})$',
        re.IGNORECASE
    )

    archived_count = 0
    for file in media_folder.iterdir():
        if file.is_file() and version_pattern.match(file.name):
            dest = archive_folder / file.name
            try:
                shutil.move(str(file), str(dest))
                logger.info(f"Archived: {file.name} -> _archive/")
                archived_count += 1
            except Exception as e:
                logger.warning(f"Failed to archive {file.name}: {e}")

    return archived_count


# Convenience functions for playblast and lookdev
def get_next_playblast_version(playblast_folder: Path, blend_name: str, config: dict) -> int:
    """Get next version number for playblast."""
    return get_next_version(playblast_folder, blend_name, config, "PB")


def get_next_lookdev_version(lookdev_folder: Path, blend_name: str, config: dict) -> int:
    """Get next version number for lookdev."""
    return get_next_version(lookdev_folder, blend_name, config, "LD")


def archive_playblast_versions(
    playblast_folder: Path,
    archive_folder: Path,
    blend_name: str,
    config: dict
) -> int:
    """Archive existing playblast versions."""
    return archive_existing_versions(playblast_folder, archive_folder, blend_name, config, "PB")


def archive_lookdev_versions(
    lookdev_folder: Path,
    archive_folder: Path,
    blend_name: str,
    config: dict
) -> int:
    """Archive existing lookdev versions."""
    return archive_existing_versions(lookdev_folder, archive_folder, blend_name, config, "LD")


__all__ = [
    'get_next_version',
    'archive_existing_versions',
    'get_next_playblast_version',
    'get_next_lookdev_version',
    'archive_playblast_versions',
    'archive_lookdev_versions',
]
