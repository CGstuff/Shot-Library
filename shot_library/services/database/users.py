"""
User CRUD Operations

Database operations for users table.
"""

import sqlite3
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection


class UserRepository:
    """Repository for user database operations."""

    # Default color palette
    DEFAULT_COLORS = [
        "#E74C3C",  # Red
        "#3498DB",  # Blue
        "#2ECC71",  # Green
        "#F39C12",  # Orange
        "#9B59B6",  # Purple
        "#1ABC9C",  # Teal
        "#E91E63",  # Pink
        "#00BCD4",  # Cyan
    ]

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize repository.

        Args:
            connection: Database connection manager
        """
        self._conn = connection

    def create(
        self,
        username: str,
        display_name: str,
        color: str,
        role: str = "reviewer",
        is_active: bool = True,
    ) -> str:
        """
        Create a new user.

        Args:
            username: Unique username (alphanumeric + underscore, 3-32 chars)
            display_name: Display name (1-64 chars)
            color: Hex color (#RRGGBB)
            role: User role ('admin' or 'reviewer')
            is_active: Whether user is active

        Returns:
            UUID of created user

        Raises:
            ValueError: If username or color is invalid
        """
        if not self._validate_username(username):
            raise ValueError(
                "Username must be 3-32 alphanumeric characters or underscores"
            )

        if not self._validate_color(color):
            raise ValueError("Color must be a valid hex color (#RRGGBB)")

        if role not in ('admin', 'reviewer'):
            raise ValueError("Role must be 'admin' or 'reviewer'")

        user_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (
                    id, username, display_name, color, role, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, display_name, color, role,
                1 if is_active else 0, now, now
            ))

        return user_id

    def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username (case-insensitive)."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_all(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        Get all users.

        Args:
            include_inactive: Whether to include inactive users

        Returns:
            List of user dicts
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        if include_inactive:
            cursor.execute('SELECT * FROM users ORDER BY display_name ASC')
        else:
            cursor.execute(
                'SELECT * FROM users WHERE is_active = 1 ORDER BY display_name ASC'
            )

        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_admins(self) -> List[Dict[str, Any]]:
        """Get all active admin users."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE role = 'admin' AND is_active = 1 ORDER BY display_name ASC"
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def update(
        self,
        user_id: str,
        display_name: Optional[str] = None,
        color: Optional[str] = None,
        role: Optional[str] = None,
    ) -> bool:
        """
        Update a user.

        Args:
            user_id: User UUID
            display_name: New display name
            color: New color
            role: New role

        Returns:
            True if updated, False if not found

        Raises:
            ValueError: If color or role is invalid
        """
        updates = []
        params = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if color is not None:
            if not self._validate_color(color):
                raise ValueError("Color must be a valid hex color (#RRGGBB)")
            updates.append("color = ?")
            params.append(color)
        if role is not None:
            if role not in ('admin', 'reviewer'):
                raise ValueError("Role must be 'admin' or 'reviewer'")
            updates.append("role = ?")
            params.append(role)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(user_id)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE users SET {", ".join(updates)} WHERE id = ?',
                params
            )
            return cursor.rowcount > 0

    def deactivate(self, user_id: str) -> bool:
        """
        Deactivate a user (soft delete).

        Args:
            user_id: User UUID

        Returns:
            True if deactivated, False if not found
        """
        now = datetime.now().isoformat()
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET is_active = 0, updated_at = ? WHERE id = ?',
                (now, user_id)
            )
            return cursor.rowcount > 0

    def reactivate(self, user_id: str) -> bool:
        """
        Reactivate a deactivated user.

        Args:
            user_id: User UUID

        Returns:
            True if reactivated, False if not found
        """
        now = datetime.now().isoformat()
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET is_active = 1, updated_at = ? WHERE id = ?',
                (now, user_id)
            )
            return cursor.rowcount > 0

    def delete(self, user_id: str) -> bool:
        """
        Permanently delete a user.

        Args:
            user_id: User UUID

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            return cursor.rowcount > 0

    def exists(self, username: str) -> bool:
        """Check if username exists (case-insensitive)."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM users WHERE username = ? LIMIT 1',
            (username,)
        )
        return cursor.fetchone() is not None

    def count(self, active_only: bool = True) -> int:
        """Get user count."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        if active_only:
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
        else:
            cursor.execute('SELECT COUNT(*) FROM users')

        return cursor.fetchone()[0]

    def get_used_colors(self) -> List[str]:
        """Get list of colors used by active users."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT color FROM users WHERE is_active = 1')
        return [row[0] for row in cursor.fetchall()]

    def get_available_colors(self) -> List[str]:
        """Get list of colors not used by active users."""
        used_colors = set(self.get_used_colors())
        return [c for c in self.DEFAULT_COLORS if c not in used_colors]

    def get_first_available_color(self) -> str:
        """Get first available color, or a default if all are used."""
        available = self.get_available_colors()
        if available:
            return available[0]
        return self.DEFAULT_COLORS[0]

    def _validate_username(self, username: str) -> bool:
        """Validate username format."""
        return bool(re.match(r'^[a-zA-Z0-9_]{3,32}$', username))

    def _validate_color(self, color: str) -> bool:
        """Validate hex color format."""
        return bool(re.match(r'^#[0-9A-Fa-f]{6}$', color))

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        result = dict(zip(columns, row))
        # Convert is_active to boolean
        result['is_active'] = bool(result.get('is_active', 0))
        return result


__all__ = ['UserRepository']
