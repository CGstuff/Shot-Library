"""
Playblast CRUD Operations

Database operations for playblasts table.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection


class PlayblastRepository:
    """Repository for playblast database operations."""

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
        file_path: str,
        duration_ms: Optional[int] = None,
        fps: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        frame_count: Optional[int] = None,
        is_latest: bool = False,
        is_archived: bool = False,
    ) -> str:
        """
        Create a new playblast record.

        Args:
            shot_id: Parent shot UUID
            version: Version number (1, 2, 3...)
            file_path: Absolute path to MP4 file
            duration_ms: Video duration in milliseconds
            fps: Frames per second
            width: Video width in pixels
            height: Video height in pixels
            frame_count: Total frame count
            is_latest: True if this is the current version
            is_archived: True if moved to archive folder

        Returns:
            UUID of created playblast
        """
        playblast_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # If this is marked as latest, unmark other versions
            if is_latest:
                cursor.execute(
                    'UPDATE playblasts SET is_latest = 0 WHERE shot_id = ?',
                    (shot_id,)
                )

            cursor.execute('''
                INSERT INTO playblasts (
                    id, shot_id, version, file_path,
                    duration_ms, fps, width, height, frame_count,
                    is_latest, is_archived, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                playblast_id, shot_id, version, file_path,
                duration_ms, fps, width, height, frame_count,
                1 if is_latest else 0, 1 if is_archived else 0, now
            ))

        return playblast_id

    def get_by_id(self, playblast_id: str) -> Optional[Dict[str, Any]]:
        """
        Get playblast by ID.

        Args:
            playblast_id: Playblast UUID

        Returns:
            Playblast dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM playblasts WHERE id = ?', (playblast_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_file_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get playblast by file path.

        Args:
            file_path: Absolute path to MP4 file

        Returns:
            Playblast dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM playblasts WHERE file_path = ?', (file_path,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_for_shot(self, shot_id: str) -> List[Dict[str, Any]]:
        """
        Get all playblasts for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            List of playblast dicts ordered by version descending
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            'SELECT * FROM playblasts WHERE shot_id = ? ORDER BY version DESC',
            (shot_id,)
        )

        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_latest_for_shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest playblast for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Latest playblast dict or None
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM playblasts WHERE shot_id = ? AND is_latest = 1',
            (shot_id,)
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)

        # Fallback to highest version if no explicit latest
        cursor.execute(
            'SELECT * FROM playblasts WHERE shot_id = ? ORDER BY version DESC LIMIT 1',
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
            Playblast dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM playblasts WHERE shot_id = ? AND version = ?',
            (shot_id, version)
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def update(
        self,
        playblast_id: str,
        duration_ms: Optional[int] = None,
        fps: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        frame_count: Optional[int] = None,
        is_latest: Optional[bool] = None,
        is_archived: Optional[bool] = None,
    ) -> bool:
        """
        Update a playblast record.

        Args:
            playblast_id: Playblast UUID
            Other args: Fields to update (None = no change)

        Returns:
            True if updated, False if not found
        """
        updates = []
        params = []

        if duration_ms is not None:
            updates.append("duration_ms = ?")
            params.append(duration_ms)
        if fps is not None:
            updates.append("fps = ?")
            params.append(fps)
        if width is not None:
            updates.append("width = ?")
            params.append(width)
        if height is not None:
            updates.append("height = ?")
            params.append(height)
        if frame_count is not None:
            updates.append("frame_count = ?")
            params.append(frame_count)
        if is_latest is not None:
            updates.append("is_latest = ?")
            params.append(1 if is_latest else 0)
        if is_archived is not None:
            updates.append("is_archived = ?")
            params.append(1 if is_archived else 0)

        if not updates:
            return False

        params.append(playblast_id)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # If setting as latest, unmark other versions first
            if is_latest:
                # Get shot_id first
                cursor.execute(
                    'SELECT shot_id FROM playblasts WHERE id = ?',
                    (playblast_id,)
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        'UPDATE playblasts SET is_latest = 0 WHERE shot_id = ?',
                        (row[0],)
                    )

            cursor.execute(
                f'UPDATE playblasts SET {", ".join(updates)} WHERE id = ?',
                params
            )
            return cursor.rowcount > 0

    def upsert(
        self,
        shot_id: str,
        version: int,
        file_path: str,
        duration_ms: Optional[int] = None,
        fps: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        frame_count: Optional[int] = None,
        is_latest: bool = False,
        is_archived: bool = False,
    ) -> str:
        """
        Insert or update a playblast by file_path.

        If a playblast with the given file_path already exists, updates it.
        Otherwise, creates a new record.

        Args:
            shot_id: Parent shot UUID
            version: Version number (1, 2, 3...)
            file_path: Absolute path to MP4 file
            duration_ms: Video duration in milliseconds
            fps: Frames per second
            width: Video width in pixels
            height: Video height in pixels
            frame_count: Total frame count
            is_latest: True if this is the current version
            is_archived: True if moved to archive folder

        Returns:
            UUID of created or updated playblast
        """
        existing = self.get_by_file_path(file_path)
        if existing:
            # Update existing record
            self.update(
                existing['id'],
                duration_ms=duration_ms,
                fps=fps,
                width=width,
                height=height,
                frame_count=frame_count,
                is_latest=is_latest,
                is_archived=is_archived,
            )
            return existing['id']
        else:
            # Create new record
            return self.create(
                shot_id=shot_id,
                version=version,
                file_path=file_path,
                duration_ms=duration_ms,
                fps=fps,
                width=width,
                height=height,
                frame_count=frame_count,
                is_latest=is_latest,
                is_archived=is_archived,
            )

    def delete(self, playblast_id: str) -> bool:
        """
        Delete a playblast record.

        Args:
            playblast_id: Playblast UUID

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM playblasts WHERE id = ?', (playblast_id,))
            return cursor.rowcount > 0

    def delete_for_shot(self, shot_id: str) -> int:
        """
        Delete all playblasts for a shot.

        Args:
            shot_id: Shot UUID

        Returns:
            Number of playblasts deleted
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM playblasts WHERE shot_id = ?', (shot_id,))
            return cursor.rowcount

    def exists(self, file_path: str) -> bool:
        """
        Check if playblast exists by file path.

        Args:
            file_path: Absolute path to MP4 file

        Returns:
            True if exists
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM playblasts WHERE file_path = ? LIMIT 1',
            (file_path,)
        )
        return cursor.fetchone() is not None

    def count(self) -> int:
        """Get total playblast count."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM playblasts')
        return cursor.fetchone()[0]

    def count_for_shot(self, shot_id: str) -> int:
        """Get playblast count for a shot."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM playblasts WHERE shot_id = ?',
            (shot_id,)
        )
        return cursor.fetchone()[0]

    def get_highest_version(self, shot_id: str) -> int:
        """Get highest version number for a shot."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT MAX(version) FROM playblasts WHERE shot_id = ?',
            (shot_id,)
        )
        result = cursor.fetchone()[0]
        return result if result is not None else 0

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))


__all__ = ['PlayblastRepository']
