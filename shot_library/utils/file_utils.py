"""
File Utilities - Safe file and folder operations

Provides centralized functions for:
- Transactional folder operations
- Safe file copying/moving
- Atomic file writes with backup
- File locking for concurrent access
- Rollback support
"""

import logging
import os
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# File locking for concurrent access
_file_locks: dict = {}
_file_locks_lock = threading.Lock()


@contextmanager
def transactional_move(src: Path, dst: Path,
                       cleanup_on_error: bool = True) -> Generator[None, None, None]:
    """
    Context manager for transactional folder move operations.

    If an exception occurs within the context, the destination folder
    is cleaned up (if it was created) to maintain consistency.

    Args:
        src: Source path
        dst: Destination path
        cleanup_on_error: If True, remove dst on error

    Yields:
        None

    Examples:
        >>> with transactional_move(src_folder, dst_folder):
        ...     # Do operations that might fail
        ...     shutil.move(src_folder, dst_folder)
        ...     update_database(dst_folder)

    Raises:
        Re-raises any exception after cleanup
    """
    dst_existed_before = dst.exists()

    try:
        yield
    except Exception:
        if cleanup_on_error and dst.exists() and not dst_existed_before:
            try:
                shutil.rmtree(dst)
                logger.debug(f"Cleaned up {dst} after error")
            except Exception as cleanup_error:
                logger.warning(f"Could not clean up {dst}: {cleanup_error}")
        raise


@contextmanager
def atomic_write(path: Path, backup: bool = True) -> Generator[Path, None, None]:
    """
    Context manager for atomic file writes with backup.

    Writes to a temporary file first, then renames to target.
    If an error occurs, the temporary file is cleaned up and
    the original file is preserved.

    On Windows network drives, rename may not be atomic, so we:
    1. Write to temp file in same directory
    2. Optionally backup original (if exists)
    3. Delete original
    4. Rename temp to target
    5. On error, restore backup

    Args:
        path: Target file path
        backup: If True, create backup of existing file before replacing

    Yields:
        Path to temporary file to write to

    Examples:
        >>> with atomic_write(config_path) as tmp_path:
        ...     with open(tmp_path, 'w') as f:
        ...         json.dump(data, f)
    """
    path = Path(path)
    # Use temp file in same directory to ensure same filesystem
    tmp_path = path.with_suffix(path.suffix + '.tmp.' + str(os.getpid()))
    backup_path = path.with_suffix(path.suffix + '.bak') if backup else None
    original_existed = path.exists()

    try:
        yield tmp_path

        if not tmp_path.exists():
            return  # Nothing was written

        # Create backup of original if requested
        if backup and original_existed:
            try:
                shutil.copy2(path, backup_path)
            except Exception as e:
                logger.warning(f"Could not create backup of {path}: {e}")

        # Replace original with temp
        # On Windows, we need to delete first, then rename
        if sys.platform == 'win32' and path.exists():
            try:
                path.unlink()
            except PermissionError:
                # File is locked - wait a bit and retry
                import time
                time.sleep(0.1)
                path.unlink()

        tmp_path.replace(path)

        # Remove backup on success
        if backup_path and backup_path.exists():
            try:
                backup_path.unlink()
            except Exception:
                pass  # Non-critical

    except Exception:
        # Clean up temp file on error
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

        # Restore backup if original was corrupted
        if backup and backup_path and backup_path.exists() and not path.exists():
            try:
                shutil.move(str(backup_path), str(path))
                logger.info(f"Restored {path} from backup after write failure")
            except Exception as e:
                logger.error(f"Could not restore backup for {path}: {e}")

        raise


@contextmanager
def file_lock(path: Path, timeout: float = 5.0):
    """
    Context manager for file-level locking using threading locks.

    Provides process-level locking for concurrent access to files.
    This uses in-memory locks, so it only works within the same process.
    For cross-process locking, use OS-level file locks.

    Args:
        path: Path to the file to lock
        timeout: Seconds to wait for lock (0 = non-blocking)

    Raises:
        TimeoutError: If lock cannot be acquired within timeout

    Examples:
        >>> with file_lock(json_path):
        ...     data = load_json(json_path)
        ...     data['count'] += 1
        ...     save_json(json_path, data)
    """
    key = str(path.resolve())

    # Get or create lock for this path
    with _file_locks_lock:
        if key not in _file_locks:
            _file_locks[key] = threading.RLock()
        lock = _file_locks[key]

    # Acquire with timeout
    acquired = lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(f"Could not acquire lock for {path} within {timeout}s")

    try:
        yield
    finally:
        lock.release()


def atomic_json_write(path: Path, data: dict, indent: int = 2) -> bool:
    """
    Write JSON data atomically with proper error handling.

    Args:
        path: Path to JSON file
        data: Data to serialize
        indent: JSON indentation level

    Returns:
        True if successful
    """
    import json

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with file_lock(path):
            with atomic_write(path) as tmp_path:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=indent)
        return True

    except Exception as e:
        logger.error(f"Failed to write JSON to {path}: {e}")
        return False


def atomic_json_read(path: Path) -> Optional[dict]:
    """
    Read JSON data with file locking for consistency.

    Args:
        path: Path to JSON file

    Returns:
        Parsed JSON data, or None if file doesn't exist or is invalid
    """
    import json

    if not path.exists():
        return None

    try:
        with file_lock(path, timeout=2.0):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to read JSON from {path}: {e}")
        return None


def safe_remove_tree(path: Path, ignore_errors: bool = True) -> bool:
    """
    Safely remove a directory tree.

    Args:
        path: Path to directory to remove
        ignore_errors: If True, log errors but don't raise

    Returns:
        True if removal succeeded or path didn't exist
    """
    if not path.exists():
        return True

    try:
        shutil.rmtree(path)
        return True
    except PermissionError as e:
        if ignore_errors:
            logger.warning(f"Permission denied removing {path}: {e}")
            return False
        raise
    except OSError as e:
        if ignore_errors:
            logger.warning(f"Could not remove {path}: {e}")
            return False
        raise


def ensure_parent_exists(path: Path) -> bool:
    """
    Ensure the parent directory of a path exists.

    Args:
        path: File or directory path

    Returns:
        True if parent exists or was created
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Could not create parent directory for {path}: {e}")
        return False


def get_unique_path(path: Path) -> Path:
    """
    Get a unique path by appending a number if path exists.

    Args:
        path: Desired path

    Returns:
        Unique path (original if doesn't exist, or with _2, _3, etc.)

    Examples:
        >>> get_unique_path(Path("folder"))
        Path('folder')  # if doesn't exist
        >>> get_unique_path(Path("folder"))
        Path('folder_2')  # if folder exists
    """
    if not path.exists():
        return path

    counter = 2
    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1

        # Safety limit
        if counter > 1000:
            raise ValueError(f"Could not find unique path for {path}")


__all__ = [
    'transactional_move',
    'atomic_write',
    'file_lock',
    'atomic_json_write',
    'atomic_json_read',
    'safe_remove_tree',
    'ensure_parent_exists',
    'get_unique_path',
]
