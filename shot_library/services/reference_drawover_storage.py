"""
ReferenceDrawoverStorage - Drawover storage for Analysis Mode

Stores reference video drawovers separately from production annotations.
Uses video path hash as identifier instead of animation UUID.
"""

import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from .drawover_storage import DrawoverStorage, DrawoverCache


class ReferenceDrawoverStorage(DrawoverStorage):
    """
    Drawover storage for Analysis Mode reference videos.

    Differences from production DrawoverStorage:
    - Uses ~/.shot_library/analysis/drawovers/ as base path
    - Uses video path hash instead of animation UUID
    - Uses "reference" as version label (no versioning)

    File structure:
        ~/.shot_library/analysis/drawovers/{video_hash}/reference/
        ├── f0125.json       # Frame 125 vector data
        ├── f0125.png        # Frame 125 PNG cache
        └── manifest.json    # Index of all drawovers
    """

    VERSION_LABEL = "reference"

    @classmethod
    def get_base_path(cls) -> Path:
        """Get the base path for analysis mode drawover storage."""
        return Path.home() / ".shot_library" / "analysis" / "drawovers"

    def __init__(self):
        """Initialize with analysis mode base path."""
        base_path = self.get_base_path()
        base_path.mkdir(parents=True, exist_ok=True)
        # Skip parent __init__ and set up directly
        self._base = base_path
        self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_video_id(video_path: str) -> str:
        """
        Generate stable identifier from video path.

        Uses file path hash so annotations persist even if file is renamed
        but path stays same.
        """
        normalized = str(Path(video_path).resolve())
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    # ==================== Convenience Methods ====================

    def save_drawover_for_video(
        self,
        video_path: str,
        frame: int,
        strokes: List[Dict],
        author: str = '',
        canvas_size: Tuple[int, int] = (1920, 1080)
    ) -> bool:
        """
        Save drawover data for a video frame.

        Args:
            video_path: Path to the video file
            frame: Frame number
            strokes: List of stroke dictionaries
            author: Current user
            canvas_size: Video dimensions

        Returns:
            True if saved successfully
        """
        video_id = self.get_video_id(video_path)
        return self.save_drawover(
            video_id, self.VERSION_LABEL, frame, strokes, author, canvas_size
        )

    def load_drawover_for_video(
        self,
        video_path: str,
        frame: int
    ) -> Optional[Dict]:
        """Load drawover data for a video frame."""
        video_id = self.get_video_id(video_path)
        return self.load_drawover(video_id, self.VERSION_LABEL, frame)

    def delete_drawover_for_video(
        self,
        video_path: str,
        frame: int
    ) -> bool:
        """Delete a frame's drawover files."""
        video_id = self.get_video_id(video_path)
        return self.delete_drawover(video_id, self.VERSION_LABEL, frame)

    def has_drawover_for_video(
        self,
        video_path: str,
        frame: int
    ) -> bool:
        """Check if a video frame has drawover data."""
        video_id = self.get_video_id(video_path)
        return self.has_drawover(video_id, self.VERSION_LABEL, frame)

    def list_frames_with_drawovers_for_video(
        self,
        video_path: str
    ) -> List[int]:
        """Get list of frames that have drawovers for a video."""
        video_id = self.get_video_id(video_path)
        return self.list_frames_with_drawovers(video_id, self.VERSION_LABEL)

    def add_stroke_for_video(
        self,
        video_path: str,
        frame: int,
        stroke: Dict,
        author: str = '',
        canvas_size: Tuple[int, int] = (1920, 1080)
    ) -> Optional[str]:
        """Add a single stroke to a video frame's drawover."""
        video_id = self.get_video_id(video_path)
        return self.add_stroke(
            video_id, self.VERSION_LABEL, frame, stroke, author, canvas_size
        )

    def remove_stroke_for_video(
        self,
        video_path: str,
        frame: int,
        stroke_id: str,
        soft_delete: bool = False,  # Analysis mode uses hard delete by default
        deleted_by: str = ''
    ) -> bool:
        """Remove a stroke from a video frame's drawover."""
        video_id = self.get_video_id(video_path)
        return self.remove_stroke(
            video_id, self.VERSION_LABEL, frame, stroke_id, soft_delete, deleted_by
        )

    def clear_frame_for_video(
        self,
        video_path: str,
        frame: int,
        soft_delete: bool = False,  # Analysis mode uses hard delete by default
        deleted_by: str = ''
    ) -> bool:
        """Clear all strokes on a video frame."""
        video_id = self.get_video_id(video_path)
        return self.clear_frame(
            video_id, self.VERSION_LABEL, frame, soft_delete, deleted_by
        )

    def render_to_png_for_video(
        self,
        video_path: str,
        frame: int,
        size: Tuple[int, int]
    ) -> Optional[Path]:
        """Render video frame drawover to PNG."""
        video_id = self.get_video_id(video_path)
        return self.render_to_png(video_id, self.VERSION_LABEL, frame, size)

    def delete_all_for_video(self, video_path: str) -> bool:
        """Delete ALL drawover files for a video."""
        video_id = self.get_video_id(video_path)
        return self.delete_all_for_version(video_id, self.VERSION_LABEL)

    def get_manifest_for_video(self, video_path: str) -> Optional[Dict]:
        """Get manifest data for a video."""
        video_id = self.get_video_id(video_path)
        return self.get_manifest(video_id, self.VERSION_LABEL)

    # ==================== Path Getters ====================

    def get_drawover_dir_for_video(self, video_path: str) -> Path:
        """Get directory for a video's drawovers."""
        video_id = self.get_video_id(video_path)
        return self.get_drawover_dir(video_id, self.VERSION_LABEL)

    def get_drawover_path_for_video(self, video_path: str, frame: int) -> Path:
        """Get path for a video frame's drawover JSON."""
        video_id = self.get_video_id(video_path)
        return self.get_drawover_path(video_id, self.VERSION_LABEL, frame)

    def get_png_cache_path_for_video(self, video_path: str, frame: int) -> Path:
        """Get path for a video frame's PNG cache."""
        video_id = self.get_video_id(video_path)
        return self.get_png_cache_path(video_id, self.VERSION_LABEL, frame)


# ==================== Singleton ====================

_reference_storage_instance: Optional[ReferenceDrawoverStorage] = None
_reference_cache_instance: Optional[DrawoverCache] = None


def get_reference_drawover_storage() -> ReferenceDrawoverStorage:
    """Get singleton ReferenceDrawoverStorage instance."""
    global _reference_storage_instance
    if _reference_storage_instance is None:
        _reference_storage_instance = ReferenceDrawoverStorage()
    return _reference_storage_instance


def get_reference_drawover_cache() -> DrawoverCache:
    """Get singleton DrawoverCache instance for reference videos."""
    global _reference_cache_instance
    if _reference_cache_instance is None:
        _reference_cache_instance = DrawoverCache()
    return _reference_cache_instance


__all__ = [
    'ReferenceDrawoverStorage',
    'get_reference_drawover_storage',
    'get_reference_drawover_cache'
]
