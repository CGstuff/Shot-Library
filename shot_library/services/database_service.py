"""
DatabaseService - SQLite database management facade for Shot Library

Pattern: Facade pattern with repository delegation
Delegates to focused repository modules in services/database/
"""

import logging
import threading
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from contextlib import contextmanager

from ..config import Config

logger = logging.getLogger(__name__)


class AnimationsStub:
    """
    Stub class for Animation Library compatibility.

    Provides resolve methods that the VersionHistoryDialog expects.
    For Shot Library, these just return paths from the version dict directly.
    """

    def resolve_thumbnail_file(self, version: dict) -> Optional[Path]:
        """Return thumbnail path from version dict."""
        thumb_path = version.get('thumbnail_path')
        if thumb_path:
            path = Path(thumb_path)
            return path if path.exists() else None
        return None

    def resolve_preview_file(self, version: dict) -> Optional[Path]:
        """Return preview/playblast path from version dict."""
        preview_path = version.get('preview_path')
        if preview_path:
            path = Path(preview_path)
            return path if path.exists() else None
        return None


# Import from modular database package
from .database import (
    DatabaseConnection,
    SchemaManager,
    SCHEMA_VERSION,
    VERSION_FEATURES,
    backup_database,
    get_backups,
    delete_backup,
    ShotRepository,
    PlayblastRepository,
    LookdevRepository,
    RenderRepository,
    ReviewRepository,
    UserRepository,
    TaskRepository,
    AuditRepository,
)


