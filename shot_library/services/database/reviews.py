"""
Review CRUD Operations

Database operations for reviews, comments, and annotations tables.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection


class ReviewRepository:
    """Repository for review database operations."""

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize repository.

        Args:
            connection: Database connection manager
        """
        self._conn = connection

    # ==================== REVIEWS ====================

    def create_review(
        self,
        shot_id: str,
        sidecar_path: str,
        playblast_id: Optional[str] = None,
    ) -> str:
        """
        Create a new review record.

        Args:
            shot_id: Parent shot UUID
            sidecar_path: Path to .shot_review.json sidecar file
            playblast_id: Optional playblast being reviewed

        Returns:
            UUID of created review
        """
        review_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO reviews (
                    id, shot_id, playblast_id, sidecar_path,
                    last_synced_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (review_id, shot_id, playblast_id, sidecar_path, now, now, now))

        return review_id

    def get_review_by_id(self, review_id: str) -> Optional[Dict[str, Any]]:
        """Get review by ID."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reviews WHERE id = ?', (review_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_review_for_shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """Get review for a shot."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM reviews WHERE shot_id = ? ORDER BY created_at DESC LIMIT 1',
            (shot_id,)
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def update_review_sync(self, review_id: str) -> bool:
        """Update last_synced_at timestamp."""
        now = datetime.now().isoformat()
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE reviews SET last_synced_at = ?, updated_at = ? WHERE id = ?',
                (now, now, review_id)
            )
            return cursor.rowcount > 0

    def delete_review(self, review_id: str) -> bool:
        """Delete a review (cascades to comments and annotations)."""
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM reviews WHERE id = ?', (review_id,))
            return cursor.rowcount > 0

    # ==================== COMMENTS ====================

    def create_comment(
        self,
        review_id: str,
        user_id: str,
        frame: int,
        content: str,
        timecode: Optional[str] = None,
    ) -> str:
        """
        Create a new comment.

        Args:
            review_id: Parent review UUID
            user_id: Author's user UUID
            frame: Frame number (0-indexed)
            content: Comment text
            timecode: Optional timecode string (HH:MM:SS:FF)

        Returns:
            UUID of created comment
        """
        comment_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO comments (
                    id, review_id, user_id, frame, timecode, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (comment_id, review_id, user_id, frame, timecode, content, now))

            # Update review's updated_at
            cursor.execute(
                'UPDATE reviews SET updated_at = ? WHERE id = ?',
                (now, review_id)
            )

        return comment_id

    def get_comment_by_id(self, comment_id: str) -> Optional[Dict[str, Any]]:
        """Get comment by ID."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM comments WHERE id = ?', (comment_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_comments_for_review(self, review_id: str) -> List[Dict[str, Any]]:
        """Get all comments for a review."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM comments WHERE review_id = ? ORDER BY frame ASC, created_at ASC',
            (review_id,)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_comments_at_frame(self, review_id: str, frame: int) -> List[Dict[str, Any]]:
        """Get comments at a specific frame."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM comments WHERE review_id = ? AND frame = ? ORDER BY created_at ASC',
            (review_id, frame)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_comments_by_user(self, review_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Get comments by a specific user."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM comments WHERE review_id = ? AND user_id = ? ORDER BY frame ASC',
            (review_id, user_id)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def update_comment(
        self,
        comment_id: str,
        content: Optional[str] = None,
        timecode: Optional[str] = None,
    ) -> bool:
        """Update a comment."""
        updates = []
        params = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if timecode is not None:
            updates.append("timecode = ?")
            params.append(timecode)

        if not updates:
            return False

        params.append(comment_id)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE comments SET {", ".join(updates)} WHERE id = ?',
                params
            )
            return cursor.rowcount > 0

    def delete_comment(self, comment_id: str) -> bool:
        """Delete a comment (cascades to annotations)."""
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
            return cursor.rowcount > 0

    # ==================== ANNOTATIONS ====================

    def create_annotation(
        self,
        comment_id: str,
        frame: int,
        data_json: str,
    ) -> str:
        """
        Create a new annotation.

        Args:
            comment_id: Parent comment UUID
            frame: Frame number
            data_json: Serialized drawing data (JSON)

        Returns:
            UUID of created annotation
        """
        annotation_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO annotations (id, comment_id, frame, data_json, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (annotation_id, comment_id, frame, data_json, now))

        return annotation_id

    def get_annotation_by_id(self, annotation_id: str) -> Optional[Dict[str, Any]]:
        """Get annotation by ID."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM annotations WHERE id = ?', (annotation_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_annotations_for_comment(self, comment_id: str) -> List[Dict[str, Any]]:
        """Get all annotations for a comment."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM annotations WHERE comment_id = ? ORDER BY created_at ASC',
            (comment_id,)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def delete_annotation(self, annotation_id: str) -> bool:
        """Delete an annotation."""
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM annotations WHERE id = ?', (annotation_id,))
            return cursor.rowcount > 0

    # ==================== HELPERS ====================

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))


__all__ = ['ReviewRepository']
