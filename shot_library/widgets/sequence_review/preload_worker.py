"""
Preload Worker

Background worker for preloading next video during sequence playback.
Enables seamless transitions between shots.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ...services.media_engine import MediaEngine, FrameResult, VideoInfo

logger = logging.getLogger(__name__)


class PreloadWorker(QObject):
    """
    Worker for preloading next video in background.

    Opens video file and reads first frame in a separate thread
    to avoid blocking the main UI thread. Used for seamless
    transitions in sequence review.

    Signals:
        finished: Emitted when preload completes
            - success: True if preload succeeded
            - data: Tuple of (VideoInfo, FrameResult) or None on failure

    Usage:
        thread = QThread()
        worker = PreloadWorker(engine, video_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(handle_result)
        thread.start()
    """

    finished = pyqtSignal(bool, object)  # success, (video_info, first_frame) or None

    def __init__(self, engine: MediaEngine, video_path: Path):
        """
        Initialize preload worker.

        Args:
            engine: MediaEngine instance to use for loading
            video_path: Path to video file to preload
        """
        super().__init__()
        self._engine = engine
        self._video_path = video_path
        self._cancelled = False

    def cancel(self) -> None:
        """Mark worker as cancelled - won't emit result."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if worker was cancelled."""
        return self._cancelled

    def run(self) -> None:
        """Open video and read first frame in background."""
        if self._cancelled:
            return

        try:
            # Open video
            video_info = self._engine.open_video(self._video_path)

            if video_info is None or self._cancelled:
                if not self._cancelled:
                    logger.debug(f"Preload failed to open: {self._video_path}")
                    self.finished.emit(False, None)
                return

            # Pre-read first frame for instant display
            first_frame = self._engine.get_frame(0)

            if self._cancelled:
                return

            if first_frame:
                logger.debug(f"Preload complete: {self._video_path.name}")
                self.finished.emit(True, (video_info, first_frame))
            else:
                logger.debug(f"Preload failed to read first frame: {self._video_path}")
                self.finished.emit(False, None)

        except Exception as e:
            logger.warning(f"Preload failed for {self._video_path}: {e}")
            if not self._cancelled:
                self.finished.emit(False, None)


class PreloadManager:
    """
    Manager for background preloading operations.

    Handles thread lifecycle and cancellation for preload workers.
    """

    def __init__(self):
        self._thread: Optional[QThread] = None
        self._worker: Optional[PreloadWorker] = None

    def start_preload(
        self,
        engine: MediaEngine,
        video_path: Path,
        on_finished: callable
    ) -> None:
        """
        Start preloading a video in background.

        Args:
            engine: MediaEngine to use
            video_path: Path to video file
            on_finished: Callback for completion (bool, data)
        """
        # Cancel any existing preload
        self.cancel()

        # Create worker and thread
        self._thread = QThread()
        self._worker = PreloadWorker(engine, video_path)
        self._worker.moveToThread(self._thread)

        # Connect signals
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(on_finished)
        self._worker.finished.connect(self._thread.quit)

        # Start
        self._thread.start()

    def cancel(self) -> None:
        """Cancel any pending preload operation."""
        if self._worker:
            self._worker.cancel()
            self._worker = None

        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)  # Wait up to 500ms

        self._thread = None

    @property
    def is_active(self) -> bool:
        """Check if preload is currently running."""
        return self._thread is not None and self._thread.isRunning()

    def cleanup(self) -> None:
        """Clean up resources."""
        self.cancel()


__all__ = ['PreloadWorker', 'PreloadManager']
