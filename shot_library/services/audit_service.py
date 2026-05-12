"""
AuditService - Centralized audit logging for Shot Library

Logs all significant events in Shot Mode:
- Shot status changes
- Focused views (version history, playblast detail)
- Playblast discovery
- Note/drawover changes
- User management actions

The audit trail is stored in the main shot_library.db (in .meta/ folder)
and can be accessed by external tools like the Kitsu-style orchestration app.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List, Any, Dict, TYPE_CHECKING
import json
import logging

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from .database_service import DatabaseService
    from .user_service import UserService

logger = logging.getLogger(__name__)


class AuditAction(Enum):
    """Audit action types."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    RESTORED = "restored"
    VIEWED = "viewed"
    STATUS_CHANGED = "status_changed"
    DISCOVERED = "discovered"  # For playblast indexing
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"


class AuditEntityType(Enum):
    """Entity types that can be audited."""
    SHOT = "shot"
    PLAYBLAST = "playblast"
    NOTE = "note"
    DRAWOVER = "drawover"
    USER = "user"
    PLAYLIST = "playlist"  # Future
    PROJECT = "project"


@dataclass
class AuditEvent:
    """Represents a single audit event."""
    id: int
    timestamp: datetime
    user_id: Optional[str]
    username: str
    entity_type: str
    entity_id: str
    entity_name: str
    action: str
    field_changed: Optional[str]
    old_value: Optional[Any]
    new_value: Optional[Any]
    metadata: Optional[Dict]
    project_path: Optional[str]


