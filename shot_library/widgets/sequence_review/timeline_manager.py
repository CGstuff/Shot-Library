"""
Sequence Timeline Manager

Manages the unified timeline across all shots in a sequence.
Handles frame offset calculations and shot boundary detection.
"""

import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from ...utils.video_resolver import ShotVideoResolver

logger = logging.getLogger(__name__)


class SequenceTimelineManager:
    """
    Manages timeline calculations for sequence review.

    Provides:
    - Frame offset calculation for each shot
    - Global frame <-> local frame conversion
    - Shot boundary information for ruler display
    - Total sequence duration tracking
    """

    def __init__(self):
        self._shot_frame_offsets: List[int] = []
        self._shot_frame_counts: List[int] = []
        self._shot_fps_values: List[float] = []
        self._total_frames: int = 0
        self._default_fps: float = 24.0
        self._boundaries: List[Dict] = []

    @property
    def total_frames(self) -> int:
        """Total frames in entire sequence."""
        return self._total_frames

    @property
    def shot_count(self) -> int:
        """Number of shots in sequence."""
        return len(self._shot_frame_offsets)

    @property
    def boundaries(self) -> List[Dict]:
        """Shot boundaries for frame ruler display."""
        return self._boundaries

    @property
    def default_fps(self) -> float:
        """Default FPS (from first video or 24.0)."""
        return self._default_fps

    def init_from_shots(self, shots: List[Dict]) -> float:
        """
        Initialize timeline from list of shots.

        Scans all shots to get frame counts and calculates
        cumulative offsets for unified timeline.

        Args:
            shots: List of shot dictionaries

        Returns:
            FPS from first video (for timecode display)
        """
        self._shot_frame_offsets = []
        self._shot_frame_counts = []
        self._shot_fps_values = []
        self._boundaries = []

        cumulative_frames = 0
        first_fps = None

        for i, shot in enumerate(shots):
            # Store starting frame offset
            self._shot_frame_offsets.append(cumulative_frames)

            # Get video info
            video_path = ShotVideoResolver.get_existing_video_path(shot)
            frame_count = 0
            fps = 24.0

            if video_path:
                frame_count, fps = self._get_video_info(video_path)

                # Store first video's FPS
                if first_fps is None and fps > 0:
                    first_fps = fps

            # Default to 100 frames if we can't determine
            if frame_count <= 0:
                frame_count = 100

            self._shot_frame_counts.append(frame_count)
            self._shot_fps_values.append(fps)

            # Create boundary marker
            shot_name = shot.get('shot_name', shot.get('name', f'Shot {i + 1}'))
            self._boundaries.append({
                'frame': cumulative_frames,
                'end_frame': cumulative_frames + frame_count - 1,
                'name': shot_name,
                'index': i,
                'frame_count': frame_count
            })

            cumulative_frames += frame_count

        self._total_frames = cumulative_frames
        self._default_fps = first_fps or 24.0

        logger.debug(
            f"Timeline initialized: {len(shots)} shots, "
            f"{self._total_frames} total frames, {self._default_fps}fps"
        )

        return self._default_fps

    def _get_video_info(self, video_path: Path) -> Tuple[int, float]:
        """
        Get frame count and FPS from video file.

        Args:
            video_path: Path to video file

        Returns:
            Tuple of (frame_count, fps)
        """
        try:
            import cv2

            cap = cv2.VideoCapture(str(video_path))
            if cap.isOpened():
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()

                if frame_count > 0 and fps > 0:
                    return frame_count, fps

        except Exception as e:
            logger.warning(f"Failed to get video info for {video_path}: {e}")

        return 0, 24.0

    def get_global_frame(self, shot_index: int, local_frame: int) -> int:
        """
        Convert shot index + local frame to global sequence frame.

        Args:
            shot_index: Index of shot (0-based)
            local_frame: Frame number within the shot

        Returns:
            Global frame number in the sequence
        """
        if 0 <= shot_index < len(self._shot_frame_offsets):
            return self._shot_frame_offsets[shot_index] + local_frame
        return local_frame

    def get_shot_from_global_frame(self, global_frame: int) -> Tuple[int, int]:
        """
        Convert global frame to shot index and local frame.

        Args:
            global_frame: Global frame number in sequence

        Returns:
            Tuple of (shot_index, local_frame)
        """
        # Search from end (more efficient for sequential playback)
        for i in range(len(self._shot_frame_offsets) - 1, -1, -1):
            if global_frame >= self._shot_frame_offsets[i]:
                local_frame = global_frame - self._shot_frame_offsets[i]
                return (i, local_frame)

        return (0, 0)

    def get_shot_offset(self, shot_index: int) -> int:
        """
        Get the starting frame offset for a shot.

        Args:
            shot_index: Index of shot

        Returns:
            Frame offset (global frame where shot starts)
        """
        if 0 <= shot_index < len(self._shot_frame_offsets):
            return self._shot_frame_offsets[shot_index]
        return 0

    def get_shot_frame_count(self, shot_index: int) -> int:
        """
        Get the frame count for a specific shot.

        Args:
            shot_index: Index of shot

        Returns:
            Number of frames in the shot
        """
        if 0 <= shot_index < len(self._shot_frame_counts):
            return self._shot_frame_counts[shot_index]
        return 0

    def get_shot_fps(self, shot_index: int) -> float:
        """
        Get the FPS for a specific shot.

        Args:
            shot_index: Index of shot

        Returns:
            FPS of the shot's video
        """
        if 0 <= shot_index < len(self._shot_fps_values):
            return self._shot_fps_values[shot_index]
        return self._default_fps

    def get_shot_end_frame(self, shot_index: int) -> int:
        """
        Get the ending global frame for a shot.

        Args:
            shot_index: Index of shot

        Returns:
            Last global frame of the shot
        """
        if 0 <= shot_index < len(self._shot_frame_offsets):
            offset = self._shot_frame_offsets[shot_index]
            count = self._shot_frame_counts[shot_index]
            return offset + count - 1
        return 0

    def is_valid_shot_index(self, shot_index: int) -> bool:
        """
        Check if shot index is valid.

        Args:
            shot_index: Index to check

        Returns:
            True if index is valid
        """
        return 0 <= shot_index < len(self._shot_frame_offsets)

    def clamp_local_frame(self, shot_index: int, local_frame: int) -> int:
        """
        Clamp local frame to valid range for shot.

        Args:
            shot_index: Index of shot
            local_frame: Frame number to clamp

        Returns:
            Clamped frame number
        """
        if not self.is_valid_shot_index(shot_index):
            return 0

        max_frame = self._shot_frame_counts[shot_index] - 1
        return max(0, min(local_frame, max_frame))

    def get_progress_percentage(self, global_frame: int) -> float:
        """
        Get playback progress as percentage.

        Args:
            global_frame: Current global frame

        Returns:
            Progress percentage (0.0 to 100.0)
        """
        if self._total_frames <= 0:
            return 0.0

        return (global_frame / self._total_frames) * 100.0

    def get_shot_boundaries(self) -> List[Dict]:
        """
        Get shot boundary information for frame ruler.

        Returns:
            List of boundary dictionaries with:
            - frame: Starting frame
            - end_frame: Ending frame
            - name: Shot name
            - index: Shot index
            - frame_count: Number of frames
        """
        return self._boundaries.copy()

    def clear(self) -> None:
        """Clear all timeline data."""
        self._shot_frame_offsets = []
        self._shot_frame_counts = []
        self._shot_fps_values = []
        self._boundaries = []
        self._total_frames = 0


__all__ = ['SequenceTimelineManager']
