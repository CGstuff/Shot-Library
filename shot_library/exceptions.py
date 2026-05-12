"""
Shot Library Exceptions

Custom exception hierarchy for standardized error handling.
Use these exceptions instead of generic Exception for better error context.

Hierarchy:
    ShotLibraryError (base)
    ├── DatabaseError
    │   ├── ConnectionError
    │   └── QueryError
    ├── VideoError
    │   ├── VideoNotFoundError
    │   └── VideoDecodingError
    ├── ExportError
    │   ├── FFmpegNotFoundError
    │   └── ExportFailedError
    ├── SchemaError
    │   ├── SchemaNotFoundError
    │   └── SchemaParseError
    └── ConfigError
"""


class ShotLibraryError(Exception):
    """
    Base exception for all Shot Library errors.

    All custom exceptions inherit from this, allowing:
        try:
            ...
        except ShotLibraryError as e:
            handle_any_shot_library_error(e)
    """

    def __init__(self, message: str = "", details: str = ""):
        self.message = message
        self.details = details
        super().__init__(message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}\n{self.details}"
        return self.message


# ============ Database Errors ============

class DatabaseError(ShotLibraryError):
    """Base class for database-related errors."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Failed to connect to database."""

    def __init__(self, db_path: str = "", message: str = ""):
        self.db_path = db_path
        super().__init__(
            message or f"Failed to connect to database: {db_path}",
            f"Path: {db_path}"
        )


class QueryError(DatabaseError):
    """Database query execution failed."""

    def __init__(self, query: str = "", message: str = "", original_error: str = ""):
        self.query = query
        self.original_error = original_error
        super().__init__(
            message or "Database query failed",
            f"Query: {query[:100]}...\nError: {original_error}" if len(query) > 100
            else f"Query: {query}\nError: {original_error}"
        )


# ============ Video Errors ============

class VideoError(ShotLibraryError):
    """Base class for video-related errors."""
    pass


class VideoNotFoundError(VideoError):
    """Video file not found or inaccessible."""

    def __init__(self, path: str = "", message: str = ""):
        self.path = path
        super().__init__(
            message or f"Video file not found: {path}",
            f"Path: {path}"
        )


class VideoDecodingError(VideoError):
    """Failed to decode/read video file."""

    def __init__(self, path: str = "", frame: int = -1, message: str = ""):
        self.path = path
        self.frame = frame
        details = f"Path: {path}"
        if frame >= 0:
            details += f"\nFrame: {frame}"
        super().__init__(
            message or f"Failed to decode video: {path}",
            details
        )


# ============ Export Errors ============

class ExportError(ShotLibraryError):
    """Base class for export-related errors."""
    pass


class FFmpegNotFoundError(ExportError):
    """FFmpeg executable not found in PATH."""

    def __init__(self):
        super().__init__(
            "FFmpeg not found",
            "Please install FFmpeg and add it to your system PATH.\n"
            "Download from: https://ffmpeg.org/download.html"
        )


class ExportFailedError(ExportError):
    """Export operation failed."""

    def __init__(self, output_path: str = "", reason: str = ""):
        self.output_path = output_path
        self.reason = reason
        super().__init__(
            f"Export failed: {reason}" if reason else "Export failed",
            f"Output: {output_path}" if output_path else ""
        )


# ============ Schema Errors ============

class SchemaError(ShotLibraryError):
    """Base class for schema-related errors."""
    pass


class SchemaNotFoundError(SchemaError):
    """Schema configuration file not found."""

    def __init__(self, schema_name: str = "", search_path: str = ""):
        self.schema_name = schema_name
        self.search_path = search_path
        super().__init__(
            f"Schema not found: {schema_name}" if schema_name else "Schema not found",
            f"Searched in: {search_path}" if search_path else ""
        )


class SchemaParseError(SchemaError):
    """Failed to parse schema configuration."""

    def __init__(self, schema_path: str = "", reason: str = ""):
        self.schema_path = schema_path
        self.reason = reason
        super().__init__(
            f"Failed to parse schema: {reason}" if reason else "Failed to parse schema",
            f"File: {schema_path}" if schema_path else ""
        )


# ============ Config Errors ============

class ConfigError(ShotLibraryError):
    """Configuration-related errors."""

    def __init__(self, key: str = "", message: str = ""):
        self.key = key
        super().__init__(
            message or f"Configuration error for: {key}",
            f"Key: {key}" if key else ""
        )


# ============ Operation Errors ============

class OperationCancelledError(ShotLibraryError):
    """Operation was cancelled by user."""

    def __init__(self, operation: str = ""):
        self.operation = operation
        super().__init__(
            f"Operation cancelled: {operation}" if operation else "Operation cancelled"
        )


class PermissionDeniedError(ShotLibraryError):
    """Operation denied due to permissions."""

    def __init__(self, operation: str = "", reason: str = ""):
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"Permission denied: {operation}" if operation else "Permission denied",
            reason
        )


__all__ = [
    # Base
    'ShotLibraryError',
    # Database
    'DatabaseError',
    'DatabaseConnectionError',
    'QueryError',
    # Video
    'VideoError',
    'VideoNotFoundError',
    'VideoDecodingError',
    # Export
    'ExportError',
    'FFmpegNotFoundError',
    'ExportFailedError',
    # Schema
    'SchemaError',
    'SchemaNotFoundError',
    'SchemaParseError',
    # Config
    'ConfigError',
    # Operation
    'OperationCancelledError',
    'PermissionDeniedError',
]
