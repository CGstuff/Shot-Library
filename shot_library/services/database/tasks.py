"""
Task CRUD Operations

Database operations for tasks table.
Used for shot assignments and Pipeline Control integration.
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection


class TaskRepository:
    """Repository for task database operations."""

    # Valid priority values
    PRIORITIES = ['low', 'medium', 'high', 'urgent']
    
    # Valid task status values
    STATUSES = ['pending', 'in_progress', 'done']

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize repository.

        Args:
            connection: Database connection manager
        """
        self._conn = connection

    def create(
        self,
        shot_id: str,
        assigned_to: Optional[str] = None,
        assigned_by: Optional[str] = None,
        priority: str = 'medium',
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        status: str = 'pending',
    ) -> str:
        """
        Create a new task for a shot.

        Args:
            shot_id: UUID of the shot
            assigned_to: UUID of assigned user (optional)
            assigned_by: UUID of user who assigned (optional)
            priority: Task priority (low, medium, high, urgent)
            due_date: ISO format due date (optional)
            notes: Task notes (optional)
            status: Task status (pending, in_progress, done)

        Returns:
            UUID of created task

        Raises:
            ValueError: If priority or status is invalid
        """
        if priority not in self.PRIORITIES:
            raise ValueError(f"Priority must be one of: {', '.join(self.PRIORITIES)}")
        
        if status not in self.STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(self.STATUSES)}")

        task_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (
                    id, shot_id, assigned_to, assigned_by,
                    priority, due_date, notes, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id, shot_id, assigned_to, assigned_by,
                priority, due_date, notes, status,
                now, now
            ))

        return task_id

    def get_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID with joined user/shot names."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                t.*,
                s.shot_name,
                u1.display_name as assigned_to_name,
                u2.display_name as assigned_by_name
            FROM tasks t
            LEFT JOIN shots s ON t.shot_id = s.id
            LEFT JOIN users u1 ON t.assigned_to = u1.id
            LEFT JOIN users u2 ON t.assigned_by = u2.id
            WHERE t.id = ?
        ''', (task_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_shot_id(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task for a shot (one task per shot).
        
        Args:
            shot_id: UUID of the shot
            
        Returns:
            Task dict or None
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                t.*,
                s.shot_name,
                u1.display_name as assigned_to_name,
                u2.display_name as assigned_by_name
            FROM tasks t
            LEFT JOIN shots s ON t.shot_id = s.id
            LEFT JOIN users u1 ON t.assigned_to = u1.id
            LEFT JOIN users u2 ON t.assigned_by = u2.id
            WHERE t.shot_id = ?
            ORDER BY t.created_at DESC
            LIMIT 1
        ''', (shot_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_all(
        self,
        assigned_to: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        include_done: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all tasks with optional filters.

        Args:
            assigned_to: Filter by assigned user ID
            priority: Filter by priority
            status: Filter by status
            include_done: Include completed tasks

        Returns:
            List of task dicts with joined names
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        query = '''
            SELECT 
                t.*,
                s.shot_name,
                u1.display_name as assigned_to_name,
                u2.display_name as assigned_by_name
            FROM tasks t
            LEFT JOIN shots s ON t.shot_id = s.id
            LEFT JOIN users u1 ON t.assigned_to = u1.id
            LEFT JOIN users u2 ON t.assigned_by = u2.id
            WHERE 1=1
        '''
        params = []

        if assigned_to:
            query += ' AND t.assigned_to = ?'
            params.append(assigned_to)

        if priority:
            query += ' AND t.priority = ?'
            params.append(priority)

        if status:
            query += ' AND t.status = ?'
            params.append(status)
        elif not include_done:
            query += " AND t.status != 'done'"

        query += ' ORDER BY t.due_date ASC NULLS LAST, t.created_at DESC'

        cursor.execute(query, params)
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_by_assignee(self, user_id: str, include_done: bool = False) -> List[Dict[str, Any]]:
        """Get all tasks assigned to a user."""
        return self.get_all(assigned_to=user_id, include_done=include_done)

    def get_overdue(self) -> List[Dict[str, Any]]:
        """Get all overdue tasks (past due date and not done)."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        cursor.execute('''
            SELECT 
                t.*,
                s.shot_name,
                u1.display_name as assigned_to_name,
                u2.display_name as assigned_by_name
            FROM tasks t
            LEFT JOIN shots s ON t.shot_id = s.id
            LEFT JOIN users u1 ON t.assigned_to = u1.id
            LEFT JOIN users u2 ON t.assigned_by = u2.id
            WHERE t.due_date IS NOT NULL 
              AND t.due_date < ?
              AND t.status != 'done'
            ORDER BY t.due_date ASC
        ''', (now,))
        
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def update(
        self,
        task_id: str,
        assigned_to: Optional[str] = None,
        priority: Optional[str] = None,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None,
    ) -> bool:
        """
        Update a task.

        Args:
            task_id: Task UUID
            assigned_to: New assigned user (None to keep, '' to clear)
            priority: New priority
            due_date: New due date (None to keep, '' to clear)
            notes: New notes (None to keep, '' to clear)
            status: New status

        Returns:
            True if updated, False if not found

        Raises:
            ValueError: If priority or status is invalid
        """
        updates = []
        params = []

        if assigned_to is not None:
            updates.append("assigned_to = ?")
            params.append(assigned_to if assigned_to else None)
            
        if priority is not None:
            if priority not in self.PRIORITIES:
                raise ValueError(f"Priority must be one of: {', '.join(self.PRIORITIES)}")
            updates.append("priority = ?")
            params.append(priority)
            
        if due_date is not None:
            updates.append("due_date = ?")
            params.append(due_date if due_date else None)
            
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes if notes else None)
            
        if status is not None:
            if status not in self.STATUSES:
                raise ValueError(f"Status must be one of: {', '.join(self.STATUSES)}")
            updates.append("status = ?")
            params.append(status)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(task_id)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE tasks SET {", ".join(updates)} WHERE id = ?',
                params
            )
            return cursor.rowcount > 0

    def assign(
        self,
        task_id: str,
        assigned_to: str,
        assigned_by: str,
    ) -> bool:
        """
        Assign a task to a user.

        Args:
            task_id: Task UUID
            assigned_to: User UUID to assign to
            assigned_by: User UUID who is assigning

        Returns:
            True if updated, False if not found
        """
        now = datetime.now().isoformat()
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tasks 
                SET assigned_to = ?, assigned_by = ?, updated_at = ?
                WHERE id = ?
            ''', (assigned_to, assigned_by, now, task_id))
            return cursor.rowcount > 0

    def unassign(self, task_id: str) -> bool:
        """
        Remove assignment from a task.

        Args:
            task_id: Task UUID

        Returns:
            True if updated, False if not found
        """
        now = datetime.now().isoformat()
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tasks 
                SET assigned_to = NULL, updated_at = ?
                WHERE id = ?
            ''', (now, task_id))
            return cursor.rowcount > 0

    def set_priority(self, task_id: str, priority: str) -> bool:
        """Set task priority."""
        return self.update(task_id, priority=priority)

    def set_status(self, task_id: str, status: str) -> bool:
        """Set task status."""
        return self.update(task_id, status=status)

    def set_due_date(self, task_id: str, due_date: Optional[str]) -> bool:
        """Set task due date (pass None or '' to clear)."""
        return self.update(task_id, due_date=due_date if due_date else '')

    def delete(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: Task UUID

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            return cursor.rowcount > 0

    def delete_by_shot(self, shot_id: str) -> int:
        """
        Delete all tasks for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Number of tasks deleted
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tasks WHERE shot_id = ?', (shot_id,))
            return cursor.rowcount

    def count(self, status: Optional[str] = None) -> int:
        """Get task count, optionally filtered by status."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        if status:
            cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', (status,))
        else:
            cursor.execute('SELECT COUNT(*) FROM tasks')

        return cursor.fetchone()[0]

    def count_by_priority(self) -> Dict[str, int]:
        """Get task counts grouped by priority."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT priority, COUNT(*) as count 
            FROM tasks 
            WHERE status != 'done'
            GROUP BY priority
        ''')
        return {row[0]: row[1] for row in cursor.fetchall()}

    def count_by_assignee(self) -> Dict[str, int]:
        """Get task counts grouped by assignee."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                COALESCE(u.display_name, 'Unassigned') as assignee,
                COUNT(*) as count 
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to = u.id
            WHERE t.status != 'done'
            GROUP BY t.assigned_to
        ''')
        return {row[0]: row[1] for row in cursor.fetchall()}

    def get_or_create_for_shot(
        self,
        shot_id: str,
        assigned_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get existing task for shot, or create one if none exists.
        
        Args:
            shot_id: UUID of the shot
            assigned_by: User creating the task (if new)
            
        Returns:
            Task dict
        """
        existing = self.get_by_shot_id(shot_id)
        if existing:
            return existing
            
        # Create new task
        task_id = self.create(
            shot_id=shot_id,
            assigned_by=assigned_by,
        )
        return self.get_by_id(task_id)

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))


__all__ = ['TaskRepository']
