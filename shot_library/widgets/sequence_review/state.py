"""
State Dataclasses for SequenceReviewDialog

Groups the 45+ state variables from SequenceReviewDialog into
logical, focused dataclasses for better organization and type safety.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from PyQt6.QtGui import QImage

from ...services.media_engine import FrameResult, VideoInfo


@dataclass
class PlaybackState:
    """
    Current playback state.

    Tracks whether video is playing, auto-advance settings,
    and transition state between shots.
    """
    is_playing: bool = False
    auto_advance: bool = True
    waiting_for_next: bool = False
    playback_speed: float = 1.0
    loop: bool = False

    def start_playback(self) -> None:
        """Mark playback as started."""
        self.is_playing = True
        self.waiting_for_next = False

    def stop_playback(self) -> None:
        """Mark playback as stopped."""
        self.is_playing = False

    def prepare_for_next(self) -> None:
        """Mark as waiting for next shot to load."""
        self.waiting_for_next = True

    def reset(self) -> None:
        """Reset to initial state."""
        self.is_playing = False
        self.waiting_for_next = False


@dataclass
class TimelineState:
    """
    Unified timeline state across all shots.

    Manages the global timeline that spans all shots in the sequence,
    including frame offsets and current position.
    """
    show_timecode: bool = True  # True = HH:MM:SS:FF, False = frame number
    current_video_fps: float = 24.0
    shot_frame_offsets: List[int] = field(default_factory=list)
    shot_frame_counts: List[int] = field(default_factory=list)
    total_sequence_frames: int = 0
    current_global_frame: int = 0
    current_shot_index: int = 0

    def get_global_frame(self, shot_index: int, local_frame: int) -> int:
        """
        Convert shot index + local frame to global sequence frame.

        Args:
            shot_index: Index of shot in sequence
            local_frame: Frame number within the shot

        Returns:
            Global frame number across entire sequence
        """
        if shot_index < len(self.shot_frame_offsets):
            return self.shot_frame_offsets[shot_index] + local_frame
        return local_frame

    def get_shot_from_global_frame(self, global_frame: int) -> tuple:
        """
        Convert global frame to shot index and local frame.

        Args:
            global_frame: Global frame number in sequence

        Returns:
            Tuple of (shot_index, local_frame)
        """
        for i in range(len(self.shot_frame_offsets) - 1, -1, -1):
            if global_frame >= self.shot_frame_offsets[i]:
                local_frame = global_frame - self.shot_frame_offsets[i]
                return (i, local_frame)
        return (0, 0)

    def get_shot_local_frame(self, shot_index: int, global_frame: int) -> int:
        """
        Get local frame within a specific shot.

        Args:
            shot_index: Index of shot
            global_frame: Global frame number

        Returns:
            Local frame number within the shot
        """
        if shot_index < len(self.shot_frame_offsets):
            return global_frame - self.shot_frame_offsets[shot_index]
        return 0

    def update_position(self, shot_index: int, local_frame: int) -> None:
        """
        Update current position in timeline.

        Args:
            shot_index: Current shot index
            local_frame: Current frame within shot
        """
        self.current_shot_index = shot_index
        self.current_global_frame = self.get_global_frame(shot_index, local_frame)

    def reset(self) -> None:
        """Reset timeline to initial state."""
        self.shot_frame_offsets = []
        self.shot_frame_counts = []
        self.total_sequence_frames = 0
        self.current_global_frame = 0
        self.current_shot_index = 0


@dataclass
class PreloadState:
    """
    State for background preloading of next video.

    Tracks preloaded video information for seamless transitions.
    """
    preloaded_index: int = -1
    preload_ready: bool = False
    preloaded_first_frame: Optional[FrameResult] = None
    preloaded_video_info: Optional[VideoInfo] = None

    def is_ready_for(self, shot_index: int) -> bool:
        """
        Check if preload is ready for specific shot.

        Args:
            shot_index: Shot index to check

        Returns:
            True if preload is complete for this shot
        """
        return self.preload_ready and self.preloaded_index == shot_index

    def mark_ready(
        self,
        index: int,
        first_frame: FrameResult,
        video_info: VideoInfo
    ) -> None:
        """
        Mark preload as complete.

        Args:
            index: Shot index that was preloaded
            first_frame: First frame for instant display
            video_info: Video metadata
        """
        self.preloaded_index = index
        self.preload_ready = True
        self.preloaded_first_frame = first_frame
        self.preloaded_video_info = video_info

    def clear(self) -> None:
        """Clear preload state."""
        self.preloaded_index = -1
        self.preload_ready = False
        self.preloaded_first_frame = None
        self.preloaded_video_info = None

    def consume(self) -> tuple:
        """
        Consume preloaded data and clear state.

        Returns:
            Tuple of (first_frame, video_info)
        """
        frame = self.preloaded_first_frame
        info = self.preloaded_video_info
        self.clear()
        return frame, info


@dataclass
class DisplayState:
    """
    Current display/UI state.

    Tracks the current frame being displayed and UI element states.
    """
    current_frame_image: Optional[QImage] = None
    shot_list_collapsed: bool = False

    def set_current_frame(self, image: QImage) -> None:
        """Store current frame for resize handling."""
        self.current_frame_image = image

    def clear_frame(self) -> None:
        """Clear stored frame."""
        self.current_frame_image = None

    def has_frame(self) -> bool:
        """Check if there's a valid frame stored."""
        return (
            self.current_frame_image is not None and
            not self.current_frame_image.isNull()
        )


@dataclass
class SequenceReviewState:
    """
    Combined state container for SequenceReviewDialog.

    Aggregates all state objects for easy access and management.
    """
    playback: PlaybackState = field(default_factory=PlaybackState)
    timeline: TimelineState = field(default_factory=TimelineState)
    preload: PreloadState = field(default_factory=PreloadState)
    display: DisplayState = field(default_factory=DisplayState)

    def reset_all(self) -> None:
        """Reset all state objects."""
        self.playback.reset()
        self.timeline.reset()
        self.preload.clear()
        self.display.clear_frame()


__all__ = [
    'PlaybackState',
    'TimelineState',
    'PreloadState',
    'DisplayState',
    'SequenceReviewState',
]
