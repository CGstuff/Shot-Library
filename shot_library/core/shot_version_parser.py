"""
Shot Version Parser

Parses versioned shot names following industry standards (ShotGrid/Netflix VFX).
Extracts base shot name and version number from patterns like:
- shot1_v003 -> base="shot1", version=3
- AGM_104_065_comp_v005 -> base="AGM_104_065_comp", version=5
- shot_no_version -> base="shot_no_version", version=None

Supported patterns (priority order):
- _v### / _V### (industry standard)
- -v### / -V###
- .v### / .V###
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Tuple
import hashlib


@dataclass
class ShotVersionInfo:
    """Result of parsing a shot name for version information."""
    base_name: str
    version: Optional[int]
    original_name: str
    version_suffix: Optional[str] = None  # e.g., "_v003"

    @property
    def is_versioned(self) -> bool:
        """Returns True if this shot has a version number."""
        return self.version is not None

    @property
    def version_label(self) -> Optional[str]:
        """Returns formatted version label like 'v003' or None."""
        if self.version is not None:
            return f"v{self.version:03d}"
        return None


# Version patterns in priority order (most common first)
# Each pattern captures: full suffix, version number
# Supports 1-4 digits (v1, v01, v001, v0001)
VERSION_PATTERNS = [
    # _v### or _V### (ShotGrid/Netflix standard)
    re.compile(r'^(.+?)(_[vV](\d{1,4}))$'),
    # -v### or -V###
    re.compile(r'^(.+?)(-[vV](\d{1,4}))$'),
    # .v### or .V###
    re.compile(r'^(.+?)(\.[vV](\d{1,4}))$'),
]


def parse_shot_version(shot_name: str) -> ShotVersionInfo:
    """
    Parse a shot name to extract base name and version number.

    Args:
        shot_name: The shot folder name or filename (without extension)

    Returns:
        ShotVersionInfo with parsed base_name and version

    Examples:
        >>> parse_shot_version("shot1_v003")
        ShotVersionInfo(base_name="shot1", version=3, ...)

        >>> parse_shot_version("AGM_104_065_comp_v005")
        ShotVersionInfo(base_name="AGM_104_065_comp", version=5, ...)

        >>> parse_shot_version("shot_no_version")
        ShotVersionInfo(base_name="shot_no_version", version=None, ...)
    """
    if not shot_name:
        return ShotVersionInfo(
            base_name="",
            version=None,
            original_name="",
        )

    # Try each pattern in priority order
    for pattern in VERSION_PATTERNS:
        match = pattern.match(shot_name)
        if match:
            base_name = match.group(1)
            version_suffix = match.group(2)
            version_str = match.group(3)

            try:
                version = int(version_str)
                return ShotVersionInfo(
                    base_name=base_name,
                    version=version,
                    original_name=shot_name,
                    version_suffix=version_suffix,
                )
            except ValueError:
                # Invalid version number, continue to next pattern
                continue

    # No version pattern matched - return as unversioned
    return ShotVersionInfo(
        base_name=shot_name,
        version=None,
        original_name=shot_name,
    )


def generate_version_group_id(base_name: str, parent_path: str) -> str:
    """
    Generate a deterministic version group ID for grouping related shots.

    Shots with the same base name in the same parent folder belong to the
    same version group.

    Args:
        base_name: Base shot name (without version suffix)
        parent_path: Parent folder path containing the shot folders

    Returns:
        UUID-like string identifying the version group
    """
    # Normalize path separators for consistent hashing
    normalized_path = parent_path.replace('\\', '/')

    # Create deterministic hash from base_name + parent_path
    key = f"{normalized_path}/{base_name}"
    hash_bytes = hashlib.sha256(key.encode('utf-8')).digest()

    # Format as UUID-like string (8-4-4-4-12)
    hex_str = hash_bytes[:16].hex()
    return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def group_shots_by_version(
    shots: List[Tuple[str, str]]  # List of (shot_name, parent_path)
) -> dict:
    """
    Group shots by their base name to identify version families.

    Args:
        shots: List of tuples (shot_name, parent_path)

    Returns:
        Dict mapping version_group_id to list of (shot_name, version, parent_path)
    """
    groups = {}

    for shot_name, parent_path in shots:
        info = parse_shot_version(shot_name)
        group_id = generate_version_group_id(info.base_name, parent_path)

        if group_id not in groups:
            groups[group_id] = []

        groups[group_id].append({
            'shot_name': shot_name,
            'base_name': info.base_name,
            'version': info.version,
            'parent_path': parent_path,
        })

    return groups


def find_latest_in_group(group: List[dict]) -> Optional[dict]:
    """
    Find the latest version shot in a version group.

    For versioned shots, returns the one with highest version number.
    For unversioned shots (version=None), returns the first one.

    Args:
        group: List of shot dicts from group_shots_by_version

    Returns:
        The shot dict that should be marked as latest, or None if empty
    """
    if not group:
        return None

    # Separate versioned and unversioned shots
    versioned = [s for s in group if s['version'] is not None]
    unversioned = [s for s in group if s['version'] is None]

    if versioned:
        # Return highest version
        return max(versioned, key=lambda s: s['version'])
    elif unversioned:
        # Return first unversioned shot (they're all "latest" if no versions)
        return unversioned[0]

    return None


def mark_latest_versions(groups: dict) -> List[str]:
    """
    Identify which shots should be marked as latest in their version groups.

    Args:
        groups: Dict from group_shots_by_version

    Returns:
        List of shot_names that should be marked as is_latest=True
    """
    latest_shots = []

    for group_id, shots in groups.items():
        latest = find_latest_in_group(shots)
        if latest:
            latest_shots.append(latest['shot_name'])

    return latest_shots


__all__ = [
    'ShotVersionInfo',
    'parse_shot_version',
    'generate_version_group_id',
    'group_shots_by_version',
    'find_latest_in_group',
    'mark_latest_versions',
]
