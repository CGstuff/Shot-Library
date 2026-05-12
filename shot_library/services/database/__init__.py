"""
Database Module - Shot Library Database Operations

This module provides focused database repositories for shot production visibility:
- connection: Thread-safe connection management
- schema: Schema initialization for shot domain
- shots: Shot CRUD operations
- playblasts: Playblast version tracking
- reviews: Review sessions, comments, and annotations
- users: User profile management
- tasks: Task assignments for Pipeline Control integration
- audit: Audit trail logging for all events
"""

from .connection import DatabaseConnection
from .schema import (
    SchemaManager,
    SCHEMA_VERSION,
    VERSION_FEATURES,
    backup_database,
    get_backups,
    delete_backup,
)
from .shots import ShotRepository
from .playblasts import PlayblastRepository
from .lookdevs import LookdevRepository
from .renders import RenderRepository
from .reviews import ReviewRepository
from .users import UserRepository
from .tasks import TaskRepository
from .folder_schemas import FolderSchemaRepository
from .audit import AuditRepository

__all__ = [
    # Connection
    'DatabaseConnection',
    # Schema
    'SchemaManager',
    'SCHEMA_VERSION',
    'VERSION_FEATURES',
    'backup_database',
    'get_backups',
    'delete_backup',
    # Repositories
    'ShotRepository',
    'PlayblastRepository',
    'LookdevRepository',
    'RenderRepository',
    'ReviewRepository',
    'UserRepository',
    'TaskRepository',
    'FolderSchemaRepository',
    'AuditRepository',
]
