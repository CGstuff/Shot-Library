"""
Render CRUD Operations

Database operations for renders table.
Renders use folder-based versioning (unlike playblasts which use filename versioning).
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection


class RenderRepository:
    """Repository for render database operations."""

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
        version: int,
        folder_path: str,
        frame_start: Optional[int] = None,
        frame_end: Optional[int] = None,
        frame_count: Optional[int] = None,
        extension: Optional[str] = None,
        file_pattern: Optional[str] = None,
        proxy_path: Optional[str] = None,
        render_engine: Optional[str] = None,
        samples: Optional[int] = None,
        render_time_seconds: Optional[float] = None,
        resolution_x: Optional[int] = None,
        resolution_y: Optional[int] = None,
        is_current: bool = False,
    ) -> str:
        """
        Create a new render record.

        Args:
            shot_id: Parent shot UUID
            version: Version number (0 for current, 1+ for archives)
            folder_path: Path to render folder (current/ or _archive/vXXX/)
            frame_start: First frame number
            frame_end: Last frame number
            frame_count: Total frame count
            extension: File extension (.png, .exr)
            file_pattern: Frame file pattern (e.g., "shot_010_%04d.exr")
            proxy_path: Path to proxy MP4 if generated
            render_engine: Render engine name
            samples: Sample count
            render_time_seconds: Total render time
            resolution_x: Horizontal resolution
            resolution_y: Vertical resolution
            is_current: True if this is the active render

        Returns:
            UUID of created render
        """
        render_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # If this is marked as current, unmark other versions
            if is_current:
                cursor.execute(
                    'UPDATE renders SET is_current = 0 WHERE shot_id = ?',
                    (shot_id,)
                )

            cursor.execute('''
                INSERT INTO renders (
                    id, shot_id, version, folder_path,
                    frame_start, frame_end, frame_count,
                    extension, file_pattern,
                    proxy_path, proxy_generated_at,
                    render_engine, samples, render_time_seconds,
                    resolution_x, resolution_y,
                    is_current, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                render_id, shot_id, version, folder_path,
                frame_start, frame_end, frame_count,
                extension, file_pattern,
                proxy_path, now if proxy_path else None,
                render_engine, samples, render_time_seconds,
                resolution_x, resolution_y,
                1 if is_current else 0, now
            ))

        return render_id

    def get_by_id(self, render_id: str) -> Optional[Dict[str, Any]]:
        """
        Get render by ID.

        Args:
            render_id: Render UUID

        Returns:
            Render dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM renders WHERE id = ?', (render_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_folder_path(self, folder_path: str) -> Optional[Dict[str, Any]]:
        """
        Get render by folder path.

        Args:
            folder_path: Path to render folder

        Returns:
            Render dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM renders WHERE folder_path = ?', (folder_path,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_for_shot(self, shot_id: str) -> List[Dict[str, Any]]:
        """
        Get all renders for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            List of render dicts ordered by version (current first, then ascending)
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM renders
            WHERE shot_id = ?
            ORDER BY is_current DESC, version ASC
        ''', (shot_id,))

        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_current_for_shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current (active) render for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Current render dict or None
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM renders WHERE shot_id = ? AND is_current = 1',
            (shot_id,)
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_version(self, shot_id: str, version: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific version for a shot.

        Args:
            shot_id: Shot UUID
            version: Version number

        Returns:
            Render dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM renders WHERE shot_id = ? AND version = ?',
            (shot_id, version)
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def update(
        self,
        render_id: str,
        frame_start: Optional[int] = None,
        frame_end: Optional[int] = None,
        frame_count: Optional[int] = None,
        extension: Optional[str] = None,
        file_pattern: Optional[str] = None,
        proxy_path: Optional[str] = None,
        render_engine: Optional[str] = None,
        samples: Optional[int] = None,
        render_time_seconds: Optional[float] = None,
        resolution_x: Optional[int] = None,
        resolution_y: Optional[int] = None,
        is_current: Optional[bool] = None,
    ) -> bool:
        """
        Update a render record.

        Args:
            render_id: Render UUID
            Other args: Fields to update (None = no change)

        Returns:
            True if updated, False if not found
        """
        updates = []
        params = []

        if frame_start is not None:
            updates.append("frame_start = ?")
            params.append(frame_start)
        if frame_end is not None:
            updates.append("frame_end = ?")
            params.append(frame_end)
        if frame_count is not None:
            updates.append("frame_count = ?")
            params.append(frame_count)
        if extension is not None:
            updates.append("extension = ?")
            params.append(extension)
        if file_pattern is not None:
            updates.append("file_pattern = ?")
            params.append(file_pattern)
        if proxy_path is not None:
            updates.append("proxy_path = ?")
            params.append(proxy_path)
            updates.append("proxy_generated_at = ?")
            params.append(datetime.now().isoformat())
        if render_engine is not None:
            updates.append("render_engine = ?")
            params.append(render_engine)
        if samples is not None:
            updates.append("samples = ?")
            params.append(samples)
        if render_time_seconds is not None:
            updates.append("render_time_seconds = ?")
            params.append(render_time_seconds)
        if resolution_x is not None:
            updates.append("resolution_x = ?")
            params.append(resolution_x)
        if resolution_y is not None:
            updates.append("resolution_y = ?")
            params.append(resolution_y)
        if is_current is not None:
            updates.append("is_current = ?")
            params.append(1 if is_current else 0)

        if not updates:
            return False

        params.append(render_id)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # If setting as current, unmark other versions first
            if is_current:
                cursor.execute(
                    'SELECT shot_id FROM renders WHERE id = ?',
                    (render_id,)
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        'UPDATE renders SET is_current = 0 WHERE shot_id = ?',
                        (row[0],)
                    )

            cursor.execute(
                f'UPDATE renders SET {", ".join(updates)} WHERE id = ?',
                params
            )
            return cursor.rowcount > 0

    def upsert(
        self,
        shot_id: str,
        version: int,
        folder_path: str,
        **kwargs
    ) -> str:
        """
        Insert or update a render by folder_path.

        If a render with the given folder_path already exists, updates it.
        Otherwise, creates a new record.

        Args:
            shot_id: Parent shot UUID
            version: Version number
            folder_path: Path to render folder
            **kwargs: Additional fields to set

        Returns:
            UUID of created or updated render
        """
        existing = self.get_by_folder_path(folder_path)
        if existing:
            # Update existing record
            self.update(existing['id'], **kwargs)
            return existing['id']
        else:
            # Create new record
            return self.create(
                shot_id=shot_id,
                version=version,
                folder_path=folder_path,
                **kwargs
            )

    def delete(self, render_id: str) -> bool:
        """
        Delete a render record.

        Args:
            render_id: Render UUID

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM renders WHERE id = ?', (render_id,))
            return cursor.rowcount > 0

    def delete_for_shot(self, shot_id: str) -> int:
        """
        Delete all renders for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Number of renders deleted
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM renders WHERE shot_id = ?', (shot_id,))
            return cursor.rowcount

    def exists(self, folder_path: str) -> bool:
        """
        Check if render exists by folder path.

        Args:
            folder_path: Path to render folder

        Returns:
            True if exists
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM renders WHERE folder_path = ? LIMIT 1',
            (folder_path,)
        )
        return cursor.fetchone() is not None

    def count(self) -> int:
        """Get total render count."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM renders')
        return cursor.fetchone()[0]

    def count_for_shot(self, shot_id: str) -> int:
        """Get render count for a shot."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM renders WHERE shot_id = ?',
            (shot_id,)
        )
        return cursor.fetchone()[0]

    def get_highest_version(self, shot_id: str) -> int:
        """Get highest version number for a shot."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT MAX(version) FROM renders WHERE shot_id = ?',
            (shot_id,)
        )
        result = cursor.fetchone()[0]
        return result if result is not None else 0

    def get_renders_without_proxy(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get renders that don't have a proxy generated.

        Args:
            limit: Maximum number of results

        Returns:
            List of render dicts without proxies
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM renders
            WHERE proxy_path IS NULL
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit,))
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))


__all__ = ['RenderRepository']
