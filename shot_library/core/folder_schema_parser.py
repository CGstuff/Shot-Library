"""
Folder Schema Parser

Parses studio folder structures into normalized shot identity.
Implements the folder-schema-parser contract.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import re


@dataclass
class HierarchyLevel:
    """Definition of a hierarchy level in folder structure."""
    level: str  # "show", "episode", "sequence", "scene", "shot"
    pattern: Optional[str] = None  # Regex pattern for folder name
    folder_contains: Optional[str] = None  # Required file extension


@dataclass
class SchemaConfig:
    """Complete folder schema configuration."""
    name: str
    hierarchy_levels: List[HierarchyLevel]
    blend_file_patterns: List[str]  # Regex patterns with named groups
    playblast_folder: str = "PlayBlast"
    playblast_pattern: str = r"^v(?P<version>\d{3})\.mp4$"
    # Multi-camera reference file support
    reference_patterns: List[str] = None  # Patterns for _ref## and _cam## suffixes
    reference_detection_enabled: bool = True  # Enable auto-detection of master/view relationships

    def __post_init__(self):
        """Initialize default reference patterns if not provided."""
        if self.reference_patterns is None:
            # Default patterns: matches _ref01, _ref02, _cam01, _cam02, etc.
            self.reference_patterns = [
                r'^(?P<base>.+)_ref(?P<view>\d{2})\.blend$',
                r'^(?P<base>.+)_cam(?P<view>\d{2})\.blend$',
            ]


@dataclass
class ParsedPath:
    """Result of parsing a path against a schema."""
    show: Optional[str] = None
    episode: Optional[str] = None
    episode_num: Optional[int] = None
    sequence: Optional[str] = None
    sequence_num: Optional[int] = None
    scene: Optional[str] = None
    scene_num: Optional[int] = None
    shot: Optional[str] = None
    shot_num: Optional[int] = None
    version: Optional[int] = None
    match_confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)


class FolderSchemaParser:
    """
    Parses studio folder structures into normalized shot identity.

    Configurable via JSON schema definitions.
    Read-only: Never modifies filesystem.
    """

    def __init__(self, config: SchemaConfig):
        """
        Initialize parser with schema configuration.

        Args:
            config: Schema configuration for this studio layout
        """
        self.config = config
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        for level in self.config.hierarchy_levels:
            if level.pattern:
                try:
                    self._compiled_patterns[level.level] = re.compile(level.pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex for level '{level.level}': {e}")

        # Compile blend file patterns
        self._blend_patterns: List[re.Pattern] = []
        for pattern in self.config.blend_file_patterns:
            try:
                self._blend_patterns.append(re.compile(pattern))
            except re.error as e:
                raise ValueError(f"Invalid blend file pattern '{pattern}': {e}")

        # Compile playblast pattern
        try:
            self._playblast_pattern = re.compile(self.config.playblast_pattern)
        except re.error as e:
            raise ValueError(f"Invalid playblast pattern: {e}")

        # Compile reference patterns for multi-camera detection
        self._reference_patterns: List[re.Pattern] = []
        if self.config.reference_patterns:
            for pattern in self.config.reference_patterns:
                try:
                    self._reference_patterns.append(re.compile(pattern))
                except re.error as e:
                    raise ValueError(f"Invalid reference pattern '{pattern}': {e}")

    @classmethod
    def from_json(cls, json_path: Path) -> 'FolderSchemaParser':
        """
        Create parser from JSON configuration file.

        Args:
            json_path: Path to schema JSON file

        Returns:
            Configured parser

        Raises:
            FileNotFoundError: If JSON file doesn't exist
            ValueError: If JSON is invalid
        """
        if not json_path.exists():
            raise FileNotFoundError(f"Schema file not found: {json_path}")

        with open(json_path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)

        return cls.from_dict(config_dict)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'FolderSchemaParser':
        """
        Create parser from dictionary configuration.

        Args:
            config_dict: Schema as dictionary

        Returns:
            Configured parser

        Raises:
            ValueError: If config is invalid
        """
        # Validate required fields
        if 'hierarchy_levels' not in config_dict:
            raise ValueError("Config must contain 'hierarchy_levels'")

        # Parse hierarchy levels
        levels = []
        for level_dict in config_dict['hierarchy_levels']:
            levels.append(HierarchyLevel(
                level=level_dict.get('level', 'unknown'),
                pattern=level_dict.get('pattern'),
                folder_contains=level_dict.get('folder_contains')
            ))

        config = SchemaConfig(
            name=config_dict.get('name', 'Unnamed Schema'),
            hierarchy_levels=levels,
            blend_file_patterns=config_dict.get('blend_file_patterns', [r'^(?P<shot>[\w]+)\.blend$']),
            playblast_folder=config_dict.get('playblast_folder', 'PlayBlast'),
            playblast_pattern=config_dict.get('playblast_pattern', r'^v(?P<version>\d{3})\.mp4$'),
            reference_patterns=config_dict.get('reference_patterns'),
            reference_detection_enabled=config_dict.get('reference_detection_enabled', True),
        )

        return cls(config)

    def parse_path(self, path: Path) -> ParsedPath:
        """
        Parse a path against the configured schema.

        Args:
            path: Path to parse (folder or file)

        Returns:
            ParsedPath with extracted components
        """
        result = ParsedPath()
        parts = list(path.parts)

        matched_levels = 0
        total_levels = len(self.config.hierarchy_levels)

        # Match path components against hierarchy levels
        for level in self.config.hierarchy_levels:
            if not parts:
                break

            # Find matching component
            for i, part in enumerate(parts):
                if level.pattern:
                    compiled = self._compiled_patterns.get(level.level)
                    if compiled and compiled.match(part):
                        self._extract_level_data(result, level.level, part)
                        parts = parts[i + 1:]
                        matched_levels += 1
                        break
                elif level.folder_contains:
                    # Check if any remaining folder contains the required file
                    test_path = Path(*parts[:i + 1])
                    if path.parent == test_path or str(path).startswith(str(test_path)):
                        # This might be the shot folder
                        self._extract_level_data(result, level.level, part)
                        matched_levels += 1
                        break

        result.match_confidence = matched_levels / total_levels if total_levels > 0 else 0.0

        return result

    def parse_blend_filename(self, filename: str) -> ParsedPath:
        """
        Parse a .blend filename to extract shot identity and version.

        Args:
            filename: Filename (not full path)

        Returns:
            ParsedPath with extracted components
        """
        result = ParsedPath()

        for pattern in self._blend_patterns:
            match = pattern.match(filename)
            if match:
                groups = match.groupdict()

                if 'shot' in groups:
                    result.shot = groups['shot']
                    # Try to extract shot number
                    result.shot_num = self._extract_number(groups['shot'])

                if 'version' in groups:
                    try:
                        result.version = int(groups['version'])
                    except (ValueError, TypeError):
                        pass

                if 'sequence' in groups:
                    result.sequence = groups['sequence']
                    result.sequence_num = self._extract_number(groups['sequence'])

                if 'episode' in groups:
                    result.episode = groups['episode']
                    result.episode_num = self._extract_number(groups['episode'])

                if 'scene' in groups:
                    result.scene = groups['scene']
                    result.scene_num = self._extract_number(groups['scene'])

                result.match_confidence = 1.0
                break

        return result

    def is_shot_folder(self, folder_path: Path) -> bool:
        """
        Check if a folder matches the shot level of the schema.

        Args:
            folder_path: Path to check

        Returns:
            True if folder is a valid shot folder
        """
        if not folder_path.is_dir():
            return False

        # Find the shot level in hierarchy
        shot_level = None
        for level in self.config.hierarchy_levels:
            if level.level == 'shot':
                shot_level = level
                break

        if not shot_level:
            # No explicit shot level - check for .blend files
            return any(folder_path.glob('*.blend'))

        # Check folder_contains requirement
        if shot_level.folder_contains:
            ext = shot_level.folder_contains
            if not ext.startswith('.'):
                ext = '.' + ext
            return any(folder_path.glob(f'*{ext}'))

        # Check pattern match
        if shot_level.pattern:
            compiled = self._compiled_patterns.get('shot')
            if compiled:
                return bool(compiled.match(folder_path.name))

        return False

    def find_blend_files(self, folder_path: Path) -> List[Path]:
        """
        Find all .blend files in a folder that match schema patterns.

        Args:
            folder_path: Shot folder to search

        Returns:
            List of matching .blend file paths
        """
        if not folder_path.is_dir():
            return []

        blend_files = list(folder_path.glob('*.blend'))

        # Filter by patterns if specified
        if self._blend_patterns:
            matched = []
            for f in blend_files:
                for pattern in self._blend_patterns:
                    if pattern.match(f.name):
                        matched.append(f)
                        break
            # If no matches, return all blend files anyway
            return matched if matched else blend_files

        return blend_files

    def get_playblast_folder(self, shot_folder: Path) -> Path:
        """
        Get the expected playblast folder path for a shot.

        Args:
            shot_folder: Path to shot folder

        Returns:
            Path to PlayBlast folder (may not exist)
        """
        return shot_folder / self.config.playblast_folder

    # ==================== MULTI-CAMERA REFERENCE DETECTION ====================

    def is_reference_detection_enabled(self) -> bool:
        """Check if reference pattern detection is enabled."""
        return self.config.reference_detection_enabled

    def parse_reference_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Parse a filename to detect if it's a view file (matches _ref## or _cam## pattern).

        Args:
            filename: Filename to check (e.g., "SH0010_ref01.blend")

        Returns:
            Dict with 'base', 'view', 'pattern_type' if matched, None otherwise
            Example: {'base': 'SH0010', 'view': '01', 'pattern_type': 'ref'}
        """
        if not self._reference_patterns:
            return None

        for pattern in self._reference_patterns:
            match = pattern.match(filename)
            if match:
                groups = match.groupdict()
                # Determine pattern type from the pattern string
                pattern_str = pattern.pattern
                if '_ref' in pattern_str:
                    pattern_type = 'ref'
                elif '_cam' in pattern_str:
                    pattern_type = 'cam'
                else:
                    pattern_type = 'unknown'

                return {
                    'base': groups.get('base'),
                    'view': groups.get('view'),
                    'pattern_type': pattern_type,
                }

        return None

    def is_view_file(self, filename: str) -> bool:
        """
        Check if a filename matches a view pattern (_ref## or _cam##).

        Args:
            filename: Filename to check

        Returns:
            True if the file is a view file
        """
        return self.parse_reference_filename(filename) is not None

    def get_master_base_name(self, view_filename: str) -> Optional[str]:
        """
        Extract the master base name from a view filename.

        Args:
            view_filename: View filename (e.g., "SH0010_ref01.blend")

        Returns:
            Master base name (e.g., "SH0010") or None if not a view file
        """
        parsed = self.parse_reference_filename(view_filename)
        if parsed:
            return parsed['base']
        return None

    def find_master_for_views(self, folder_path: Path, view_base_name: str) -> Optional[Path]:
        """
        Find the master .blend file for a set of views.

        Looks for a .blend file that matches the base name without _ref## or _cam## suffix.

        Args:
            folder_path: Folder containing the files
            view_base_name: Base name extracted from view files (e.g., "SH0010")

        Returns:
            Path to master file if found
        """
        if not folder_path.is_dir():
            return None

        # Look for exact match: base_name.blend
        master_path = folder_path / f"{view_base_name}.blend"
        if master_path.exists():
            return master_path

        # Look for versioned master: base_name_v###.blend (but not _ref## or _cam##)
        for blend_file in folder_path.glob(f"{view_base_name}*.blend"):
            filename = blend_file.name
            # Skip if it's a view file
            if self.is_view_file(filename):
                continue
            # Found a non-view file with matching base name
            return blend_file

        return None

    def classify_blend_files(self, folder_path: Path) -> Dict[str, Any]:
        """
        Classify all .blend files in a folder into master, views, and standalone.

        Args:
            folder_path: Folder to analyze

        Returns:
            Dict with:
            - 'master': Path to master file (if found)
            - 'views': List of (path, view_info) tuples for view files
            - 'standalone': List of paths for files that don't fit the pattern
        """
        result = {
            'master': None,
            'views': [],
            'standalone': [],
        }

        if not folder_path.is_dir():
            return result

        blend_files = list(folder_path.glob('*.blend'))
        if not blend_files:
            return result

        # First pass: identify view files and collect base names
        views = []
        base_names = set()
        non_views = []

        for blend_file in blend_files:
            view_info = self.parse_reference_filename(blend_file.name)
            if view_info:
                views.append((blend_file, view_info))
                base_names.add(view_info['base'])
            else:
                non_views.append(blend_file)

        # If no views found, all files are standalone
        if not views:
            result['standalone'] = non_views
            return result

        # Find master among non-view files
        # Master should have a base name that matches the views
        for blend_file in non_views:
            stem = blend_file.stem
            # Check if this file's name (without version suffix) matches a view base
            # Strip version suffix like _v001, _v002, etc.
            base_stem = stem
            version_match = re.search(r'_v\d{3}$', stem)
            if version_match:
                base_stem = stem[:version_match.start()]

            if base_stem in base_names:
                result['master'] = blend_file
                # Remaining non-views (that aren't master) are standalone
                for other in non_views:
                    if other != blend_file:
                        result['standalone'].append(other)
                break
        else:
            # No master found - all non-views are standalone
            result['standalone'] = non_views

        result['views'] = views
        return result

    def validate_config(self) -> List[str]:
        """
        Validate the current schema configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check for at least one hierarchy level
        if not self.config.hierarchy_levels:
            errors.append("At least one hierarchy level must be defined")

        # Check for shot level
        has_shot = any(l.level == 'shot' for l in self.config.hierarchy_levels)
        has_folder_contains = any(l.folder_contains for l in self.config.hierarchy_levels)
        if not has_shot and not has_folder_contains:
            errors.append("Schema must define a 'shot' level or use 'folder_contains'")

        # Validate regex patterns
        for level in self.config.hierarchy_levels:
            if level.pattern:
                try:
                    re.compile(level.pattern)
                except re.error as e:
                    errors.append(f"Invalid regex for level '{level.level}': {e}")

        # Validate blend file patterns
        for pattern in self.config.blend_file_patterns:
            try:
                compiled = re.compile(pattern)
                # Check for shot group
                if 'shot' not in compiled.groupindex:
                    errors.append(f"Blend pattern missing (?P<shot>...) group: {pattern}")
            except re.error as e:
                errors.append(f"Invalid blend file pattern: {e}")

        # Validate playblast pattern
        try:
            compiled = re.compile(self.config.playblast_pattern)
            if 'version' not in compiled.groupindex:
                errors.append("Playblast pattern missing (?P<version>...) group")
        except re.error as e:
            errors.append(f"Invalid playblast pattern: {e}")

        return errors

    def _extract_level_data(self, result: ParsedPath, level: str, value: str):
        """Extract data from a matched level component."""
        num = self._extract_number(value)

        if level == 'show':
            result.show = value
        elif level == 'episode':
            result.episode = value
            result.episode_num = num
        elif level == 'sequence':
            result.sequence = value
            result.sequence_num = num
        elif level == 'scene':
            result.scene = value
            result.scene_num = num
        elif level == 'shot':
            result.shot = value
            result.shot_num = num

    def _extract_number(self, value: str) -> Optional[int]:
        """Extract trailing number from a string."""
        if not value:
            return None
        match = re.search(r'(\d+)$', value)
        if match:
            return int(match.group(1))
        return None


# Built-in schema presets
SCHEMA_PRESETS: Dict[str, Dict[str, Any]] = {
    'simple_shot': {
        'name': 'Simple Shot',
        'hierarchy_levels': [
            {'level': 'shot', 'folder_contains': '.blend', 'examples': 'SH010, MyShot, shot_01'}
        ],
        'blend_file_patterns': [r'^(?P<shot>[\w]+)\.blend$'],
    },
    'netflix_vfx': {
        'name': 'Netflix VFX',
        'hierarchy_levels': [
            {'level': 'show', 'pattern': r'^[A-Z][A-Za-z0-9_]*$', 'examples': 'MyShow, ARCANE, Project_X'},
            {'level': 'episode', 'pattern': r'^EP\d{2}$', 'examples': 'EP01, EP12'},
            {'level': 'sequence', 'pattern': r'^(SQ|SEQ)\d{3}$', 'examples': 'SQ005, SEQ120'},
            {'level': 'shot', 'folder_contains': '.blend', 'examples': 'SH010, SH020'}
        ],
        'blend_file_patterns': [
            r'^(?P<shot>[A-Z]+\d+)_v(?P<version>\d{3})\.blend$',
            r'^(?P<shot>[A-Za-z0-9_]+)\.blend$'
        ],
    },
    'shotgrid_standard': {
        'name': 'ShotGrid Standard',
        'hierarchy_levels': [
            {'level': 'show', 'pattern': r'^[A-Za-z0-9_]+$', 'examples': 'my_show, Project01'},
            {'level': 'sequence', 'pattern': r'^(SQ|SEQ|sq)_?\d{3,4}$', 'examples': 'SQ005, SEQ_0100, sq005'},
            {'level': 'shot', 'pattern': r'^(SH|SHOT|sh)_?\d{3,4}$', 'examples': 'SH010, SHOT_0020, sh005'}
        ],
        'blend_file_patterns': [
            r'^(?P<shot>[\w]+)_v(?P<version>\d{3})\.blend$',
            r'^(?P<shot>[\w]+)\.blend$'
        ],
    },
    'tv_flat': {
        'name': 'TV Flat',
        'hierarchy_levels': [
            {'level': 'episode', 'pattern': r'^EP[_\-]?\d+$', 'examples': 'EP01, EP_02, EP-12'},
            {'level': 'shot', 'folder_contains': '.blend', 'examples': 'SH010, MyShot'},
        ],
        'blend_file_patterns': [
            r'^(?P<shot>[\w]+)_v(?P<version>\d{3})\.blend$',
            r'^(?P<shot>[\w]+)\.blend$',
        ],
    },
}


def get_preset(name: str) -> FolderSchemaParser:
    """Get a built-in schema preset by name."""
    if name not in SCHEMA_PRESETS:
        raise ValueError(f"Unknown preset: {name}. Available: {list(SCHEMA_PRESETS.keys())}")
    return FolderSchemaParser.from_dict(SCHEMA_PRESETS[name])


# Add from_preset as class method for convenience
FolderSchemaParser.from_preset = staticmethod(get_preset)


__all__ = [
    'HierarchyLevel',
    'SchemaConfig',
    'ParsedPath',
    'FolderSchemaParser',
    'SCHEMA_PRESETS',
    'get_preset',
]
