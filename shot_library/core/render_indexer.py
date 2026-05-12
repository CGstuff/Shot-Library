"""
RenderIndexer - Discovery for folder-based image sequence renders

Unlike playblasts/lookdevs (filename versioning: shot_PB_v001.mp4),
renders use folder-based versioning:
- Render/current/ - Active render (filenames NEVER change for NLE compatibility)
- Render/_archive/v001/, v002/ - Archived versions

This module provides discovery and indexing for render sequences.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredRender:
    """
    Information about a discovered render sequence.

    Attributes:
        folder_path: Path to render folder (current/ or _archive/vXXX/)
        shot_folder: Parent shot folder path
        version: Version number (0 for current, 1+ for archives)
        is_current: True if this is the active render in current/
        frame_start: First frame number in sequence
        frame_end: Last frame number in sequence
        frame_count: Total number of frames
        extension: File extension (".png" or ".exr")
        file_pattern: Pattern for frame files (e.g., "shot_010_%04d.exr")
        proxy_path: Path to proxy MP4 if generated
        json_metadata: Parsed JSON sidecar data if present
        created_at: When the render was created (from file mtime)
        render_engine: Render engine used (from metadata)
        samples: Sample count (from metadata)
        render_time_seconds: Total render time (from metadata)
        resolution_x: Horizontal resolution
        resolution_y: Vertical resolution
    """
    folder_path: Path
    shot_folder: Path
    version: int
    is_current: bool
    frame_start: int = 1
    frame_end: int = 1
    frame_count: int = 0
    extension: str = ".png"
    file_pattern: str = ""
    proxy_path: Optional[Path] = None
    json_metadata: Optional[Dict] = None
    created_at: Optional[datetime] = None
    render_engine: Optional[str] = None
    samples: Optional[int] = None
    render_time_seconds: Optional[float] = None
    resolution_x: Optional[int] = None
    resolution_y: Optional[int] = None


class RenderIndexer(QObject):
    """
    Discovers and indexes render image sequences in shot folders.

    Render folder structure:
        shot_folder/
            Render/
                current/           <- Active render (version 0)
                    shot_010_0001.exr
                    shot_010_0002.exr
                    ...
                    render_metadata.json  <- Optional metadata sidecar
                    proxy.mp4             <- Optional proxy video
                _archive/
                    v001/          <- Archived version 1
                        shot_010_0001.exr
                        ...
                    v002/          <- Archived version 2
                        ...

    Usage:
        indexer = RenderIndexer()
        renders = indexer.discover_renders(shot_folder)
        current = indexer.get_current_render(shot_folder)
    """

    # Signals
    render_discovered = pyqtSignal(str, object)  # shot_uuid, DiscoveredRender

    # Supported image extensions
    SUPPORTED_EXTENSIONS = {".png", ".exr", ".tiff", ".tif", ".jpg", ".jpeg", ".tga", ".bmp", ".dpx", ".hdr"}

    # Frame number patterns (common naming conventions)
    FRAME_PATTERNS = [
        # Pattern: shot_name_####.ext or shot_name.####.ext
        re.compile(r'^(?P<base>.+?)[\._](?P<frame>\d{3,6})\.(?P<ext>\w+)$'),
        # Pattern: ####.ext (frame number only)
        re.compile(r'^(?P<frame>\d{3,6})\.(?P<ext>\w+)$'),
        # Pattern: shot_name_f####.ext
        re.compile(r'^(?P<base>.+?)_f(?P<frame>\d{3,6})\.(?P<ext>\w+)$'),
    ]

    # Archive version folder pattern
    ARCHIVE_VERSION_PATTERN = re.compile(r'^v(\d{3,4})$', re.IGNORECASE)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

    def discover_renders(self, shot_folder: Path) -> List[DiscoveredRender]:
        """
        Discover all renders (current and archived) for a shot.

        Args:
            shot_folder: Path to shot folder

        Returns:
            List of DiscoveredRender objects, sorted by version (current first)
        """
        renders = []
        render_root = shot_folder / "Render"

        if not render_root.exists():
            return renders

        # Check current/
        current_render = self._discover_in_folder(
            render_root / "current",
            shot_folder,
            version=0,
            is_current=True
        )
        if current_render:
            renders.append(current_render)

        # Check _archive/vXXX/
        archive_dir = render_root / "_archive"
        if archive_dir.exists():
            for version_dir in sorted(archive_dir.iterdir()):
                if not version_dir.is_dir():
                    continue

                match = self.ARCHIVE_VERSION_PATTERN.match(version_dir.name)
                if match:
                    version = int(match.group(1))
                    archived_render = self._discover_in_folder(
                        version_dir,
                        shot_folder,
                        version=version,
                        is_current=False
                    )
                    if archived_render:
                        renders.append(archived_render)
                else:
                    logger.debug(
                        "Skipping archive folder %s: name does not match v### / v#### pattern",
                        version_dir,
                    )

        # Sort by version (0/current first, then ascending)
        renders.sort(key=lambda r: (0 if r.is_current else 1, r.version))

        return renders

    def get_current_render(self, shot_folder: Path) -> Optional[DiscoveredRender]:
        """
        Get the active render from current/ folder.

        Args:
            shot_folder: Path to shot folder

        Returns:
            DiscoveredRender for current version, or None
        """
        render_root = shot_folder / "Render"
        current_dir = render_root / "current"

        if not current_dir.exists():
            return None

        return self._discover_in_folder(
            current_dir,
            shot_folder,
            version=0,
            is_current=True
        )

    def get_archived_renders(self, shot_folder: Path) -> List[DiscoveredRender]:
        """
        Get all archived render versions.

        Args:
            shot_folder: Path to shot folder

        Returns:
            List of archived DiscoveredRender objects
        """
        all_renders = self.discover_renders(shot_folder)
        return [r for r in all_renders if not r.is_current]

    def get_render_by_version(
        self,
        shot_folder: Path,
        version: int
    ) -> Optional[DiscoveredRender]:
        """
        Get a specific render version.

        Args:
            shot_folder: Path to shot folder
            version: Version number (0 for current)

        Returns:
            DiscoveredRender or None
        """
        renders = self.discover_renders(shot_folder)
        for render in renders:
            if render.version == version:
                return render
        return None

    def _discover_in_folder(
        self,
        folder: Path,
        shot_folder: Path,
        version: int,
        is_current: bool
    ) -> Optional[DiscoveredRender]:
        """
        Discover render sequence in a specific folder.

        Args:
            folder: Folder to scan (current/ or _archive/vXXX/)
            shot_folder: Parent shot folder
            version: Version number
            is_current: Whether this is the current render

        Returns:
            DiscoveredRender or None if no sequence found
        """
        if not folder.exists():
            return None

        # Find image files
        image_files = []
        for ext in self.SUPPORTED_EXTENSIONS:
            image_files.extend(folder.glob(f"*{ext}"))
            image_files.extend(folder.glob(f"*{ext.upper()}"))

        if not image_files:
            return None

        # Parse frame sequence
        sequence_info = self._parse_sequence(image_files)
        if not sequence_info:
            return None

        frame_start, frame_end, extension, pattern = sequence_info
        frame_count = frame_end - frame_start + 1

        # Check for proxy
        proxy_path = None
        for proxy_name in ["proxy.mp4", "preview.mp4", "render_proxy.mp4"]:
            candidate = folder / proxy_name
            if candidate.exists():
                proxy_path = candidate
                break

        # Load JSON metadata
        json_metadata = self._load_metadata(folder)

        # Get creation time from first frame
        created_at = None
        first_frame = self._get_frame_path(folder, pattern, frame_start, extension)
        if first_frame and first_frame.exists():
            created_at = datetime.fromtimestamp(first_frame.stat().st_mtime)

        # Extract metadata fields
        render_engine = None
        samples = None
        render_time = None
        resolution_x = None
        resolution_y = None

        if json_metadata:
            render_engine = json_metadata.get('render_engine')
            samples = json_metadata.get('samples')
            render_time = json_metadata.get('render_time_seconds')
            resolution_x = json_metadata.get('resolution_x') or json_metadata.get('resolution', [None, None])[0]
            resolution_y = json_metadata.get('resolution_y') or json_metadata.get('resolution', [None, None])[1]

        return DiscoveredRender(
            folder_path=folder,
            shot_folder=shot_folder,
            version=version,
            is_current=is_current,
            frame_start=frame_start,
            frame_end=frame_end,
            frame_count=frame_count,
            extension=extension,
            file_pattern=pattern,
            proxy_path=proxy_path,
            json_metadata=json_metadata,
            created_at=created_at,
            render_engine=render_engine,
            samples=samples,
            render_time_seconds=render_time,
            resolution_x=resolution_x,
            resolution_y=resolution_y,
        )

    def _parse_sequence(
        self,
        files: List[Path]
    ) -> Optional[Tuple[int, int, str, str]]:
        """
        Parse frame sequence from list of files.

        Args:
            files: List of image file paths

        Returns:
            Tuple of (frame_start, frame_end, extension, pattern) or None
        """
        if not files:
            return None

        frames = []
        extension = None
        base_name = None

        for file in files:
            for pattern in self.FRAME_PATTERNS:
                match = pattern.match(file.name)
                if match:
                    frame_num = int(match.group('frame'))
                    ext = "." + match.group('ext').lower()

                    if extension is None:
                        extension = ext
                    elif ext != extension:
                        continue  # Mixed extensions, skip

                    # Extract base name if present
                    if 'base' in match.groupdict():
                        if base_name is None:
                            base_name = match.group('base')
                        elif match.group('base') != base_name:
                            continue  # Different sequence, skip

                    frames.append(frame_num)
                    break

        if not frames:
            return None

        frames.sort()
        frame_start = frames[0]
        frame_end = frames[-1]

        # Build pattern string
        sample_file = files[0]
        for pattern in self.FRAME_PATTERNS:
            match = pattern.match(sample_file.name)
            if match:
                frame_str = match.group('frame')
                padding = len(frame_str)

                if 'base' in match.groupdict() and match.group('base'):
                    # Has base name: shot_010_%04d.exr
                    pattern_str = f"{match.group('base')}_%0{padding}d{extension}"
                else:
                    # Frame only: %04d.exr
                    pattern_str = f"%0{padding}d{extension}"

                return (frame_start, frame_end, extension, pattern_str)

        return None

    def _get_frame_path(
        self,
        folder: Path,
        pattern: str,
        frame: int,
        extension: str
    ) -> Optional[Path]:
        """
        Get path to specific frame file.

        Args:
            folder: Render folder
            pattern: Frame pattern string
            frame: Frame number
            extension: File extension

        Returns:
            Path to frame file
        """
        try:
            filename = pattern % frame
            return folder / filename
        except (TypeError, ValueError):
            # Pattern doesn't have %d placeholder, try direct
            return None

    def _load_metadata(self, folder: Path) -> Optional[Dict]:
        """
        Load JSON metadata sidecar if present.

        Args:
            folder: Render folder

        Returns:
            Parsed JSON dict or None
        """
        metadata_names = [
            "render_metadata.json",
            "metadata.json",
            "render.json",
        ]

        for name in metadata_names:
            metadata_path = folder / name
            if metadata_path.exists():
                try:
                    with open(metadata_path, 'r') as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to load render metadata from {metadata_path}: {e}")

        return None

    def get_sequence_file_list(
        self,
        render: DiscoveredRender
    ) -> List[Path]:
        """
        Get list of all frame files in a render sequence.

        Args:
            render: DiscoveredRender object

        Returns:
            List of frame file paths
        """
        files = []
        for frame in range(render.frame_start, render.frame_end + 1):
            frame_path = self._get_frame_path(
                render.folder_path,
                render.file_pattern,
                frame,
                render.extension
            )
            if frame_path and frame_path.exists():
                files.append(frame_path)
        return files

    def calculate_sequence_size(self, render: DiscoveredRender) -> int:
        """
        Calculate total file size of render sequence.

        Args:
            render: DiscoveredRender object

        Returns:
            Total size in bytes
        """
        total = 0
        for file in self.get_sequence_file_list(render):
            try:
                total += file.stat().st_size
            except OSError:
                pass
        return total


# Singleton instance
_indexer_instance: Optional[RenderIndexer] = None


def get_render_indexer() -> RenderIndexer:
    """Get the singleton RenderIndexer instance."""
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = RenderIndexer()
    return _indexer_instance


__all__ = [
    'DiscoveredRender',
    'RenderIndexer',
    'get_render_indexer',
]
