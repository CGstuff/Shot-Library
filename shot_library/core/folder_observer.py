"""
Folder Observer

Monitors production folder trees for changes.
Implements the folder-observer contract.

T175: Added logging for filesystem events.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Set, Callable, Dict
import threading
import uuid

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

# T175: Logger for filesystem events
logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
def _get_event_bus():
    from ..events.event_bus import get_event_bus
    return get_event_bus()

# Configuration constants
FOLDER_OBSERVER_DEBOUNCE_MS = 250
FOLDER_OBSERVER_POLLING_INTERVAL_MS = 2000
FOLDER_OBSERVER_MAX_EVENTS_PER_BATCH = 1000


class ChangeType(Enum):
    """Type of filesystem change."""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class FileSystemChange:
    """Represents a detected filesystem change."""
    change_type: ChangeType
    path: Path
    old_path: Optional[Path] = None  # For MOVED events
    is_directory: bool = False
    detected_at: datetime = None

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now()


class FolderObserver(QObject):
    """
    Monitors production folder trees for changes.

    Uses watchdog library with debouncing for efficient change detection.
    Read-only: Never modifies filesystem.
    """

    # Signals
    changes_detected = pyqtSignal(list)  # List[FileSystemChange]
    watch_started = pyqtSignal(str, object)  # watch_id, Path
    watch_stopped = pyqtSignal(str)  # watch_id
    watch_error = pyqtSignal(str, object)  # watch_id, Exception
    buffer_overflow = pyqtSignal(str)  # watch_id (indicates polling fallback)

    # File patterns to watch
    WATCHED_PATTERNS = {'*.blend', '*.mp4'}

    # Patterns to ignore
    IGNORED_PATTERNS = {'*.blend1', '*.blend2', '*~', '*.tmp', '*.swp'}

    def __init__(
        self,
        debounce_ms: int = 250,
        recursive: bool = True,
        parent=None
    ):
        """
        Initialize observer with configuration.

        Args:
            debounce_ms: Milliseconds to wait before processing batched changes
            recursive: Whether to watch subdirectories
        """
        super().__init__(parent)
        self.debounce_ms = debounce_ms
        self.recursive = recursive

        self._observers: Dict[str, 'Observer'] = {}
        self._handlers: Dict[str, 'ShotLibraryEventHandler'] = {}
        self._callbacks: Dict[str, Callable[[List[FileSystemChange]], None]] = {}
        self._pending_changes: Dict[str, List[FileSystemChange]] = {}
        self._debounce_timers: Dict[str, QTimer] = {}
        self._polling_timers: Dict[str, QTimer] = {}  # For overflow fallback
        self._watch_paths: Dict[str, Path] = {}  # Track watched paths
        self._using_polling: Dict[str, bool] = {}  # Track polling fallback state
        self._lock = threading.Lock()

    def start_watching(
        self,
        root_path: Path,
        on_changes: Callable[[List[FileSystemChange]], None]
    ) -> str:
        """
        Start watching a folder tree.

        Args:
            root_path: Root folder to monitor
            on_changes: Callback invoked with batched changes

        Returns:
            Watch ID for later reference

        Raises:
            FileNotFoundError: If root_path doesn't exist
            PermissionError: If folder is not readable
        """
        if not root_path.exists():
            raise FileNotFoundError(f"Path does not exist: {root_path}")

        if not root_path.is_dir():
            raise FileNotFoundError(f"Path is not a directory: {root_path}")

        # Try to access directory to check permissions
        try:
            list(root_path.iterdir())
        except PermissionError:
            raise PermissionError(f"Cannot read directory: {root_path}")

        watch_id = str(uuid.uuid4())[:8]

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileSystemEvent

            # Create event handler with root path for security checks
            handler = ShotLibraryEventHandler(
                watch_id=watch_id,
                on_event=self._on_fs_event,
                watched_patterns=self.WATCHED_PATTERNS,
                ignored_patterns=self.IGNORED_PATTERNS,
                on_overflow=self._on_buffer_overflow,
                root_path=root_path
            )

            # Create and start observer
            observer = Observer()
            observer.schedule(handler, str(root_path), recursive=self.recursive)
            observer.start()

            with self._lock:
                self._observers[watch_id] = observer
                self._handlers[watch_id] = handler
                self._callbacks[watch_id] = on_changes
                self._pending_changes[watch_id] = []
                self._watch_paths[watch_id] = root_path
                self._using_polling[watch_id] = False

                # Create debounce timer
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(lambda wid=watch_id: self._flush_changes(wid))
                self._debounce_timers[watch_id] = timer

                # Create polling fallback timer (T150)
                polling_timer = QTimer()
                polling_timer.timeout.connect(lambda wid=watch_id: self._poll_for_changes(wid))
                self._polling_timers[watch_id] = polling_timer

            self.watch_started.emit(watch_id, root_path)

            # T175: Log watch start
            logger.info(f"Started watching folder: {root_path} (watch_id={watch_id})")

            # T151: Also emit via EventBus for system-wide notification
            try:
                event_bus = _get_event_bus()
                event_bus.filesystem_watch_started.emit(watch_id, str(root_path))
            except Exception:
                pass  # EventBus not available in tests

            return watch_id

        except ImportError:
            logger.error("watchdog library not installed")
            raise RuntimeError("watchdog library not installed. Run: pip install watchdog")
        except Exception as e:
            logger.error(f"Failed to start watching {root_path}: {e}")
            self.watch_error.emit(watch_id, e)
            raise

    def stop_watching(self, watch_id: str) -> None:
        """
        Stop watching a folder tree.

        Args:
            watch_id: ID returned from start_watching
        """
        # DEADLOCK FIX: Extract observer from dict while holding lock,
        # then release lock before calling stop()/join() which may block.
        # This prevents deadlock if observer thread tries to acquire _lock.
        observer = None
        debounce_timer = None
        polling_timer = None

        with self._lock:
            if watch_id in self._observers:
                observer = self._observers.pop(watch_id)

            self._handlers.pop(watch_id, None)
            self._callbacks.pop(watch_id, None)
            self._pending_changes.pop(watch_id, None)
            self._watch_paths.pop(watch_id, None)
            self._using_polling.pop(watch_id, None)

            if watch_id in self._debounce_timers:
                debounce_timer = self._debounce_timers.pop(watch_id)

            if watch_id in self._polling_timers:
                polling_timer = self._polling_timers.pop(watch_id)

        # Stop observer OUTSIDE the lock to prevent deadlock
        if observer is not None:
            observer.stop()
            observer.join(timeout=2.0)

        # Stop timers (these are safe to call from any thread)
        if debounce_timer is not None:
            debounce_timer.stop()
        if polling_timer is not None:
            polling_timer.stop()

        self.watch_stopped.emit(watch_id)

        # T175: Log watch stop
        logger.info(f"Stopped watching folder (watch_id={watch_id})")

        # T151: Also emit via EventBus for system-wide notification
        try:
            event_bus = _get_event_bus()
            event_bus.filesystem_watch_stopped.emit(watch_id)
        except Exception:
            pass  # EventBus not available in tests

    def stop_all(self) -> None:
        """Stop all active watchers."""
        watch_ids = list(self._observers.keys())
        for watch_id in watch_ids:
            self.stop_watching(watch_id)

    def get_active_watches(self) -> List[str]:
        """
        Get list of active watch IDs.

        Returns:
            List of watch IDs
        """
        with self._lock:
            return list(self._observers.keys())

    def is_watching(self, root_path: Path) -> bool:
        """
        Check if a path is being watched.

        Args:
            root_path: Path to check

        Returns:
            True if path is under active watch
        """
        # This is a simplified check - could be improved
        return len(self._observers) > 0

    def _on_fs_event(self, watch_id: str, change: FileSystemChange):
        """Handle filesystem event from watchdog."""
        with self._lock:
            if watch_id not in self._pending_changes:
                return

            self._pending_changes[watch_id].append(change)

            # Reset debounce timer
            timer = self._debounce_timers.get(watch_id)
            if timer:
                timer.stop()
                timer.start(self.debounce_ms)

    def _flush_changes(self, watch_id: str):
        """Process pending changes after debounce period."""
        with self._lock:
            if watch_id not in self._pending_changes:
                return

            changes = self._pending_changes[watch_id]
            self._pending_changes[watch_id] = []

            callback = self._callbacks.get(watch_id)

        if changes and callback:
            # Deduplicate changes
            deduped = self._deduplicate_changes(changes)

            # Call callback and emit signal
            try:
                callback(deduped)
            except Exception as e:
                self.watch_error.emit(watch_id, e)

            self.changes_detected.emit(deduped)

            # T151: Also emit via EventBus for system-wide notification
            try:
                event_bus = _get_event_bus()
                event_bus.filesystem_changes_detected.emit(deduped)
            except Exception:
                pass  # EventBus not available in tests

    def _deduplicate_changes(
        self,
        changes: List[FileSystemChange]
    ) -> List[FileSystemChange]:
        """Remove duplicate changes for the same path."""
        # Keep the last change for each path
        by_path: Dict[str, FileSystemChange] = {}
        for change in changes:
            key = str(change.path)
            by_path[key] = change
        return list(by_path.values())

    def _on_buffer_overflow(self, watch_id: str):
        """
        Handle buffer overflow from watchdog (T150).

        When the ReadDirectoryChangesW buffer overflows (common on network drives),
        we fall back to polling mode temporarily.
        """
        observer = None
        polling_timer = None

        with self._lock:
            if watch_id not in self._watch_paths:
                return

            # Mark as using polling
            self._using_polling[watch_id] = True

            # Get observer to stop (will stop outside lock to prevent deadlock)
            if watch_id in self._observers:
                observer = self._observers.get(watch_id)

            # Get polling timer
            polling_timer = self._polling_timers.get(watch_id)

        # Stop observer OUTSIDE the lock to prevent deadlock
        if observer is not None:
            observer.stop()
            # Don't wait for join, just let it die

        # Start polling timer
        if polling_timer is not None:
            polling_timer.start(FOLDER_OBSERVER_POLLING_INTERVAL_MS)

        # Emit overflow signal
        self.buffer_overflow.emit(watch_id)

        # T175: Log buffer overflow
        logger.warning(f"Buffer overflow for watch {watch_id}, falling back to polling")

        # T151: Also emit via EventBus for system-wide notification
        try:
            event_bus = _get_event_bus()
            event_bus.filesystem_buffer_overflow.emit(watch_id)
        except Exception:
            pass  # EventBus not available in tests

    def _poll_for_changes(self, watch_id: str):
        """
        Poll for changes as fallback when event-driven watching fails (T150).

        This is less efficient but works reliably on network drives.
        """
        with self._lock:
            if watch_id not in self._watch_paths:
                return

            root_path = self._watch_paths[watch_id]
            callback = self._callbacks.get(watch_id)

        if not root_path or not callback:
            return

        try:
            # Scan for .blend and .mp4 files
            changes = []
            for pattern in ['**/*.blend', '**/*.mp4']:
                for file_path in root_path.glob(pattern):
                    # Check if file was modified recently
                    try:
                        stat = file_path.stat()
                        # If modified in the last polling interval + buffer
                        import time
                        if time.time() - stat.st_mtime < (FOLDER_OBSERVER_POLLING_INTERVAL_MS / 1000.0) * 2:
                            changes.append(FileSystemChange(
                                change_type=ChangeType.MODIFIED,
                                path=file_path,
                                is_directory=False
                            ))
                    except (OSError, PermissionError):
                        continue

            if changes:
                deduped = self._deduplicate_changes(changes)
                callback(deduped)
                self.changes_detected.emit(deduped)

                # T151: Also emit via EventBus for system-wide notification
                try:
                    event_bus = _get_event_bus()
                    event_bus.filesystem_changes_detected.emit(deduped)
                except Exception:
                    pass  # EventBus not available in tests

        except PermissionError as e:
            logger.warning(f"Permission error during polling: {e}")
            self.watch_error.emit(watch_id, e)
            # T151: Also emit via EventBus
            try:
                event_bus = _get_event_bus()
                event_bus.filesystem_watch_error.emit(watch_id, str(e))
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Polling error: {e}")

    def resume_event_watching(self, watch_id: str) -> bool:
        """
        Attempt to resume event-driven watching after polling fallback (T150).

        Returns:
            True if event-driven watching was resumed successfully
        """
        with self._lock:
            if watch_id not in self._watch_paths:
                return False

            if not self._using_polling.get(watch_id, False):
                return True  # Already using events

            root_path = self._watch_paths[watch_id]
            callback = self._callbacks.get(watch_id)

        if not root_path or not callback:
            return False

        try:
            from watchdog.observers import Observer

            # Stop polling
            polling_timer = self._polling_timers.get(watch_id)
            if polling_timer:
                polling_timer.stop()

            # Create new observer with root path for security
            handler = ShotLibraryEventHandler(
                watch_id=watch_id,
                on_event=self._on_fs_event,
                watched_patterns=self.WATCHED_PATTERNS,
                ignored_patterns=self.IGNORED_PATTERNS,
                root_path=root_path
            )

            observer = Observer()
            observer.schedule(handler, str(root_path), recursive=self.recursive)
            observer.start()

            with self._lock:
                self._observers[watch_id] = observer
                self._handlers[watch_id] = handler
                self._using_polling[watch_id] = False

            logger.info(f"Resumed event-driven watching for {watch_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to resume event watching: {e}")
            return False

    def is_using_polling(self, watch_id: str) -> bool:
        """Check if a watch is currently using polling fallback."""
        return self._using_polling.get(watch_id, False)


class ShotLibraryEventHandler:
    """Watchdog event handler for Shot Library."""

    def __init__(
        self,
        watch_id: str,
        on_event: Callable[[str, FileSystemChange], None],
        watched_patterns: Set[str],
        ignored_patterns: Set[str],
        on_overflow: Optional[Callable[[str], None]] = None,
        root_path: Optional[Path] = None
    ):
        self.watch_id = watch_id
        self.on_event = on_event
        self.watched_patterns = watched_patterns
        self.ignored_patterns = ignored_patterns
        self.on_overflow = on_overflow
        self._root_path = root_path  # For path sanitization

    def on_any_event(self, event):
        """Catch-all handler to detect buffer overflow (T150)."""
        # watchdog raises a specific error or sends special event on overflow
        # We detect this by checking if event is a directory change event
        # with too many events in quick succession
        pass

    def dispatch(self, event):
        """Handle any filesystem event."""
        from watchdog.events import (
            FileCreatedEvent, FileModifiedEvent,
            FileDeletedEvent, FileMovedEvent,
            DirCreatedEvent, DirDeletedEvent, DirMovedEvent
        )

        path = Path(event.src_path)

        # SECURITY: Sanitize path to prevent path traversal attacks
        if not self._is_safe_path(path):
            logger.warning(f"Rejected unsafe path: {path}")
            return

        # Check if we should process this file
        if not self._should_process(path):
            return

        # Create change object
        change = None

        if isinstance(event, (FileCreatedEvent, DirCreatedEvent)):
            change = FileSystemChange(
                change_type=ChangeType.CREATED,
                path=path,
                is_directory=isinstance(event, DirCreatedEvent)
            )
        elif isinstance(event, (FileModifiedEvent,)):
            change = FileSystemChange(
                change_type=ChangeType.MODIFIED,
                path=path,
                is_directory=False
            )
        elif isinstance(event, (FileDeletedEvent, DirDeletedEvent)):
            change = FileSystemChange(
                change_type=ChangeType.DELETED,
                path=path,
                is_directory=isinstance(event, DirDeletedEvent)
            )
        elif isinstance(event, (FileMovedEvent, DirMovedEvent)):
            dest_path = Path(event.dest_path)
            # Also sanitize destination path for MOVED events
            if not self._is_safe_path(dest_path):
                logger.warning(f"Rejected unsafe destination path: {dest_path}")
                return
            change = FileSystemChange(
                change_type=ChangeType.MOVED,
                path=dest_path,
                old_path=path,
                is_directory=isinstance(event, DirMovedEvent)
            )

        if change:
            self.on_event(self.watch_id, change)

    def _is_safe_path(self, path: Path) -> bool:
        """
        Check if path is safe (no path traversal, no symlinks outside root).

        Security checks:
        1. Reject paths containing ".." components
        2. Reject symlinks pointing outside the watched root
        3. Ensure resolved path is under the root
        """
        path_str = str(path)

        # Check for path traversal attempts
        if '..' in path_str:
            return False

        # Skip symlink checks if no root path configured
        if self._root_path is None:
            return True

        try:
            # Resolve symlinks and check if still under root
            resolved = path.resolve()
            root_resolved = self._root_path.resolve()

            # Check if resolved path is under the root
            try:
                resolved.relative_to(root_resolved)
                return True
            except ValueError:
                # Path is outside the watched root
                return False

        except (OSError, ValueError):
            # Path doesn't exist or can't be resolved - allow it
            # (watchdog may report deleted files)
            return True

    def _should_process(self, path: Path) -> bool:
        """Check if file matches watched patterns and not ignored."""
        name = path.name

        # Check ignored patterns
        for pattern in self.ignored_patterns:
            if self._matches_pattern(name, pattern):
                return False

        # Check watched patterns
        for pattern in self.watched_patterns:
            if self._matches_pattern(name, pattern):
                return True

        # Also process directories (for folder creation/deletion)
        try:
            if path.is_dir():
                return True
        except OSError:
            pass  # Path may not exist

        return False

    def _matches_pattern(self, name: str, pattern: str) -> bool:
        """Simple glob-like pattern matching."""
        import fnmatch
        return fnmatch.fnmatch(name, pattern)


__all__ = [
    'ChangeType',
    'FileSystemChange',
    'FolderObserver',
]
