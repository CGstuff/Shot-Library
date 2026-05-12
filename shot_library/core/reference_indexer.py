"""
Reference Indexer - Video discovery for Analysis Mode

Simple indexer that discovers ALL video files in a folder without
any naming conventions or version parsing. Used for reference video
analysis (like SyncSketch/Keyframe Pro).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Set

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class VideoMetadata:
    """Metadata extracted from a video file using cv2."""
    duration_ms: int
    fps: float
    width: int
    height: int
    frame_count: int


@dataclass
class DiscoveredVideo:
    """A video file discovered for analysis."""
    file_path: Path
    name: str  # filename without extension
    metadata: Optional[VideoMetadata]
    created_at: datetime
    file_size: int  # bytes


class ReferenceIndexer(QObject):
    """
    Discovers all video files in a folder for Analysis Mode.

    No naming conventions, no versioning - just finds all video files.
    """

    # Signals
    video_discovered = pyqtSignal(object)  # DiscoveredVideo

    # Supported video extensions
    VIDEO_EXTENSIONS: Set[str] = {
        '.mp4', '.mov', '.avi', '.mkv', '.webm',
        '.m4v', '.wmv', '.flv', '.ogv'
    }

    def __init__(self, parent=None):
        super().__init__(parent)

    def discover_videos(
        self,
        folder: Path,
        recursive: bool = False
    ) -> List[DiscoveredVideo]:
        """
        Find all video files in a folder.

        Args:
            folder: Directory to search
            recursive: If True, search subdirectories too

        Returns:
            List of discovered videos sorted by name (case-insensitive)
        """
        folder = Path(folder) if not isinstance(folder, Path) else folder

        if not folder.exists() or not folder.is_dir():
            return []

        discovered: List[DiscoveredVideo] = []

        # Build list of video files
        video_files: List[Path] = []
        if recursive:
            for ext in self.VIDEO_EXTENSIONS:
                video_files.extend(folder.rglob(f'*{ext}'))
                video_files.extend(folder.rglob(f'*{ext.upper()}'))
        else:
            for ext in self.VIDEO_EXTENSIONS:
                video_files.extend(folder.glob(f'*{ext}'))
                video_files.extend(folder.glob(f'*{ext.upper()}'))

        # Remove duplicates (from case variants) and process
        seen_paths: Set[str] = set()
        for video_path in video_files:
            path_key = str(video_path).lower()
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)

            try:
                stat = video_path.stat()
                video = DiscoveredVideo(
                    file_path=video_path,
                    name=video_path.stem,
                    metadata=self.extract_metadata(video_path),
                    created_at=datetime.fromtimestamp(stat.st_mtime),
                    file_size=stat.st_size
                )
                discovered.append(video)
                self.video_discovered.emit(video)
            except (OSError, IOError):
                # Skip files we can't access
                continue

        # Sort by name (case-insensitive)
        discovered.sort(key=lambda v: v.name.lower())
        return discovered

    def discover_video(self, video_path: Path) -> Optional[DiscoveredVideo]:
        """
        Create a DiscoveredVideo for a single file.

        Args:
            video_path: Path to video file

        Returns:
            DiscoveredVideo or None if file doesn't exist/isn't a video
        """
        video_path = Path(video_path) if not isinstance(video_path, Path) else video_path

        if not video_path.exists():
            return None

        if video_path.suffix.lower() not in self.VIDEO_EXTENSIONS:
            return None

        try:
            stat = video_path.stat()
            return DiscoveredVideo(
                file_path=video_path,
                name=video_path.stem,
                metadata=self.extract_metadata(video_path),
                created_at=datetime.fromtimestamp(stat.st_mtime),
                file_size=stat.st_size
            )
        except (OSError, IOError):
            return None

    def extract_metadata(self, video_path: Path) -> Optional[VideoMetadata]:
        """
        Extract video metadata from a video file.

        Uses opencv-python to read video properties.

        Args:
            video_path: Path to video file

        Returns:
            VideoMetadata or None if extraction fails
        """
        try:
            import cv2

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return None

            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Calculate duration
            duration_ms = int((frame_count / fps) * 1000) if fps > 0 else 0

            cap.release()

            return VideoMetadata(
                duration_ms=duration_ms,
                fps=fps,
                width=width,
                height=height,
                frame_count=frame_count
            )

        except ImportError:
            return None
        except Exception:
            return None

    def get_sibling_videos(self, video_path: Path) -> List[DiscoveredVideo]:
        """
        Get all videos in the same folder as the given video.

        Useful for populating the video list in VersionHistoryDialog
        when in Analysis Mode.

        Args:
            video_path: Path to a video file

        Returns:
            List of all videos in the same folder (including the input video)
        """
        video_path = Path(video_path) if not isinstance(video_path, Path) else video_path

        if not video_path.exists():
            return []

        parent_folder = video_path.parent
        return self.discover_videos(parent_folder, recursive=False)

    def is_video_file(self, file_path: Path) -> bool:
        """Check if a file is a supported video format."""
        return file_path.suffix.lower() in self.VIDEO_EXTENSIONS


# ==================== Singleton ====================

_indexer_instance: Optional[ReferenceIndexer] = None


def get_reference_indexer() -> ReferenceIndexer:
    """Get singleton ReferenceIndexer instance."""
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = ReferenceIndexer()
    return _indexer_instance


__all__ = [
    'VideoMetadata',
    'DiscoveredVideo',
    'ReferenceIndexer',
    'get_reference_indexer',
]
