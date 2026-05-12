"""
Timecode Utilities

Centralized frame/timecode conversion functions to replace 3 different implementations:
- shot_library/services/media_engine.py (line 487)
- shot_library/widgets/sequence_review_dialog.py (line 1100)
- shot_library/services/review_service.py (line 443)

All timecode formats follow SMPTE standard: HH:MM:SS:FF
"""

from typing import Optional
import re


def frame_to_timecode(frame: int, fps: float, drop_frame: bool = False) -> str:
    """
    Convert frame number to SMPTE timecode (HH:MM:SS:FF).

    Args:
        frame: Frame number (0-indexed)
        fps: Frames per second (must be > 0)
        drop_frame: If True, use drop-frame timecode for 29.97/59.94 fps
                    (Not yet implemented, reserved for future use)

    Returns:
        Timecode string in format HH:MM:SS:FF

    Example:
        >>> frame_to_timecode(0, 24.0)
        '00:00:00:00'
        >>> frame_to_timecode(24, 24.0)
        '00:00:01:00'
        >>> frame_to_timecode(1440, 24.0)  # 1 minute at 24fps
        '00:01:00:00'
    """
    if fps <= 0:
        return "00:00:00:00"

    # Use integer fps for frame calculation to avoid floating point drift
    fps_int = int(round(fps))
    if fps_int <= 0:
        fps_int = 24

    # Calculate time components
    total_seconds = frame / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    # Frame within the current second
    frames_in_second = frame % fps_int

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames_in_second:02d}"


def timecode_to_frame(timecode: str, fps: float) -> int:
    """
    Convert SMPTE timecode to frame number.

    Args:
        timecode: Timecode string in format HH:MM:SS:FF
        fps: Frames per second

    Returns:
        Frame number (0-indexed)

    Raises:
        ValueError: If timecode format is invalid

    Example:
        >>> timecode_to_frame('00:00:01:00', 24.0)
        24
        >>> timecode_to_frame('00:01:00:00', 24.0)
        1440
    """
    if fps <= 0:
        raise ValueError("FPS must be greater than 0")

    # Parse timecode (supports both : and ; separators)
    pattern = r'^(\d{1,2})[:;](\d{2})[:;](\d{2})[:;](\d{2})$'
    match = re.match(pattern, timecode.strip())

    if not match:
        raise ValueError(f"Invalid timecode format: {timecode}. Expected HH:MM:SS:FF")

    hours, minutes, seconds, frames = map(int, match.groups())

    # Validate ranges
    fps_int = int(round(fps))
    if not (0 <= hours <= 23):
        raise ValueError(f"Hours must be 0-23, got {hours}")
    if not (0 <= minutes <= 59):
        raise ValueError(f"Minutes must be 0-59, got {minutes}")
    if not (0 <= seconds <= 59):
        raise ValueError(f"Seconds must be 0-59, got {seconds}")
    if not (0 <= frames < fps_int):
        raise ValueError(f"Frames must be 0-{fps_int - 1} at {fps}fps, got {frames}")

    # Calculate total frames
    total_seconds = hours * 3600 + minutes * 60 + seconds
    total_frames = int(total_seconds * fps) + frames

    return total_frames


def format_duration(frames: int, fps: float, short: bool = False) -> str:
    """
    Format a duration in frames as a human-readable string.

    Args:
        frames: Number of frames
        fps: Frames per second
        short: If True, use compact format (1:30 instead of 00:01:30)

    Returns:
        Duration string

    Example:
        >>> format_duration(1440, 24.0)
        '00:01:00'
        >>> format_duration(1440, 24.0, short=True)
        '1:00'
        >>> format_duration(36, 24.0, short=True)
        '0:01'
    """
    if fps <= 0:
        return "0:00" if short else "00:00:00"

    total_seconds = frames / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)

    if short:
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
    else:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_frame_range(start_frame: int, end_frame: int, fps: Optional[float] = None) -> str:
    """
    Format a frame range as a string.

    Args:
        start_frame: Starting frame number
        end_frame: Ending frame number
        fps: If provided, include timecode in output

    Returns:
        Frame range string

    Example:
        >>> format_frame_range(0, 100)
        '0-100 (101 frames)'
        >>> format_frame_range(0, 47, 24.0)
        '0-47 (48 frames, 00:00:02)'
    """
    frame_count = end_frame - start_frame + 1

    if fps and fps > 0:
        duration = format_duration(frame_count, fps, short=True)
        return f"{start_frame}-{end_frame} ({frame_count} frames, {duration})"
    else:
        return f"{start_frame}-{end_frame} ({frame_count} frames)"


def ms_to_timecode(milliseconds: int, fps: float) -> str:
    """
    Convert milliseconds to SMPTE timecode.

    Args:
        milliseconds: Time in milliseconds
        fps: Frames per second

    Returns:
        Timecode string in format HH:MM:SS:FF
    """
    if fps <= 0:
        return "00:00:00:00"

    frame = int((milliseconds / 1000.0) * fps)
    return frame_to_timecode(frame, fps)


def timecode_to_ms(timecode: str, fps: float) -> int:
    """
    Convert SMPTE timecode to milliseconds.

    Args:
        timecode: Timecode string in format HH:MM:SS:FF
        fps: Frames per second

    Returns:
        Time in milliseconds
    """
    frame = timecode_to_frame(timecode, fps)
    return int((frame / fps) * 1000)


__all__ = [
    'frame_to_timecode',
    'timecode_to_frame',
    'format_duration',
    'format_frame_range',
    'ms_to_timecode',
    'timecode_to_ms',
]
