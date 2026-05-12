"""
Worker Base Classes

Standardized QThread worker classes with consistent signals and error handling.
Replaces duplicated worker boilerplate across the codebase.
"""

import logging
from abc import abstractmethod
from typing import Any, Optional, Tuple, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)


class BaseWorker(QThread):
    """
    Base class for background worker threads.

    Provides standardized signals and error handling for async operations.
    Subclasses should implement _execute() method.

    Signals:
        progress: (current: int, total: int, message: str)
        finished: (success: bool, message: str)
        error: (error: Exception)

    Example:
        class ThumbnailWorker(BaseWorker):
            def _execute(self) -> Tuple[bool, str]:
                for i, file in enumerate(self.files):
                    self.emit_progress(i + 1, len(self.files), f"Processing {file}")
                    process_thumbnail(file)
                return True, f"Processed {len(self.files)} files"

        worker = ThumbnailWorker()
        worker.files = file_list
        worker.finished.connect(on_complete)
        worker.start()
    """

    # Signals
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(bool, str)       # success, message
    error = pyqtSignal(object)             # Exception

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cancelled = False

    def run(self) -> None:
        """Thread entry point. Handles execution and error handling."""
        try:
            if self._cancelled:
                self.finished.emit(False, "Cancelled before start")
                return

            success, message = self._execute()
            self.finished.emit(success, message)

        except Exception as e:
            logger.error(f"Worker error in {self.__class__.__name__}: {e}")
            self.error.emit(e)
            self.finished.emit(False, str(e))

    @abstractmethod
    def _execute(self) -> Tuple[bool, str]:
        """
        Execute the worker task.

        Returns:
            Tuple of (success: bool, message: str)

        Raises:
            Exception: Any exception will be caught and emitted via error signal
        """
        raise NotImplementedError("Subclasses must implement _execute()")

    def cancel(self) -> None:
        """Request cancellation of the worker task."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    def emit_progress(self, current: int, total: int, message: str = "") -> None:
        """
        Emit progress update.

        Args:
            current: Current progress value
            total: Total expected value
            message: Optional status message
        """
        if not self._cancelled:
            self.progress.emit(current, total, message)


class CallableWorker(BaseWorker):
    """
    Worker that executes a callable function.

    Useful for quick one-off background tasks without creating a subclass.

    Example:
        def heavy_computation(data):
            result = process(data)
            return True, f"Processed {len(result)} items"

        worker = CallableWorker(heavy_computation, data)
        worker.finished.connect(on_done)
        worker.start()
    """

    def __init__(
        self,
        func: Callable[..., Tuple[bool, str]],
        *args: Any,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        **kwargs: Any
    ):
        """
        Initialize callable worker.

        Args:
            func: Function to execute (must return Tuple[bool, str])
            *args: Positional arguments for func
            progress_callback: Optional callback for progress updates
            **kwargs: Keyword arguments for func
        """
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._progress_callback = progress_callback

    def _execute(self) -> Tuple[bool, str]:
        # Inject progress callback if function accepts it
        if self._progress_callback:
            self._kwargs['progress_callback'] = self._progress_callback

        return self._func(*self._args, **self._kwargs)


class WorkerObject(QObject):
    """
    QObject-based worker for use with moveToThread pattern.

    Use this when you need to keep the worker alive after completion
    or when you need finer control over thread lifecycle.

    Example:
        class DataLoader(WorkerObject):
            data_loaded = pyqtSignal(list)

            def _execute(self) -> Tuple[bool, str]:
                data = load_from_database()
                self.data_loaded.emit(data)
                return True, f"Loaded {len(data)} items"

        thread = QThread()
        worker = DataLoader()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.start()
    """

    # Signals
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cancelled = False

    def run(self) -> None:
        """Execute the worker task."""
        try:
            if self._cancelled:
                self.finished.emit(False, "Cancelled before start")
                return

            success, message = self._execute()
            self.finished.emit(success, message)

        except Exception as e:
            logger.error(f"WorkerObject error in {self.__class__.__name__}: {e}")
            self.error.emit(e)
            self.finished.emit(False, str(e))

    @abstractmethod
    def _execute(self) -> Tuple[bool, str]:
        """Execute the worker task. Subclasses must implement this."""
        raise NotImplementedError

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancelled

    def emit_progress(self, current: int, total: int, message: str = "") -> None:
        """Emit progress update."""
        if not self._cancelled:
            self.progress.emit(current, total, message)


class BatchWorker(BaseWorker):
    """
    Worker for processing items in batches with progress tracking.

    Automatically handles progress updates and cancellation checks
    between batch items.

    Example:
        class ImageProcessor(BatchWorker):
            def process_item(self, item, index: int) -> bool:
                resize_image(item)
                return True  # Continue processing

        worker = ImageProcessor(image_paths, batch_name="Resizing images")
        worker.start()
    """

    def __init__(
        self,
        items: list,
        batch_name: str = "Processing",
        parent: Optional[QObject] = None
    ):
        """
        Initialize batch worker.

        Args:
            items: List of items to process
            batch_name: Name for progress messages
            parent: Optional parent QObject
        """
        super().__init__(parent)
        self._items = items
        self._batch_name = batch_name
        self._processed_count = 0
        self._failed_count = 0

    def _execute(self) -> Tuple[bool, str]:
        total = len(self._items)

        for i, item in enumerate(self._items):
            if self._cancelled:
                return False, f"Cancelled after {i}/{total} items"

            # Emit progress
            self.emit_progress(i + 1, total, f"{self._batch_name} ({i + 1}/{total})")

            # Process item
            try:
                if self.process_item(item, i):
                    self._processed_count += 1
                else:
                    self._failed_count += 1
            except Exception as e:
                logger.warning(f"Failed to process item {i}: {e}")
                self._failed_count += 1

        # Summary message
        if self._failed_count == 0:
            return True, f"{self._batch_name} complete: {self._processed_count} items"
        else:
            return (
                self._failed_count < total,
                f"{self._batch_name}: {self._processed_count} succeeded, {self._failed_count} failed"
            )

    def process_item(self, item: Any, index: int) -> bool:
        """
        Process a single item.

        Subclasses should override this method.

        Args:
            item: Item to process
            index: Item index in the batch

        Returns:
            True if successful, False if failed
        """
        return True


__all__ = [
    'BaseWorker',
    'CallableWorker',
    'WorkerObject',
    'BatchWorker',
]
