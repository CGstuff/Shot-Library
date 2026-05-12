"""
Audit Repository - Database operations for audit log

Provides CRUD operations for the audit_log table which tracks
all significant events in Shot Library (Shot Mode).
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

from .connection import DatabaseConnection


class AuditRepository:
    """
    Repository for audit log database operations.
    
    The audit log tracks:
    - Shot status changes
    - Focused views (version history, playblast detail)
    - Playblast discovery
    - Note/drawover changes
    - User management actions
    """

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize repository.

        Args:
            connection: Database connection manager
        """
        self._conn = connection
        self._init_table()

    def _init_table(self):
        """Create audit_log table if not exists."""
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            
            # Create main audit log table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    
                    -- Who performed the action
                    user_id TEXT,
                    username TEXT NOT NULL DEFAULT 'system',
                    
                    -- What entity was affected
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    entity_name TEXT,
                    
                    -- What action was taken
                    action TEXT NOT NULL,
                    
                    -- Change details (for updates)
                    field_changed TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    
                    -- Additional context
                    metadata TEXT,
                    project_path TEXT
                )
            ''')
            
            # Create indexes for common queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp 
                ON audit_log(timestamp DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_entity 
                ON audit_log(entity_type, entity_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_user 
                ON audit_log(user_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_action 
                ON audit_log(action)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_project 
                ON audit_log(project_path)
            ''')

    def insert(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        user_id: Optional[str] = None,
        username: str = 'system',
        entity_name: Optional[str] = None,
        field_changed: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        metadata: Optional[str] = None,
        project_path: Optional[str] = None
    ) -> int:
        """
        Insert an audit event.

        Args:
            entity_type: Type of entity ('shot', 'playblast', 'note', 'user', etc.)
            entity_id: UUID or identifier of the entity
            action: Action performed ('created', 'updated', 'viewed', etc.)
            user_id: UUID of user who performed action (None for system)
            username: Username for display (defaults to 'system')
            entity_name: Human-readable name (shot name, filename, etc.)
            field_changed: Which field was changed (for updates)
            old_value: Previous value (JSON string)
            new_value: New value (JSON string)
            metadata: Additional context (JSON string)
            project_path: Project/production folder path

        Returns:
            ID of inserted audit event
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO audit_log (
                    user_id, username, entity_type, entity_id, entity_name,
                    action, field_changed, old_value, new_value, metadata, project_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, entity_type, entity_id, entity_name,
                action, field_changed, old_value, new_value, metadata, project_path
            ))
            return cursor.lastrowid

    def get_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Get audit event by ID."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM audit_log WHERE id = ?', (event_id,))
        row = cursor.fetchone()
        
        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_entity(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get history for a specific entity.

        Args:
            entity_type: Entity type to filter by
            entity_id: Entity ID to filter by
            limit: Maximum number of results

        Returns:
            List of audit events, newest first
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM audit_log 
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (entity_type, entity_id, limit))
        
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_by_user(
        self,
        user_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get activity by a specific user.

        Args:
            user_id: User UUID to filter by
            limit: Maximum number of results

        Returns:
            List of audit events, newest first
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM audit_log 
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (user_id, limit))
        
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_recent(
        self,
        limit: int = 50,
        entity_types: Optional[List[str]] = None,
        actions: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        project_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent activity with optional filters.

        Args:
            limit: Maximum number of results
            entity_types: Filter by entity types (e.g., ['shot', 'playblast'])
            actions: Filter by actions (e.g., ['status_changed', 'viewed'])
            since: Only return events after this timestamp
            project_path: Filter by project path

        Returns:
            List of audit events, newest first
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM audit_log WHERE 1=1'
        params = []
        
        if entity_types:
            placeholders = ','.join('?' * len(entity_types))
            query += f' AND entity_type IN ({placeholders})'
            params.extend(entity_types)
        
        if actions:
            placeholders = ','.join('?' * len(actions))
            query += f' AND action IN ({placeholders})'
            params.extend(actions)
        
        if since:
            query += ' AND timestamp > ?'
            params.append(since.isoformat())
        
        if project_path:
            query += ' AND project_path = ?'
            params.append(project_path)
        
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_stats(self, project_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Get audit statistics.

        Args:
            project_path: Optional project path to filter by

        Returns:
            Dictionary with counts by action, entity type, etc.
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        
        where_clause = ''
        params = []
        if project_path:
            where_clause = 'WHERE project_path = ?'
            params = [project_path]
        
        # Total count
        cursor.execute(f'SELECT COUNT(*) FROM audit_log {where_clause}', params)
        total = cursor.fetchone()[0]
        
        # Count by action
        cursor.execute(f'''
            SELECT action, COUNT(*) as count 
            FROM audit_log {where_clause}
            GROUP BY action
            ORDER BY count DESC
        ''', params)
        by_action = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Count by entity type
        cursor.execute(f'''
            SELECT entity_type, COUNT(*) as count 
            FROM audit_log {where_clause}
            GROUP BY entity_type
            ORDER BY count DESC
        ''', params)
        by_entity = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Count by user (top 10)
        cursor.execute(f'''
            SELECT username, COUNT(*) as count 
            FROM audit_log {where_clause}
            GROUP BY username
            ORDER BY count DESC
            LIMIT 10
        ''', params)
        by_user = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Recent activity (last 24 hours)
        cursor.execute(f'''
            SELECT COUNT(*) FROM audit_log 
            WHERE timestamp > datetime('now', '-1 day')
            {' AND project_path = ?' if project_path else ''}
        ''', params)
        last_24h = cursor.fetchone()[0]
        
        return {
            'total': total,
            'by_action': by_action,
            'by_entity_type': by_entity,
            'by_user': by_user,
            'last_24_hours': last_24h
        }

    def delete_old(self, days: int = 365) -> int:
        """
        Delete audit events older than specified days.
        
        Note: By default we keep forever, but this method exists
        for future use if retention policy changes.

        Args:
            days: Delete events older than this many days

        Returns:
            Number of deleted events
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM audit_log 
                WHERE timestamp < datetime('now', ?)
            ''', (f'-{days} days',))
            return cursor.rowcount

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))


__all__ = ['AuditRepository']