class AuditService(QObject):
    """
    Centralized audit logging service.
    
    This service provides a high-level API for logging audit events
    throughout Shot Library. It handles user context, JSON serialization,
    and emits signals for real-time updates.
    
    Usage:
        audit = AuditService(db_service, user_service)
        audit.log_status_change(shot_id, "SH0010", "WIP", "Review")
        audit.log_view(AuditEntityType.PLAYBLAST, pb_id, "SH0010_v001.mp4")
        
    Query:
        events = audit.get_recent_activity(limit=50)
        history = audit.get_entity_history(AuditEntityType.SHOT, shot_id)
    """
    
    # Signals for real-time updates
    event_logged = pyqtSignal(object)  # AuditEvent
    
    def __init__(
        self,
        db_service: 'DatabaseService',
        user_service: Optional['UserService'] = None,
        parent=None
    ):
        """
        Initialize audit service.
        
        Args:
            db_service: Database service for persistence
            user_service: User service for current user context (optional)
            parent: Qt parent object
        """
        super().__init__(parent)
        self._db = db_service
        self._user_service = user_service
        self._project_path: Optional[str] = None
        self._enabled = True  # Can be disabled for bulk operations
        
        logger.info("AuditService initialized")
    
    def set_project_path(self, path: str):
        """
        Set current project path for context.
        
        This is automatically set when a folder is scanned.
        
        Args:
            path: Project/production folder path
        """
        self._project_path = path
        logger.debug(f"Audit project path set to: {path}")
    
    def set_enabled(self, enabled: bool):
        """
        Enable or disable audit logging.
        
        Useful for bulk operations where individual logging would be noisy.
        
        Args:
            enabled: Whether to log events
        """
        self._enabled = enabled
    
    def _get_current_user(self) -> tuple:
        """
        Get current user ID and username.
        
        Returns:
            Tuple of (user_id, username)
        """
        if self._user_service:
            user = self._user_service.get_active_user()
            if user:
                return str(user.id), user.username
        return None, "system"
    
    # ==================== CORE LOGGING METHODS ====================
    
    def log_event(
        self,
        entity_type: AuditEntityType,
        entity_id: str,
        action: AuditAction,
        entity_name: str = "",
        field_changed: Optional[str] = None,
        old_value: Any = None,
        new_value: Any = None,
        metadata: Optional[Dict] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None
    ) -> Optional[int]:
        """
        Log an audit event.
        
        This is the core logging method. Other methods are convenience
        wrappers around this.
        
        Args:
            entity_type: Type of entity being audited
            entity_id: UUID or identifier of the entity
            action: Action being performed
            entity_name: Human-readable name for display
            field_changed: Which field was changed (for updates)
            old_value: Previous value (will be JSON serialized)
            new_value: New value (will be JSON serialized)
            metadata: Additional context (will be JSON serialized)
            user_id: Override user ID (uses current user if not provided)
            username: Override username (uses current user if not provided)
        
        Returns:
            Event ID, or None if logging is disabled or fails
        """
        if not self._enabled:
            return None
        
        try:
            # Get user context
            if user_id is None or username is None:
                auto_user_id, auto_username = self._get_current_user()
                user_id = user_id or auto_user_id
                username = username or auto_username
            
            # Serialize values to JSON
            old_json = json.dumps(old_value) if old_value is not None else None
            new_json = json.dumps(new_value) if new_value is not None else None
            meta_json = json.dumps(metadata) if metadata else None
            
            # Insert into database
            event_id = self._db.audit.insert(
                entity_type=entity_type.value,
                entity_id=entity_id,
                action=action.value,
                user_id=user_id,
                username=username,
                entity_name=entity_name,
                field_changed=field_changed,
                old_value=old_json,
                new_value=new_json,
                metadata=meta_json,
                project_path=self._project_path
            )
            
            # Emit signal for real-time updates
            row = self._db.audit.get_by_id(event_id)
            if row:
                event = self._row_to_event(row)
                self.event_logged.emit(event)
            
            logger.debug(
                f"Audit: {action.value} {entity_type.value} '{entity_name}' "
                f"by {username}"
            )
            
            return event_id
            
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
            return None
    
    # ==================== CONVENIENCE METHODS ====================
    
    def log_view(
        self,
        entity_type: AuditEntityType,
        entity_id: str,
        entity_name: str
    ) -> Optional[int]:
        """
        Log a focused view event.
        
        Called when user opens version history or views detailed info.
        NOT called for every card click (only focused views).
        
        Args:
            entity_type: Type of entity being viewed
            entity_id: Entity identifier
            entity_name: Human-readable name
        
        Returns:
            Event ID
        """
        return self.log_event(
            entity_type=entity_type,
            entity_id=entity_id,
            action=AuditAction.VIEWED,
            entity_name=entity_name
        )
    
    def log_status_change(
        self,
        shot_id: str,
        shot_name: str,
        old_status: str,
        new_status: str
    ) -> Optional[int]:
        """
        Log a shot status change.
        
        Args:
            shot_id: Shot UUID
            shot_name: Shot name for display
            old_status: Previous status value
            new_status: New status value
        
        Returns:
            Event ID
        """
        return self.log_event(
            entity_type=AuditEntityType.SHOT,
            entity_id=shot_id,
            action=AuditAction.STATUS_CHANGED,
            entity_name=shot_name,
            field_changed="status",
            old_value=old_status,
            new_value=new_status
        )
    
    def log_playblast_discovered(
        self,
        playblast_id: str,
        playblast_name: str,
        shot_id: Optional[str] = None,
        shot_name: Optional[str] = None,
        version: Optional[int] = None
    ) -> Optional[int]:
        """
        Log playblast discovery by indexer.
        
        Called when a new playblast file is found during scanning.
        
        Args:
            playblast_id: Playblast identifier (usually file path)
            playblast_name: Filename for display
            shot_id: Associated shot UUID
            shot_name: Associated shot name
            version: Playblast version number
        
        Returns:
            Event ID
        """
        metadata = {}
        if shot_id:
            metadata['shot_id'] = shot_id
        if shot_name:
            metadata['shot_name'] = shot_name
        if version is not None:
            metadata['version'] = version
        
        return self.log_event(
            entity_type=AuditEntityType.PLAYBLAST,
            entity_id=playblast_id,
            action=AuditAction.DISCOVERED,
            entity_name=playblast_name,
            metadata=metadata if metadata else None
        )
    
    def log_playblast_viewed(
        self,
        playblast_id: str,
        playblast_name: str,
        shot_name: Optional[str] = None
    ) -> Optional[int]:
        """
        Log playblast view in version history.
        
        Args:
            playblast_id: Playblast identifier
            playblast_name: Filename for display
            shot_name: Associated shot name
        
        Returns:
            Event ID
        """
        metadata = {'shot_name': shot_name} if shot_name else None
        
        return self.log_event(
            entity_type=AuditEntityType.PLAYBLAST,
            entity_id=playblast_id,
            action=AuditAction.VIEWED,
            entity_name=playblast_name,
            metadata=metadata
        )
    
    def log_user_login(self, user_id: str, username: str) -> Optional[int]:
        """
        Log user login/activation.
        
        Args:
            user_id: User UUID
            username: Username
        
        Returns:
            Event ID
        """
        return self.log_event(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=AuditAction.LOGGED_IN,
            entity_name=username,
            user_id=user_id,
            username=username
        )
    
    def log_user_created(
        self,
        user_id: str,
        username: str,
        created_by_id: Optional[str] = None,
        created_by_name: Optional[str] = None
    ) -> Optional[int]:
        """
        Log user creation.
        
        Args:
            user_id: New user's UUID
            username: New user's username
            created_by_id: Admin who created the user
            created_by_name: Admin's username
        
        Returns:
            Event ID
        """
        return self.log_event(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=AuditAction.CREATED,
            entity_name=username,
            user_id=created_by_id,
            username=created_by_name or "system"
        )
    
    def log_user_updated(
        self,
        user_id: str,
        username: str,
        field_changed: str,
        old_value: Any,
        new_value: Any
    ) -> Optional[int]:
        """
        Log user profile update.
        
        Args:
            user_id: User's UUID
            username: User's username
            field_changed: Which field was changed
            old_value: Previous value
            new_value: New value
        
        Returns:
            Event ID
        """
        return self.log_event(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=AuditAction.UPDATED,
            entity_name=username,
            field_changed=field_changed,
            old_value=old_value,
            new_value=new_value
        )
    
    def log_user_deactivated(self, user_id: str, username: str) -> Optional[int]:
        """
        Log user deactivation.
        
        Args:
            user_id: User's UUID
            username: User's username
        
        Returns:
            Event ID
        """
        return self.log_event(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=AuditAction.DELETED,
            entity_name=username,
            metadata={'soft_delete': True}
        )
    
    def log_note_action(
        self,
        note_id: str,
        action: AuditAction,
        shot_name: str,
        frame: Optional[int] = None,
        content: Optional[str] = None
    ) -> Optional[int]:
        """
        Log note create/edit/delete.
        
        Args:
            note_id: Note identifier
            action: Action (created, updated, deleted)
            shot_name: Associated shot name
            frame: Frame number if applicable
            content: Note content preview
        
        Returns:
            Event ID
        """
        metadata = {}
        if frame is not None:
            metadata['frame'] = frame
        if content:
            # Truncate content for audit log
            metadata['content_preview'] = content[:100] + ('...' if len(content) > 100 else '')
        
        return self.log_event(
            entity_type=AuditEntityType.NOTE,
            entity_id=note_id,
            action=action,
            entity_name=f"Note on {shot_name}",
            metadata=metadata if metadata else None
        )
    
    # ==================== QUERY METHODS ====================
    
    def get_entity_history(
        self,
        entity_type: AuditEntityType,
        entity_id: str,
        limit: int = 100
    ) -> List[AuditEvent]:
        """
        Get history for a specific entity.
        
        Args:
            entity_type: Entity type to filter by
            entity_id: Entity ID to filter by
            limit: Maximum number of results
        
        Returns:
            List of AuditEvents, newest first
        """
        rows = self._db.audit.get_by_entity(entity_type.value, entity_id, limit)
        return [self._row_to_event(r) for r in rows]
    
    def get_recent_activity(
        self,
        limit: int = 50,
        entity_types: Optional[List[AuditEntityType]] = None,
        actions: Optional[List[AuditAction]] = None,
        since: Optional[datetime] = None
    ) -> List[AuditEvent]:
        """
        Get recent activity feed.
        
        Args:
            limit: Maximum number of results
            entity_types: Filter by entity types
            actions: Filter by actions
            since: Only return events after this timestamp
        
        Returns:
            List of AuditEvents, newest first
        """
        type_values = [t.value for t in entity_types] if entity_types else None
        action_values = [a.value for a in actions] if actions else None
        
        rows = self._db.audit.get_recent(
            limit=limit,
            entity_types=type_values,
            actions=action_values,
            since=since,
            project_path=self._project_path
        )
        return [self._row_to_event(r) for r in rows]
    
    def get_user_activity(self, user_id: str, limit: int = 50) -> List[AuditEvent]:
        """
        Get activity by a specific user.
        
        Args:
            user_id: User UUID to filter by
            limit: Maximum number of results
        
        Returns:
            List of AuditEvents, newest first
        """
        rows = self._db.audit.get_by_user(user_id, limit)
        return [self._row_to_event(r) for r in rows]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get audit statistics for current project.
        
        Returns:
            Dictionary with counts by action, entity type, etc.
        """
        return self._db.audit.get_stats(project_path=self._project_path)
    
    # ==================== HELPERS ====================
    
    def _row_to_event(self, row: Dict) -> AuditEvent:
        """Convert database row to AuditEvent."""
        return AuditEvent(
            id=row['id'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            user_id=row.get('user_id'),
            username=row['username'],
            entity_type=row['entity_type'],
            entity_id=row['entity_id'],
            entity_name=row.get('entity_name', ''),
            action=row['action'],
            field_changed=row.get('field_changed'),
            old_value=json.loads(row['old_value']) if row.get('old_value') else None,
            new_value=json.loads(row['new_value']) if row.get('new_value') else None,
            metadata=json.loads(row['metadata']) if row.get('metadata') else None,
            project_path=row.get('project_path')
        )


__all__ = [
    'AuditAction',
    'AuditEntityType',
    'AuditEvent',
    'AuditService',
]
