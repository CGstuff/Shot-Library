"""
Decorators

Reusable decorators for error handling, logging, retries, and database transactions.
Replaces 273+ inconsistent try/except patterns across 38+ files.
"""

import functools
import logging
import time
from typing import TypeVar, Callable, Any, Optional, Type, Union, Tuple

logger = logging.getLogger(__name__)

# Type variable for generic return type
T = TypeVar('T')


def handle_exceptions(
    log_level: str = 'error',
    default_return: Any = None,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    message: Optional[str] = None,
    reraise: bool = False
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to handle exceptions with consistent logging.

    Args:
        log_level: Logging level ('debug', 'info', 'warning', 'error', 'critical')
        default_return: Value to return on exception (default: None)
        exceptions: Tuple of exception types to catch
        message: Custom log message (default: auto-generated)
        reraise: If True, re-raise the exception after logging

    Returns:
        Decorated function

    Example:
        @handle_exceptions(log_level='warning', default_return=[])
        def get_items():
            return fetch_from_database()

        @handle_exceptions(exceptions=(FileNotFoundError, PermissionError))
        def read_config():
            return load_file()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                log_func = getattr(logger, log_level, logger.error)
                msg = message or f"{func.__name__} failed: {e}"
                log_func(msg)

                if reraise:
                    raise

                return default_return

        return wrapper
    return decorator


def log_execution(
    level: str = 'debug',
    log_args: bool = False,
    log_result: bool = False
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to log function execution.

    Args:
        level: Logging level
        log_args: If True, include arguments in log
        log_result: If True, include return value in log

    Example:
        @log_execution(level='info', log_args=True)
        def process_shot(shot_id: str):
            return do_processing(shot_id)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            log_func = getattr(logger, level, logger.debug)

            # Build entry log message
            if log_args:
                args_str = ', '.join(
                    [repr(a) for a in args] +
                    [f"{k}={v!r}" for k, v in kwargs.items()]
                )
                log_func(f"Entering {func.__name__}({args_str})")
            else:
                log_func(f"Entering {func.__name__}")

            result = func(*args, **kwargs)

            # Build exit log message
            if log_result:
                log_func(f"Exiting {func.__name__}, returned: {result!r}")
            else:
                log_func(f"Exiting {func.__name__}")

            return result

        return wrapper
    return decorator


def retry(
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    backoff_multiplier: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to retry failed operations with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts
        backoff_seconds: Initial delay between retries
        backoff_multiplier: Multiplier for delay after each retry
        exceptions: Exception types that trigger retry
        on_retry: Optional callback(exception, attempt_number) called before each retry

    Example:
        @retry(max_attempts=3, backoff_seconds=0.5)
        def fetch_from_network():
            return requests.get(url)

        @retry(max_attempts=5, exceptions=(ConnectionError, TimeoutError))
        def connect_to_service():
            return establish_connection()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = backoff_seconds
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(e, attempt)
                        logger.debug(
                            f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_multiplier
                    else:
                        logger.warning(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )

            # Re-raise last exception
            raise last_exception

        return wrapper
    return decorator


def atomic_db_transaction(
    connection_getter: Callable[[], Any],
    on_error: Optional[Callable[[Exception], None]] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for atomic database transactions.

    Commits on success, rolls back on exception.

    Args:
        connection_getter: Callable that returns database connection
        on_error: Optional callback for error handling

    Example:
        def get_db():
            return DatabaseService.get_connection()

        @atomic_db_transaction(get_db)
        def update_shot_status(shot_id, status):
            cursor = get_db().cursor()
            cursor.execute("UPDATE shots SET status = ? WHERE id = ?", (status, shot_id))
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            conn = connection_getter()
            try:
                result = func(*args, **kwargs)
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Transaction rolled back in {func.__name__}: {e}")
                if on_error:
                    on_error(e)
                raise

        return wrapper
    return decorator


def deprecated(
    message: str = "",
    replacement: Optional[str] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Mark a function as deprecated.

    Args:
        message: Additional deprecation message
        replacement: Name of replacement function

    Example:
        @deprecated(replacement='new_function')
        def old_function():
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            warning_msg = f"{func.__name__} is deprecated."
            if replacement:
                warning_msg += f" Use {replacement} instead."
            if message:
                warning_msg += f" {message}"

            logger.warning(warning_msg)
            return func(*args, **kwargs)

        return wrapper
    return decorator


def ensure_main_thread(
    fallback: Optional[Callable[..., T]] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Ensure function runs on Qt main thread.

    Args:
        fallback: Optional fallback function if not on main thread

    Example:
        @ensure_main_thread()
        def update_ui():
            self.label.setText("Updated")
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                from PyQt6.QtCore import QThread
                from PyQt6.QtWidgets import QApplication

                app = QApplication.instance()
                if app and QThread.currentThread() != app.thread():
                    if fallback:
                        return fallback(*args, **kwargs)
                    logger.warning(
                        f"{func.__name__} called from non-main thread. "
                        "This may cause UI issues."
                    )
            except ImportError:
                pass  # Qt not available

            return func(*args, **kwargs)

        return wrapper
    return decorator


def cache_result(
    ttl_seconds: Optional[float] = None,
    maxsize: int = 128
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Cache function results with optional TTL.

    Args:
        ttl_seconds: Time-to-live in seconds (None = infinite)
        maxsize: Maximum cache size

    Example:
        @cache_result(ttl_seconds=60)
        def get_expensive_data(key):
            return compute_data(key)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache: dict = {}
        timestamps: dict = {}

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Create hashable key
            key = (args, tuple(sorted(kwargs.items())))

            now = time.time()

            # Check cache
            if key in cache:
                if ttl_seconds is None or (now - timestamps[key]) < ttl_seconds:
                    return cache[key]

            # Compute result
            result = func(*args, **kwargs)

            # Manage cache size
            if len(cache) >= maxsize:
                # Remove oldest entry
                oldest_key = min(timestamps, key=timestamps.get)
                del cache[oldest_key]
                del timestamps[oldest_key]

            # Store result
            cache[key] = result
            timestamps[key] = now

            return result

        # Add cache management methods
        wrapper.cache_clear = lambda: (cache.clear(), timestamps.clear())
        wrapper.cache_info = lambda: {'size': len(cache), 'maxsize': maxsize}

        return wrapper
    return decorator


__all__ = [
    'handle_exceptions',
    'log_execution',
    'retry',
    'atomic_db_transaction',
    'deprecated',
    'ensure_main_thread',
    'cache_result',
]
