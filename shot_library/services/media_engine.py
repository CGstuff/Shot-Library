"""
Media Engine

Video decoding, playback, and frame extraction.
Implements the media-engine contract.

T176: Added logging for media engine operations.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap

from ..utils.timecode_utils import frame_to_timecode as _frame_to_timecode

# T176: Logger for media engine operations
logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """Information about a video file."""
    path: Path
    duration_ms: int
    fps: float
    width: int
    height: int
    frame_count: int
    codec: str


@dataclass
class FrameResult:
    """Result of a frame extraction."""
    frame_number: int
    image: QImage
    timecode: str  # HH:MM:SS:FF


class MediaEngine(QObject):
    """
    Video decoding and playback engine.

    Uses opencv-python for frame extraction.
    Read-only: Never modifies video files.

    Implements T168-T169:
    - T168: Pre-buffer 2-3 frames during video playback
    - T169: Scale down hover previews to 300px for performance
    """

    # Signals
    playback_started = pyqtSignal(object)  # Path
    playback_stopped = pyqtSignal()
    playback_paused = pyqtSignal()
    playback_resumed = pyqtSignal()
    frame_ready = pyqtSignal(object)  # FrameResult
    playback_error = pyqtSignal(object, object)  # Path, Exception
    playback_complete = pyqtSignal()  # End of video (non-looping)

    # T169: Default preview size for hover previews (300px width, 16:9)
    DEFAULT_PREVIEW_SIZE = (300, 169)

    def __init__(self, target_fps: int = 30, parent=None):
        """
        Initialize media engine.

        Args:
            target_fps: Maximum playback FPS (capped for performance)
        """
        super().__init__(parent)
        self._target_fps = min(target_fps, 30)  # Cap at 30 FPS
        self._cap = None
        self._video_info: Optional[VideoInfo] = None
        self._is_playing = False
        self._current_frame = 0
        self._playback_speed = 1.0
        self._loop = True

        # T168: Frame buffer for pre-buffering 2-3 frames
        self._frame_buffer: list[FrameResult] = []
        self._buffer_size = 3  # Pre-buffer 3 frames
        self._preview_scale = True  # T169: Scale down for hover preview

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._on_frame_callback: Optional[Callable[[FrameResult], None]] = None

    def open_video(self, video_path: Path) -> Optional[VideoInfo]:
        """
        Open a video file and get its properties.

        Args:
            video_path: Path to MP4 file

        Returns:
            VideoInfo or None if file cannot be opened
        """
        self.close_video()

        try:
            import cv2

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return None

            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))

            # Calculate duration
            duration_ms = int((frame_count / fps) * 1000) if fps > 0 else 0

            # Decode fourcc to codec name
            codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])

            self._cap = cap
            self._video_info = VideoInfo(
                path=video_path,
                duration_ms=duration_ms,
                fps=fps,
                width=width,
                height=height,
                frame_count=frame_count,
                codec=codec
            )
            self._current_frame = 0
            self._frame_buffer.clear()  # Clear any stale buffered frames

            # T176: Log successful video open
            logger.debug(f"Opened video: {video_path} ({width}x{height}, {fps:.2f}fps, {frame_count} frames)")

            return self._video_info

        except ImportError:
            logger.error("opencv-python not installed for video playback")
            return None
        except Exception as e:
            logger.error(f"Failed to open video {video_path}: {e}")
            return None

    def close_video(self) -> None:
        """Release current video resources."""
        self.stop_playback()

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        self._video_info = None
        self._current_frame = 0
        self._frame_buffer.clear()  # Ensure buffer is cleared

    def get_frame(self, frame_number: int) -> Optional[FrameResult]:
        """
        Extract a specific frame.

        Args:
            frame_number: 0-indexed frame number

        Returns:
            FrameResult or None if frame cannot be read
        """
        if self._cap is None or self._video_info is None:
            return None

        import cv2

        # Clamp frame number
        frame_number = max(0, min(frame_number, self._video_info.frame_count - 1))

        # Seek to frame
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        ret, frame = self._cap.read()
        if not ret:
            return None

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Create QImage
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qimage = QImage(
            frame_rgb.data, w, h, bytes_per_line,
            QImage.Format.Format_RGB888
        ).copy()  # Copy to own the data

        # Generate timecode
        timecode = frame_to_timecode(frame_number, self._video_info.fps)

        self._current_frame = frame_number

        return FrameResult(
            frame_number=frame_number,
            image=qimage,
            timecode=timecode
        )

    def get_frame_at_time(self, time_ms: int) -> Optional[FrameResult]:
        """
        Extract frame at specific timestamp.

        Args:
            time_ms: Timestamp in milliseconds

        Returns:
            FrameResult or None if frame cannot be read
        """
        if self._video_info is None:
            return None

        # Convert time to frame number
        frame_number = int((time_ms / 1000.0) * self._video_info.fps)
        return self.get_frame(frame_number)

    def extract_thumbnail(
        self,
        video_path: Path,
        frame_number: int = 0,
        size: tuple[int, int] = (300, 169)  # 16:9
    ) -> Optional[QPixmap]:
        """
        Extract and resize a frame as thumbnail.

        Args:
            video_path: Path to video file
            frame_number: Frame to extract (default: first frame)
            size: Target size (width, height)

        Returns:
            Scaled QPixmap or None if extraction fails
        """
        # Temporarily open video if needed
        temp_open = self._cap is None or self._video_info is None or \
                   self._video_info.path != video_path

        if temp_open:
            self.open_video(video_path)

        result = self.get_frame(frame_number)

        if temp_open:
            self.close_video()

        if result is None:
            return None

        # Scale to target size
        pixmap = QPixmap.fromImage(result.image)
        return pixmap.scaled(
            size[0], size[1],
            aspectRatioMode=True
        )

    def start_playback(
        self,
        on_frame: Callable[[FrameResult], None],
        loop: bool = True
    ) -> None:
        """
        Start continuous playback.

        Args:
            on_frame: Callback for each frame
            loop: Whether to loop at end
        """
        if self._cap is None or self._video_info is None:
            return

        self._on_frame_callback = on_frame
        self._loop = loop
        self._is_playing = True

        # Calculate timer interval
        effective_fps = min(self._target_fps, self._video_info.fps)
        interval_ms = int(1000 / (effective_fps * self._playback_speed))

        self._timer.start(max(1, interval_ms))
        self.playback_started.emit(self._video_info.path)

        # T176: Log playback start
        logger.debug(f"Started playback: {self._video_info.path} (loop={loop})")

    def stop_playback(self) -> None:
        """Stop current playback."""
        self._timer.stop()
        self._is_playing = False
        self._on_frame_callback = None
        self._frame_buffer.clear()  # Clear stale buffered frames
        self.playback_stopped.emit()
        logger.debug("Stopped playback")

    def pause_playback(self) -> None:
        """Pause current playback."""
        self._timer.stop()
        self._is_playing = False
        self.playback_paused.emit()

    def resume_playback(self) -> None:
        """Resume paused playback."""
        if self._on_frame_callback is None or self._cap is None:
            return

        self._is_playing = True

        effective_fps = min(self._target_fps, self._video_info.fps) if self._video_info else 30
        interval_ms = int(1000 / (effective_fps * self._playback_speed))

        self._timer.start(max(1, interval_ms))
        self.playback_resumed.emit()

    def seek_to_frame(self, frame_number: int) -> Optional[FrameResult]:
        """
        Seek to specific frame during playback.

        Uses timestamp-based seeking for accuracy.

        Args:
            frame_number: Target frame

        Returns:
            Frame at target position or None if seek fails
        """
        return self.get_frame(frame_number)

    def set_playback_speed(self, speed: float) -> None:
        """
        Set playback speed multiplier.

        Args:
            speed: Speed factor (0.25 to 4.0)
        """
        self._playback_speed = max(0.25, min(4.0, speed))

        # Update timer if playing
        if self._is_playing and self._video_info:
            effective_fps = min(self._target_fps, self._video_info.fps)
            interval_ms = int(1000 / (effective_fps * self._playback_speed))
            self._timer.setInterval(max(1, interval_ms))

    @property
    def is_playing(self) -> bool:
        """Whether playback is active."""
        return self._is_playing

    @property
    def current_frame(self) -> int:
        """Current frame number."""
        return self._current_frame

    @property
    def video_info(self) -> Optional[VideoInfo]:
        """Current video info or None if no video open."""
        return self._video_info

    def _on_timer_tick(self):
        """
        Handle timer tick for playback.

        T168: Uses frame buffer for smoother playback:
        - Pre-buffers 2-3 frames ahead
        - Returns buffered frame if available
        - Fills buffer in background
        """
        if not self._is_playing or self._cap is None or self._video_info is None:
            return

        # T168: Try to get frame from buffer first
        result = None
        if self._frame_buffer:
            result = self._frame_buffer.pop(0)
        else:
            # Buffer empty, read directly
            result = self._get_scaled_frame(self._current_frame)

        if result:
            # Emit frame
            if self._on_frame_callback:
                self._on_frame_callback(result)
            self.frame_ready.emit(result)

            # Advance frame
            self._current_frame += 1

            # T168: Pre-buffer next frames for smoother playback
            self._fill_buffer()

            # Check for end of video
            if self._current_frame >= self._video_info.frame_count:
                if self._loop:
                    self._current_frame = 0
                    self._frame_buffer.clear()  # Clear buffer on loop
                else:
                    self.stop_playback()
                    self.playback_complete.emit()

    def _fill_buffer(self):
        """
        T168: Fill frame buffer with pre-buffered frames.

        Pre-buffers up to self._buffer_size frames ahead for smoother playback.
        """
        if self._cap is None or self._video_info is None:
            return

        # Calculate how many frames to buffer
        frames_to_buffer = self._buffer_size - len(self._frame_buffer)
        next_frame = self._current_frame + len(self._frame_buffer)

        for i in range(frames_to_buffer):
            frame_num = next_frame + i
            if frame_num >= self._video_info.frame_count:
                break

            frame_result = self._get_scaled_frame(frame_num)
            if frame_result:
                self._frame_buffer.append(frame_result)

    def _get_scaled_frame(self, frame_number: int) -> Optional[FrameResult]:
        """
        T169: Get frame scaled down for hover preview performance.

        Args:
            frame_number: Frame to extract

        Returns:
            FrameResult with scaled image for preview
        """
        if self._cap is None or self._video_info is None:
            return None

        import cv2

        # Clamp frame number
        frame_number = max(0, min(frame_number, self._video_info.frame_count - 1))

        # Seek to frame
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        ret, frame = self._cap.read()
        if not ret:
            return None

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # T169: Scale down for hover preview performance (300px width)
        if self._preview_scale:
            target_w, target_h = self.DEFAULT_PREVIEW_SIZE
            frame_rgb = cv2.resize(
                frame_rgb,
                (target_w, target_h),
                interpolation=cv2.INTER_AREA  # Best for downscaling
            )

        # Create QImage
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qimage = QImage(
            frame_rgb.data, w, h, bytes_per_line,
            QImage.Format.Format_RGB888
        ).copy()  # Copy to own the data

        # Generate timecode
        timecode = frame_to_timecode(frame_number, self._video_info.fps)

        return FrameResult(
            frame_number=frame_number,
            image=qimage,
            timecode=timecode
        )

    def set_preview_scale(self, enabled: bool):
        """
        T169: Enable/disable preview scaling for performance.

        Args:
            enabled: If True, scale frames to 300px for hover preview
        """
        self._preview_scale = enabled


def frame_to_timecode(frame: int, fps: float) -> str:
    """
    Generate SMPTE timecode from frame number.

    This is a compatibility wrapper around the centralized
    timecode utility in shot_library.utils.timecode_utils.

    Args:
        frame: Frame number (0-indexed)
        fps: Frames per second

    Returns:
        Timecode string (HH:MM:SS:FF)
    """
    return _frame_to_timecode(frame, fps)


__all__ = [
    'VideoInfo',
    'FrameResult',
    'MediaEngine',
    'frame_to_timecode',
]
