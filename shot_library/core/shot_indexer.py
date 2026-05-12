"""
Shot Indexer

Discovers and registers shots from filesystem.
Implements the shot-indexer contract.

T174: Added logging for shot discovery operations.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Callable, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

# T174: Logger for shot discovery operations
logger = logging.getLogger(__name__)

from .editorial_order import (
    extract_editorial_components,
    generate_editorial_order_string,
    UNPARSEABLE_ORDER,
)
from .shot_version_parser import (
    parse_shot_version,
    generate_version_group_id,
)


class ShotStatus(Enum):
    """Production status for a shot (must match Pipeline Control)."""
    WIP = "WIP"
    IN_REVIEW = "In Review"
    NEEDS_WORK = "Needs Work"
    APPROVED = "Approved"
    FINAL = "Final"
    BLOCKED = "Blocked"


@dataclass
class ParsedShotIdentity:
    """Result of parsing a shot folder/filename."""
    shot_name: str
    episode_num: Optional[int] = None
    sequence_num: Optional[int] = None
    scene_num: Optional[int] = None
    shot_num: Optional[int] = None
    editorial_order: str = "9999.9999.9999.9999"  # Default: sorts to end
    parse_warning: Optional[str] = None
    confidence: float = 0.0  # 0.0 - 1.0
    # Shot version grouping (v2)
    base_shot_name: Optional[str] = None  # e.g., "shot1" from "shot1_v003"
    shot_version: Optional[int] = None  # e.g., 3 from "shot1_v003"
    version_group_id: Optional[str] = None  # UUID shared by version family
    is_latest_shot_version: bool = True  # True if latest in version group
    # Multi-camera reference files (v9)
    shot_role: str = "standalone"  # 'standalone', 'master', or 'view'
    master_blend_file: Optional[str] = None  # For views, path to master blend file
    view_name: Optional[str] = None  # For views, e.g., "ref01", "cam02"


@dataclass
class DiscoveredShot:
    """A shot discovered from the filesystem."""
    folder_path: Path
    blend_file: Path
    identity: ParsedShotIdentity
    status: ShotStatus = ShotStatus.WIP
    discovered_at: datetime = field(default_factory=datetime.now)


class ShotIndexer(QObject):
    """
    Discovers shots from filesystem using configured folder schema.

    Read-only: Never creates, modifies, or deletes production files.
    """

    # Signals
    shot_discovered = pyqtSignal(object)  # DiscoveredShot
    shot_updated = pyqtSignal(str, object)  # folder_path, DiscoveredShot
    shot_removed = pyqtSignal(str)  # folder_path
    scan_progress = pyqtSignal(int, int)  # current, total
    scan_complete = pyqtSignal(int)  # total_shots
    scan_error = pyqtSignal(str, object)  # folder_path, Exception

    def __init__(self, schema_parser: 'FolderSchemaParser', parent=None):
        """
        Initialize indexer with a configured schema parser.

        Args:
            schema_parser: Parser configured for studio folder layout
        """
        super().__init__(parent)
        self.schema_parser = schema_parser

    def scan_folder(
        self,
        root_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[DiscoveredShot]:
        """
        Scan a folder tree for shots.

        Args:
            root_path: Root folder to scan
            progress_callback: Called with (current, total) during scan

        Returns:
            List of discovered shots in editorial order

        Raises:
            FileNotFoundError: If root_path doesn't exist
            PermissionError: If folder is not readable
        """
        if not root_path.exists():
            logger.error(f"Root path does not exist: {root_path}")
            raise FileNotFoundError(f"Root path does not exist: {root_path}")

        if not root_path.is_dir():
            logger.error(f"Root path is not a directory: {root_path}")
            raise FileNotFoundError(f"Root path is not a directory: {root_path}")

        # T174: Log scan start
        logger.info(f"Starting shot scan: {root_path}")

        # Find all potential shot folders
        shot_folders = self._find_shot_folders(root_path)
        total = len(shot_folders)
        discovered_shots: List[DiscoveredShot] = []

        logger.info(f"Found {total} potential shot folders to scan")

        for i, folder in enumerate(shot_folders):
            try:
                # Index ALL blend files in the folder (not just primary)
                shots = self.index_shot_folder(folder)
                for shot in shots:
                    discovered_shots.append(shot)
                    self.shot_discovered.emit(shot)
                    logger.debug(f"Discovered shot: {shot.identity.shot_name} at {folder}")
            except PermissionError as e:
                logger.warning(f"Permission denied scanning folder: {folder}")
                self.scan_error.emit(str(folder), e)
            except Exception as e:
                logger.error(f"Error scanning folder {folder}: {e}")
                self.scan_error.emit(str(folder), e)

            if progress_callback:
                progress_callback(i + 1, total)
            self.scan_progress.emit(i + 1, total)

        # Sort by editorial order
        discovered_shots.sort(key=lambda s: s.identity.editorial_order)

        # Process version groups and mark latest versions
        self._mark_latest_versions(discovered_shots)

        # Pass 2: Detect master/view relationships
        if self.schema_parser.is_reference_detection_enabled():
            self._detect_master_view_relationships(discovered_shots)

        # T174: Log scan completion
        logger.info(f"Shot scan complete: {len(discovered_shots)} shots discovered from {root_path}")

        self.scan_complete.emit(len(discovered_shots))
        return discovered_shots

    def index_single_shot(self, shot_folder: Path) -> Optional[DiscoveredShot]:
        """
        Index a single shot folder (returns primary/latest blend only).

        For backward compatibility. Use index_shot_folder() to get all versions.

        Args:
            shot_folder: Path to shot folder containing .blend file

        Returns:
            DiscoveredShot for the primary (latest) blend, or None if invalid
        """
        shots = self.index_shot_folder(shot_folder)
        if not shots:
            return None
        # Return the latest version (highest shot_version)
        return max(shots, key=lambda s: s.identity.shot_version or 0)

    def index_shot_folder(self, shot_folder: Path) -> List[DiscoveredShot]:
        """
        Index all versioned blend files in a shot folder.

        Creates a separate DiscoveredShot for each .blend file in the folder.
        All shots share the same version_group_id for lineage tracking.

        Args:
            shot_folder: Path to shot folder containing .blend files

        Returns:
            List of DiscoveredShot instances (one per blend file)
        """
        if not shot_folder.is_dir():
            return []

        # Check if folder is a shot folder according to schema
        if not self.schema_parser.is_shot_folder(shot_folder):
            return []

        # Find all blend files
        blend_files = self.schema_parser.find_blend_files(shot_folder)
        if not blend_files:
            return []

        # Parse path to extract base identity
        parsed_path = self.schema_parser.parse_path(shot_folder)

        discovered_shots = []
        for blend_file in blend_files:
            shot = self._index_blend_file(shot_folder, blend_file, parsed_path)
            if shot:
                discovered_shots.append(shot)

        return discovered_shots

    def _index_blend_file(
        self,
        shot_folder: Path,
        blend_file: Path,
        parsed_path: 'ParsedPath'
    ) -> Optional[DiscoveredShot]:
        """
        Index a single blend file within a shot folder.

        Args:
            shot_folder: Path to shot folder
            blend_file: Path to specific .blend file
            parsed_path: Pre-parsed path info for the shot folder

        Returns:
            DiscoveredShot for this blend file
        """
        # Parse the blend filename for version info
        parsed_filename = self.schema_parser.parse_blend_filename(blend_file.name)

        # Combine identity from path and filename
        # Use blend filename as shot_name to distinguish versions
        identity = self._combine_identity_for_blend(
            parsed_path, parsed_filename, shot_folder.name, shot_folder, blend_file
        )

        return DiscoveredShot(
            folder_path=shot_folder,
            blend_file=blend_file,
            identity=identity,
            status=ShotStatus.WIP,
            discovered_at=datetime.now()
        )

    def detect_changes(
        self,
        root_path: Path,
        known_shots: List[str]  # folder paths
    ) -> Tuple[List[DiscoveredShot], List[str], List[str]]:
        """
        Detect added, removed, and modified shots.

        Args:
            root_path: Root folder to scan
            known_shots: List of previously known shot folder paths

        Returns:
            Tuple of (added_shots, removed_paths, modified_paths)
        """
        known_set = set(known_shots)

        # Scan for current shots
        current_shots = self.scan_folder(root_path)
        current_paths = {str(s.folder_path) for s in current_shots}

        # Find added shots (in current but not in known)
        added_shots = [s for s in current_shots if str(s.folder_path) not in known_set]

        # Find removed paths (in known but not in current)
        removed_paths = [p for p in known_shots if p not in current_paths]

        # For now, we don't track modifications (would need mtime comparison)
        modified_paths: List[str] = []

        return added_shots, removed_paths, modified_paths

    def _find_shot_folders(self, root_path: Path) -> List[Path]:
        """Find all folders that could be shot folders."""
        shot_folders = []

        for folder in root_path.rglob('*'):
            if folder.is_dir():
                if self.schema_parser.is_shot_folder(folder):
                    shot_folders.append(folder)

        return shot_folders

    def _select_primary_blend(self, blend_files: List[Path]) -> Path:
        """
        Select the primary .blend file from a list.

        Uses highest version number, or most recently modified if no versions.
        """
        if len(blend_files) == 1:
            return blend_files[0]

        # Try to find versioned files
        versioned = []
        for f in blend_files:
            parsed = self.schema_parser.parse_blend_filename(f.name)
            if parsed.version is not None:
                versioned.append((f, parsed.version))

        if versioned:
            # Return highest version
            versioned.sort(key=lambda x: x[1], reverse=True)
            return versioned[0][0]

        # Fall back to most recently modified
        blend_files_with_mtime = [(f, f.stat().st_mtime) for f in blend_files]
        blend_files_with_mtime.sort(key=lambda x: x[1], reverse=True)
        return blend_files_with_mtime[0][0]

    def _combine_identity_for_blend(
        self,
        parsed_path: 'ParsedPath',
        parsed_filename: 'ParsedPath',
        folder_name: str,
        shot_folder: Path,
        blend_file: Path
    ) -> ParsedShotIdentity:
        """
        Combine identity for a specific blend file, using blend filename for versioning.

        This variant uses the BASE shot name (without version suffix) for display,
        while tracking version info separately.
        """
        blend_stem = blend_file.stem  # e.g., "SH0010_v002"

        # Parse version info FIRST to get base name without version suffix
        # This ensures each blend file gets its own version number
        version_info = parse_shot_version(blend_stem)

        # Use base shot name for display (e.g., "SH0010" not "SH0010_v002")
        # Fall back to folder name if no base name extracted
        shot_name = version_info.base_name or folder_name

        # Resolve editorial-order components.
        #
        # The user-configured schema is the AUTHORITY: if their blend_file_patterns
        # or hierarchy_levels regex captured a value, that wins. The hardcoded
        # editorial_order patterns are only a FALLBACK for studios that didn't
        # configure a schema. Without this priority, the loose `[_\-](\d+)` fallback
        # could silently overwrite a correctly-extracted schema value (e.g., for
        # `01_005_010` the schema says shot=10, the fallback grabs the first
        # `_005` and says shot=5; we want the schema to win).
        components = extract_editorial_components(shot_name)
        episode_num = parsed_path.episode_num or parsed_filename.episode_num or components.episode or 0
        sequence_num = parsed_path.sequence_num or parsed_filename.sequence_num or components.sequence or 0
        scene_num = parsed_path.scene_num or parsed_filename.scene_num or components.scene or 0
        shot_num = parsed_path.shot_num or parsed_filename.shot_num or components.shot or 0

        # Generate editorial order
        editorial_order = generate_editorial_order_string(
            episode_num, sequence_num, scene_num, shot_num
        )

        # Combine warnings
        warnings = parsed_path.warnings + parsed_filename.warnings
        parse_warning = "; ".join(warnings) if warnings else None

        # Calculate confidence
        confidence = max(parsed_path.match_confidence, parsed_filename.match_confidence)

        if editorial_order == "0000.0000.0000.0000" and confidence == 0.0:
            editorial_order = UNPARSEABLE_ORDER
            if not parse_warning:
                parse_warning = f"Could not parse editorial order from: {shot_name}"

        parent_path = str(shot_folder)  # Use shot_folder as group parent
        version_group_id = generate_version_group_id(version_info.base_name, parent_path)

        return ParsedShotIdentity(
            shot_name=shot_name,
            episode_num=episode_num if episode_num else None,
            sequence_num=sequence_num if sequence_num else None,
            scene_num=scene_num if scene_num else None,
            shot_num=shot_num if shot_num else None,
            editorial_order=editorial_order,
            parse_warning=parse_warning,
            confidence=confidence,
            # Version grouping fields - based on blend filename
            base_shot_name=version_info.base_name,
            shot_version=version_info.version,
            version_group_id=version_group_id,
            is_latest_shot_version=True,  # Will be updated after grouping
        )

    def _combine_identity(
        self,
        parsed_path: 'ParsedPath',
        parsed_filename: 'ParsedPath',
        folder_name: str,
        shot_folder: Path
    ) -> ParsedShotIdentity:
        """Combine identity from path and filename parsing."""
        # Use path-based values, fall back to filename, then folder name
        shot_name = (
            parsed_filename.shot or
            parsed_path.shot or
            folder_name
        )

        episode_num = parsed_path.episode_num or parsed_filename.episode_num or 0
        sequence_num = parsed_path.sequence_num or parsed_filename.sequence_num or 0
        scene_num = parsed_path.scene_num or parsed_filename.scene_num or 0
        shot_num = parsed_path.shot_num or parsed_filename.shot_num or 0

        # If we couldn't extract from path/filename, try editorial order regex patterns
        if episode_num == 0 and sequence_num == 0 and scene_num == 0 and shot_num == 0:
            # Try to extract from shot name using editorial order patterns
            components = extract_editorial_components(shot_name)
            episode_num = components.episode
            sequence_num = components.sequence
            scene_num = components.scene
            shot_num = components.shot

        # Generate editorial order
        editorial_order = generate_editorial_order_string(
            episode_num, sequence_num, scene_num, shot_num
        )

        # Combine warnings
        warnings = parsed_path.warnings + parsed_filename.warnings
        parse_warning = "; ".join(warnings) if warnings else None

        # Calculate confidence
        confidence = max(parsed_path.match_confidence, parsed_filename.match_confidence)

        # If editorial order is all zeros and we have no confidence, mark as unparseable
        if editorial_order == "0000.0000.0000.0000" and confidence == 0.0:
            editorial_order = UNPARSEABLE_ORDER
            if not parse_warning:
                parse_warning = f"Could not parse editorial order from: {shot_name}"

        # Parse version info from folder name
        version_info = parse_shot_version(folder_name)
        parent_path = str(shot_folder.parent)
        version_group_id = generate_version_group_id(version_info.base_name, parent_path)

        return ParsedShotIdentity(
            shot_name=shot_name,
            episode_num=episode_num if episode_num else None,
            sequence_num=sequence_num if sequence_num else None,
            scene_num=scene_num if scene_num else None,
            shot_num=shot_num if shot_num else None,
            editorial_order=editorial_order,
            parse_warning=parse_warning,
            confidence=confidence,
            # Version grouping fields
            base_shot_name=version_info.base_name,
            shot_version=version_info.version,
            version_group_id=version_group_id,
            is_latest_shot_version=True,  # Will be updated after grouping
        )

    def _mark_latest_versions(self, shots: List[DiscoveredShot]):
        """
        Mark which shots are the latest in their version groups.

        After scanning, all shots have is_latest_shot_version=True by default.
        This method groups shots by version_group_id and marks only the
        highest version in each group as latest.

        Non-versioned shots (version=None) are all marked as latest.

        Args:
            shots: List of DiscoveredShot instances to process (modified in-place)
        """
        # Group shots by version_group_id
        groups: dict = {}
        for shot in shots:
            group_id = shot.identity.version_group_id
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append(shot)

        # For each group, determine the latest version
        for group_id, group_shots in groups.items():
            if len(group_shots) <= 1:
                # Only one shot in group - it's automatically latest
                continue

            # Separate versioned and unversioned shots
            versioned = [s for s in group_shots if s.identity.shot_version is not None]
            unversioned = [s for s in group_shots if s.identity.shot_version is None]

            if versioned:
                # Find highest version
                latest_shot = max(versioned, key=lambda s: s.identity.shot_version)

                # Mark all as not latest, then mark the latest one
                for shot in group_shots:
                    shot.identity.is_latest_shot_version = False
                latest_shot.identity.is_latest_shot_version = True
            else:
                # All unversioned - all are "latest" (no versioning)
                for shot in unversioned:
                    shot.identity.is_latest_shot_version = True

    def get_version_groups(self, shots: List[DiscoveredShot]) -> dict:
        """
        Get version groups with counts for display.

        Args:
            shots: List of DiscoveredShot instances

        Returns:
            Dict mapping version_group_id to {
                'base_name': str,
                'shots': List[DiscoveredShot],
                'count': int,
                'latest': DiscoveredShot
            }
        """
        groups: dict = {}

        for shot in shots:
            group_id = shot.identity.version_group_id
            if group_id not in groups:
                groups[group_id] = {
                    'base_name': shot.identity.base_shot_name,
                    'shots': [],
                    'count': 0,
                    'latest': None,
                }

            groups[group_id]['shots'].append(shot)
            groups[group_id]['count'] += 1

            if shot.identity.is_latest_shot_version:
                groups[group_id]['latest'] = shot

        return groups

    def _detect_master_view_relationships(self, shots: List[DiscoveredShot]):
        """
        Detect master/view relationships based on filename patterns.

        Pass 2 of discovery: After all shots are discovered, analyze filenames
        to detect _ref## and _cam## patterns that indicate view files.

        Detection logic:
        1. Group shots by folder
        2. For each folder, classify blend files as views or non-views
        3. If views exist, find matching master file
        4. Update shot_role and master_blend_file fields

        Args:
            shots: List of DiscoveredShot instances to process (modified in-place)
        """
        # Group shots by folder
        folder_groups: dict = {}
        for shot in shots:
            folder_key = str(shot.folder_path)
            if folder_key not in folder_groups:
                folder_groups[folder_key] = []
            folder_groups[folder_key].append(shot)

        # Process each folder
        for folder_key, folder_shots in folder_groups.items():
            if len(folder_shots) <= 1:
                # Only one shot in folder - stays standalone
                continue

            # Classify shots in this folder
            views = []
            non_views = []
            base_names = set()

            for shot in folder_shots:
                filename = shot.blend_file.name
                view_info = self.schema_parser.parse_reference_filename(filename)
                if view_info:
                    views.append((shot, view_info))
                    base_names.add(view_info['base'])
                else:
                    non_views.append(shot)


            # If no views found, all are standalone
            if not views:
                continue

            # Find master among non-view files
            master_shot = None
            for shot in non_views:
                stem = shot.blend_file.stem
                # Strip version suffix like _v001, _v002
                base_stem = stem
                version_match = re.search(r'_v\d{3}$', stem)
                if version_match:
                    base_stem = stem[:version_match.start()]

                if base_stem in base_names:
                    master_shot = shot
                    shot.identity.shot_role = 'master'
                    break

            # Mark views and link to master
            for shot, view_info in views:
                shot.identity.shot_role = 'view'
                shot.identity.view_name = f"{view_info['pattern_type']}{view_info['view']}"
                if master_shot:
                    shot.identity.master_blend_file = str(master_shot.blend_file)
                logger.debug(f"Detected view: {shot.blend_file.name} -> {shot.identity.view_name}")

            # Log relationship detection
            if master_shot:
                logger.info(
                    f"Detected master/view relationship in {folder_key}: "
                    f"master={master_shot.blend_file.name}, views={len(views)}"
                )

    def get_master_view_groups(self, shots: List[DiscoveredShot]) -> dict:
        """
        Get master/view groups for display.

        Args:
            shots: List of DiscoveredShot instances

        Returns:
            Dict mapping master_blend_file to {
                'master': DiscoveredShot,
                'views': List[DiscoveredShot],
                'view_count': int
            }
        """
        groups: dict = {}

        # Find all masters first
        for shot in shots:
            if shot.identity.shot_role == 'master':
                groups[str(shot.blend_file)] = {
                    'master': shot,
                    'views': [],
                    'view_count': 0,
                }

        # Associate views with masters
        for shot in shots:
            if shot.identity.shot_role == 'view' and shot.identity.master_blend_file:
                master_key = shot.identity.master_blend_file
                if master_key in groups:
                    groups[master_key]['views'].append(shot)
                    groups[master_key]['view_count'] += 1

        return groups


# Re-export generate_editorial_order_string as generate_editorial_order for backwards compatibility
generate_editorial_order = generate_editorial_order_string


# Import at end to avoid circular imports
from .folder_schema_parser import FolderSchemaParser, ParsedPath

__all__ = [
    'ShotStatus',
    'ParsedShotIdentity',
    'DiscoveredShot',
    'ShotIndexer',
    'generate_editorial_order',
]