class DatabaseService:
    """
    Database service facade for shot metadata storage.

    This class provides a unified API while delegating to focused repositories.

    Features:
    - Thread-local connections for thread safety
    - WAL mode for better concurrency
    - Transaction support
    - Automatic schema initialization and migrations

    Usage:
        db = DatabaseService()
        shot_id = db.shots.create(...)
        shots = db.shots.get_all()

    Direct repository access:
        db.shots.get_by_id(shot_id)
        db.playblasts.get_for_shot(shot_id)
        db.reviews.get_review_for_shot(shot_id)
        db.users.get_all()
        db.tasks.get_by_shot_id(shot_id)
        db.audit.get_recent(limit=50)
    """

    # Schema version (re-exported for compatibility)
    SCHEMA_VERSION = SCHEMA_VERSION

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database service.

        Args:
            db_path: Path to database file (defaults to Config.get_database_path())
        """
        self.db_path = db_path or Config.get_database_path()

        # Initialize connection manager
        self._connection = DatabaseConnection(self.db_path)

        # Initialize schema
        self._schema = SchemaManager(self._connection)
        self._schema.init_database()

        # Initialize repositories
        self.shots = ShotRepository(self._connection)
        self.playblasts = PlayblastRepository(self._connection)
        self.lookdevs = LookdevRepository(self._connection)
        self.renders = RenderRepository(self._connection)
        self.reviews = ReviewRepository(self._connection)
        self.users = UserRepository(self._connection)
        self.tasks = TaskRepository(self._connection)
        self.audit = AuditRepository(self._connection)

        # Stub for Animation Library compatibility (VersionHistoryDialog)
        self.animations = AnimationsStub()

        # Legacy attribute for backwards compatibility
        self.local = self._connection._local

    # ==================== CONNECTION METHODS ====================

    def _get_connection(self):
        """Get thread-local database connection."""
        return self._connection.get_connection()

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        with self._connection.transaction() as conn:
            yield conn

    def close(self):
        """Close database connection for current thread."""
        self._connection.close()

    # ==================== SHOT OPERATIONS (convenience wrappers) ====================

    def get_all_shots(self, order_by_editorial: bool = True) -> List[Dict[str, Any]]:
        """Get all shots in editorial order."""
        return self.shots.get_all(order_by_editorial=order_by_editorial)

    def get_shot_by_folder(self, folder_path: str) -> Optional[Dict[str, Any]]:
        """Get shot by folder path."""
        return self.shots.get_by_folder_path(folder_path)

    def get_shot_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Get shot by UUID."""
        return self.shots.get_by_id(uuid)

    def get_shots_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get shots filtered by status."""
        return self.shots.get_by_status(status)

    def get_shot_count(self) -> int:
        """Get total shot count."""
        return self.shots.count()

    def get_shot_count_by_status(self) -> Dict[str, int]:
        """Get shot count grouped by status."""
        return self.shots.count_by_status()

    def set_status(self, shot_id: str, status: str) -> bool:
        """
        Update the status of a shot.

        Args:
            shot_id: Shot UUID
            status: New status value (WIP, In Review, Approved, Final, Blocked)

        Returns:
            True if updated successfully, False otherwise
        """
        return self.shots.update(shot_id, status=status)

    # ==================== PLAYBLAST OPERATIONS (convenience wrappers) ====================

    def get_playblasts_for_shot(self, shot_id: str) -> List[Dict[str, Any]]:
        """Get all playblasts for a shot."""
        return self.playblasts.get_for_shot(shot_id)

    def get_latest_playblast(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """Get latest playblast for a shot."""
        return self.playblasts.get_latest_for_shot(shot_id)

    def get_playblast_count(self) -> int:
        """Get total playblast count."""
        return self.playblasts.count()

    # ==================== USER OPERATIONS (convenience wrappers) ====================

    def get_all_users(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Get all users."""
        return self.users.get_all(include_inactive=include_inactive)

    def get_user_count(self, active_only: bool = True) -> int:
        """Get user count."""
        return self.users.count(active_only=active_only)

    # ==================== APP SETTINGS ====================

    def get_app_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get an application setting from the shared database.

        Settings are stored in the app_settings table and are visible
        to external tools like Pipeline Control.

        Args:
            key: Setting key (e.g., 'operation_mode')
            default: Default value if key not found

        Returns:
            Setting value or default
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT value FROM app_settings WHERE key = ?',
                (key,)
            )
            row = cursor.fetchone()
            return row[0] if row else default
        except Exception as e:
            logger.error(f"Failed to get app setting '{key}': {e}")
            return default

    def set_app_setting(self, key: str, value: str) -> bool:
        """
        Set an application setting in the shared database.

        Settings are stored in the app_settings table and are visible
        to external tools like Pipeline Control.

        Args:
            key: Setting key (e.g., 'operation_mode')
            value: Setting value

        Returns:
            True if successful, False otherwise
        """
        try:
            from datetime import datetime
            now = datetime.now().isoformat()
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            ''', (key, value, now))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to set app setting '{key}': {e}")
            return False

    # ==================== DATABASE MAINTENANCE ====================

    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics for status display.

        Returns:
            Dict containing schema version, record counts, file size, pending features, etc.
        """
        return self._schema.get_database_stats()

    def run_integrity_check(self) -> Tuple[bool, str]:
        """
        Run database integrity check.

        Returns:
            Tuple of (is_ok, message)
        """
        return self._schema.run_integrity_check()

    def optimize_database(self) -> Tuple[int, int]:
        """
        Optimize database by running VACUUM.

        Returns:
            Tuple of (size_before, size_after) in bytes
        """
        return self._schema.optimize_database()

    def get_current_schema_version(self) -> int:
        """Get current schema version."""
        return self._schema.get_current_version()

    def create_backup(self) -> Path:
        """
        Create a backup of the database.

        Returns:
            Path to the backup file
        """
        return backup_database(self.db_path)

    def get_backups(self) -> List[Dict[str, Any]]:
        """
        Get list of existing backups.

        Returns:
            List of backup info dicts with 'path', 'size', 'date'
        """
        return get_backups(self.db_path)

    def delete_backup(self, backup_path: Path) -> bool:
        """
        Delete a backup file.

        Args:
            backup_path: Path to the backup file

        Returns:
            True if deleted successfully
        """
        return delete_backup(backup_path)

    def run_schema_upgrade(self) -> Tuple[bool, str]:
        """
        Run schema upgrade (migrations).

        Creates a backup first, then runs init_database() to apply migrations.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Get current version before upgrade
            before_version = self._schema.get_current_version()

            # Create backup before migration
            backup_path = self.create_backup()

            # Run migrations
            self._schema.init_database()

            # Get version after upgrade
            after_version = self._schema.get_current_version()

            if after_version > before_version:
                return True, f"Upgraded from v{before_version} to v{after_version}. Backup created at: {backup_path}"
            else:
                return True, f"Already at latest version (v{after_version}). Backup created at: {backup_path}"

        except Exception as e:
            return False, f"Upgrade failed: {str(e)}"

    # ==================== ANIMATION LIBRARY COMPATIBILITY STUBS ====================
    # Shot Library doesn't use these but they're needed for UI compatibility

    def get_all_rig_types(self) -> List[str]:
        """Stub: Shot Library doesn't have rig types. Returns empty list."""
        return []

    def get_all_tags(self) -> List[str]:
        """Stub: Shot Library doesn't use tags the same way. Returns empty list."""
        return []

    def get_all_animations(self) -> List[Dict[str, Any]]:
        """Stub: Returns empty list. Shot Library uses shots, not animations."""
        return []

    def get_animation_count(self) -> int:
        """Stub: Returns 0. Shot Library uses shots, not animations."""
        return 0

    def sync_library(self) -> Tuple[int, int]:
        """Stub: Returns (0, 0). Shot Library uses shot scanning instead."""
        return (0, 0)

    def clear_all_shots(self) -> int:
        """Clear all shots from the database. Returns count of cleared entries."""
        # TODO: Implement proper shot clearing when rebuild functionality is needed
        return 0

    def fix_pose_flags(self):
        """Stub: No-op. Shot Library doesn't have pose flags."""
        pass

    def get_animation_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Stub: Returns None. Shot Library uses shots, not animations."""
        return None

    def toggle_favorite(self, uuid: str) -> bool:
        """Stub: Returns False. Shot Library doesn't have animation favorites."""
        return False

    def get_version_count(self, version_group_id: str) -> int:
        """Get playblast version count for a shot."""
        playblasts = self.playblasts.get_for_shot(version_group_id)
        return len(playblasts)

    def get_version_history(self, version_group_id: str) -> list:
        """
        Get playblast version history for a shot.

        Maps playblast data to the format expected by VersionHistoryDialog.

        Args:
            version_group_id: Shot UUID (used as grouping key)

        Returns:
            List of version dicts with mapped fields
        """
        # Get shot info for name
        shot = self.shots.get_by_id(version_group_id)
        shot_name = shot.get('name', 'Unknown') if shot else 'Unknown'
        shot_status = shot.get('status', 'wip') if shot else 'wip'

        # Get all playblasts for this shot
        playblasts = self.playblasts.get_for_shot(version_group_id)

        # Map playblast data to animation-like format for dialog compatibility
        versions = []
        for pb in playblasts:
            version = {
                'uuid': pb.get('id'),
                'name': shot_name,
                'version': pb.get('version', 1),
                'version_label': f"v{pb.get('version', 1):03d}",
                'is_latest': pb.get('is_latest', 0),
                'status': shot_status,
                'frame_count': pb.get('frame_count'),
                'fps': pb.get('fps'),
                'duration_seconds': pb.get('duration_ms', 0) / 1000.0 if pb.get('duration_ms') else None,
                'preview_path': pb.get('file_path'),  # MP4 is the preview
                'thumbnail_path': None,  # Will be generated from video frame
                'width': pb.get('width'),
                'height': pb.get('height'),
                'created_at': pb.get('created_at'),
                'is_archived': pb.get('is_archived', 0),
            }
            versions.append(version)

        return versions

    def get_hierarchical_version_history(self, version_group_id: str) -> dict:
        """
        Get hierarchical version history for a shot version group.

        Returns shot versions (shot1_v001, shot1_v002, etc.) as parent items,
        each with their playblasts as children.

        Args:
            version_group_id: Version group UUID (shared by all shot versions)

        Returns:
            {
                'shot_versions': [
                    {
                        'shot_id': str,
                        'shot_name': str,
                        'shot_version_label': str,  # "v003"
                        'is_latest_shot_version': bool,
                        'status': str,
                        'playblasts': [
                            {
                                'uuid': str,
                                'version_label': str,
                                'is_latest': bool,
                                'frame_count': int,
                                'fps': int,
                                'preview_path': str,
                                'created_at': str,
                                ...
                            }
                        ]
                    },
                    ...
                ],
                'base_shot_name': str
            }
        """
        # Try multiple strategies to find shots:
        # 1. First, try to find shots by version_group_id directly
        shots_in_group = self.shots.get_shots_by_version_group(version_group_id)

        # 2. If no shots found, try looking up by shot id (version_group_id might be a shot uuid)
        shot = None
        if not shots_in_group:
            shot = self.shots.get_by_id(version_group_id)
            if shot:
                # Use this shot's version_group_id to find related shots
                actual_group_id = shot.get('version_group_id')
                if actual_group_id and actual_group_id != version_group_id:
                    shots_in_group = self.shots.get_shots_by_version_group(actual_group_id)

        if not shots_in_group and not shot:
            return {'shot_versions': [], 'base_shot_name': 'Unknown'}

        # Get base_shot_name from first available shot
        if shots_in_group:
            shot = shots_in_group[0]
        base_shot_name = shot.get('base_shot_name') or shot.get('shot_name', 'Unknown')
        actual_group_id = shot.get('version_group_id') or version_group_id

        # If only 1 shot found, try fallback: query by base_shot_name
        # This handles cases where version_group_id may not be set consistently
        if len(shots_in_group) <= 1 and base_shot_name:
            shots_by_name = self.shots.get_shots_by_base_name(base_shot_name)
            if len(shots_by_name) > len(shots_in_group):
                shots_in_group = shots_by_name

        # If no grouped shots found, just use the single shot
        if not shots_in_group:
            shots_in_group = [shot]

        # Build hierarchical structure
        shot_versions = []
        for shot_entry in shots_in_group:
            shot_id = shot_entry.get('id')
            shot_version = shot_entry.get('shot_version', 1)

            # Get playblasts for this shot
            playblasts = self.playblasts.get_for_shot(shot_id)

            # Map playblast data
            playblast_list = []
            for pb in playblasts:
                playblast_list.append({
                    'uuid': pb.get('id'),
                    'shot_id': shot_id,
                    'version': pb.get('version', 1),
                    'version_label': f"v{pb.get('version', 1):03d}",
                    'is_latest': bool(pb.get('is_latest', 0)),
                    'frame_count': pb.get('frame_count'),
                    'fps': pb.get('fps'),
                    'duration_ms': pb.get('duration_ms'),
                    'preview_path': pb.get('file_path'),
                    'thumbnail_path': None,
                    'width': pb.get('width'),
                    'height': pb.get('height'),
                    'created_at': pb.get('created_at'),
                    'is_archived': bool(pb.get('is_archived', 0)),
                })

            shot_versions.append({
                'shot_id': shot_id,
                'shot_name': shot_entry.get('shot_name', 'Unknown'),
                'shot_version': shot_version,
                'shot_version_label': f"v{shot_version:03d}" if shot_version else "v001",
                'is_latest_shot_version': bool(shot_entry.get('is_latest_shot_version', 0)),
                'status': shot_entry.get('status', 'WIP'),
                'folder_path': shot_entry.get('folder_path'),
                'playblasts': playblast_list,
                'playblast_count': len(playblast_list),
            })

        return {
            'shot_versions': shot_versions,
            'base_shot_name': base_shot_name,
        }

    def update_last_viewed(self, uuid: str) -> bool:
        """Stub: Shot Library doesn't track last viewed time for animations."""
        return False


# Singleton instance with thread safety
_database_service_instance: Optional[DatabaseService] = None
_database_service_lock = threading.Lock()


def get_database_service() -> DatabaseService:
    """
    Get global DatabaseService singleton instance (thread-safe).

    Returns:
        Global DatabaseService instance
    """
    global _database_service_instance
    if _database_service_instance is None:
        with _database_service_lock:
            # Double-check after acquiring lock
            if _database_service_instance is None:
                _database_service_instance = DatabaseService()
    return _database_service_instance


__all__ = ['DatabaseService', 'get_database_service']
