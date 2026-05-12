"""
ReferenceDatabase - Separate database for Analysis Mode annotations

This database stores annotations for reference videos in Analysis Mode,
keeping them completely separate from production notes.
"""

import sqlite3
import hashlib
import threading
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime


class ReferenceDatabase:
    """
    Manages the separate reference_notes.db database for Analysis Mode.

    Features:
    - Separate storage from production notes
    - Video ID generation from file path hash
    - Review sessions per video
    - Same API as NotesDatabase for consistency
    """

    SCHEMA_VERSION = 1
    DB_NAME = "reference_notes.db"

    @classmethod
    def get_base_path(cls) -> Path:
        """Get the base path for analysis mode storage."""
        return Path.home() / ".shot_library" / "analysis"

    @classmethod
    def get_db_path(cls) -> Path:
        """Get the database file path."""
        return cls.get_base_path() / cls.DB_NAME

    def __init__(self):
        self._connection: Optional[sqlite3.Connection] = None
        self._db_path: Optional[Path] = None

    def initialize(self) -> bool:
        """
        Initialize the reference database.

        Returns:
            True if successful
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Create base directory
            base_path = self.get_base_path()
            base_path.mkdir(parents=True, exist_ok=True)

            self._db_path = self.get_db_path()

            # Connect and create schema
            self._connection = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row

            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON")

            # Create schema
            self._create_schema()

            return True

        except Exception as e:
            logger.error(f"Reference database initialization failed: {e}")
            # Close connection if it was opened but schema creation failed
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None
            return False

    def _create_schema(self):
        """Create database schema if not exists."""
        cursor = self._connection.cursor()

        # Review sessions table (keyed by video_id instead of animation_uuid)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS review_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                video_path TEXT NOT NULL,
                video_name TEXT NOT NULL,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP,
                status TEXT DEFAULT 'active',
                UNIQUE(video_id)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ref_sessions_video_id
            ON review_sessions(video_id)
        ''')

        # Review notes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS review_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                frame INTEGER NOT NULL,
                note TEXT NOT NULL,
                author TEXT DEFAULT '',
                author_role TEXT DEFAULT 'artist',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_date TIMESTAMP,
                resolved INTEGER DEFAULT 0,
                resolved_by TEXT,
                resolved_date TIMESTAMP,
                deleted INTEGER DEFAULT 0,
                deleted_by TEXT,
                deleted_at TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES review_sessions(id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_notes_session ON review_notes(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_notes_frame ON review_notes(frame)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_notes_deleted ON review_notes(deleted)')

        # Drawover metadata table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS drawover_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                frame INTEGER NOT NULL,
                stroke_count INTEGER DEFAULT 0,
                authors TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_at TIMESTAMP,
                file_path TEXT,
                UNIQUE(video_id, frame)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ref_drawover_video_id
            ON drawover_metadata(video_id)
        ''')

        # Schema version table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
        ''')

        # Initialize version
        cursor.execute('SELECT version FROM schema_version')
        if cursor.fetchone() is None:
            cursor.execute('INSERT INTO schema_version (version) VALUES (?)', (self.SCHEMA_VERSION,))

        self._connection.commit()

    def close(self):
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

    # ==================== Studio Mode Compatibility ====================
    # Analysis Mode doesn't use studio mode, but these methods are needed
    # for compatibility with ReviewNotesManager and other shared components.

    def is_studio_mode(self) -> bool:
        """Analysis Mode doesn't use studio mode."""
        return False

    def get_current_user(self) -> str:
        """Get current user (empty in Analysis Mode)."""
        return ''

    def get_user(self, username: str) -> Optional[Dict]:
        """Get user info (returns None in Analysis Mode)."""
        return None

    def log_drawover_action(
        self,
        video_id: str,
        version_label: str,
        frame: int,
        action: str,
        actor: str = '',
        actor_role: str = ''
    ) -> None:
        """Log drawover action (no-op in Analysis Mode)."""
        pass

    # ==================== Video ID Generation ====================

    @staticmethod
    def get_video_id(video_path: str) -> str:
        """
        Generate stable identifier from video path.

        Uses file path hash so annotations persist even if file is renamed
        but path stays same. If file moves, annotations are "lost" but
        can be recovered by moving back.
        """
        normalized = str(Path(video_path).resolve())
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    # ==================== Session Methods ====================

    def get_or_create_session(self, video_path: str) -> int:
        """Get existing session or create new one for a video."""
        video_id = self.get_video_id(video_path)
        video_name = Path(video_path).stem

        cursor = self._connection.cursor()

        cursor.execute('''
            SELECT id FROM review_sessions
            WHERE video_id = ?
        ''', (video_id,))

        row = cursor.fetchone()
        if row:
            cursor.execute('''
                UPDATE review_sessions SET last_activity = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (row['id'],))
            self._connection.commit()
            return row['id']

        cursor.execute('''
            INSERT INTO review_sessions (video_id, video_path, video_name, last_activity)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (video_id, video_path, video_name))

        self._connection.commit()
        return cursor.lastrowid

    def get_session(self, video_path: str) -> Optional[Dict]:
        """Get session info if exists."""
        video_id = self.get_video_id(video_path)

        cursor = self._connection.cursor()
        cursor.execute('''
            SELECT * FROM review_sessions
            WHERE video_id = ?
        ''', (video_id,))

        row = cursor.fetchone()
        return dict(row) if row else None

    def get_session_by_id(self, video_id: str) -> Optional[Dict]:
        """Get session info by video_id directly."""
        cursor = self._connection.cursor()
        cursor.execute('''
            SELECT * FROM review_sessions
            WHERE video_id = ?
        ''', (video_id,))

        row = cursor.fetchone()
        return dict(row) if row else None

    def get_video_path_from_id(self, video_id: str) -> Optional[str]:
        """Get the video path associated with a video_id."""
        session = self.get_session_by_id(video_id)
        return session.get('video_path') if session else None

    # ==================== Note Methods ====================

    def get_notes_for_video(
        self,
        video_path: str,
        include_deleted: bool = False
    ) -> List[Dict]:
        """
        Get all notes for a specific video.

        Args:
            video_path: Path to the video file
            include_deleted: Include soft-deleted notes

        Returns:
            List of note dictionaries sorted by frame
        """
        video_id = self.get_video_id(video_path)

        cursor = self._connection.cursor()

        if include_deleted:
            cursor.execute('''
                SELECT n.* FROM review_notes n
                JOIN review_sessions s ON n.session_id = s.id
                WHERE s.video_id = ?
                ORDER BY n.frame ASC, n.created_date ASC
            ''', (video_id,))
        else:
            cursor.execute('''
                SELECT n.* FROM review_notes n
                JOIN review_sessions s ON n.session_id = s.id
                WHERE s.video_id = ?
                AND n.deleted = 0
                ORDER BY n.frame ASC, n.created_date ASC
            ''', (video_id,))

        return [dict(row) for row in cursor.fetchall()]

    def get_notes_for_version(
        self,
        video_id: str,
        version_label: str,
        include_deleted: bool = False
    ) -> List[Dict]:
        """
        Get all notes for a specific video by video_id.

        This method provides API compatibility with NotesDatabase.get_notes_for_version.
        In ReferenceDatabase, version_label is ignored (always treated as "reference").

        Args:
            video_id: The video ID (hash of video path)
            version_label: Ignored in ReferenceDatabase
            include_deleted: Include soft-deleted notes

        Returns:
            List of note dictionaries sorted by frame
        """
        cursor = self._connection.cursor()

        if include_deleted:
            cursor.execute('''
                SELECT n.* FROM review_notes n
                JOIN review_sessions s ON n.session_id = s.id
                WHERE s.video_id = ?
                ORDER BY n.frame ASC, n.created_date ASC
            ''', (video_id,))
        else:
            cursor.execute('''
                SELECT n.* FROM review_notes n
                JOIN review_sessions s ON n.session_id = s.id
                WHERE s.video_id = ?
                AND n.deleted = 0
                ORDER BY n.frame ASC, n.created_date ASC
            ''', (video_id,))

        return [dict(row) for row in cursor.fetchall()]

    def add_note(
        self,
        video_path_or_id: str,
        frame_or_version: any,
        note_or_frame: any = None,
        author_or_note: str = '',
        author_role: str = 'artist',
        **kwargs
    ) -> Optional[int]:
        """
        Add a new review note.

        Supports two signatures for compatibility:
        1. Original: add_note(video_path, frame, note, author, author_role)
        2. NotesDatabase-compatible: add_note(video_id, version_label, frame, note, author, author_role)
        """
        try:
            # Detect which signature is being used
            if isinstance(frame_or_version, int):
                # Original signature: (video_path, frame, note, author, author_role)
                video_path = video_path_or_id
                frame = frame_or_version
                note = note_or_frame if note_or_frame is not None else ''
                author = author_or_note
            else:
                # NotesDatabase signature: (video_id, version_label, frame, note, author, author_role)
                video_id = video_path_or_id
                # version_label is ignored in ReferenceDatabase
                frame = note_or_frame
                note = author_or_note
                author = kwargs.get('author', '')
                author_role = kwargs.get('author_role', 'artist')

                # Look up video_path from video_id
                video_path = self.get_video_path_from_id(video_id)
                if not video_path:
                    return None

            session_id = self.get_or_create_session(video_path)

            cursor = self._connection.cursor()
            cursor.execute('''
                INSERT INTO review_notes (session_id, frame, note, author, author_role)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, frame, note, author, author_role))

            note_id = cursor.lastrowid

            # Update session activity
            cursor.execute('''
                UPDATE review_sessions SET last_activity = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session_id,))

            self._connection.commit()
            return note_id

        except Exception as e:
            return None

    def update_note(
        self,
        note_id: int,
        note_text: str,
        actor: str = '',
        actor_role: str = ''
    ) -> bool:
        """Update note text."""
        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                UPDATE review_notes
                SET note = ?, modified_date = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (note_text, note_id))

            self._connection.commit()
            return cursor.rowcount > 0

        except Exception as e:
            return False

    def soft_delete_note(
        self,
        note_id: int,
        deleted_by: str = '',
        actor_role: str = ''
    ) -> bool:
        """Soft delete a note."""
        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                UPDATE review_notes
                SET deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP
                WHERE id = ? AND deleted = 0
            ''', (deleted_by, note_id))

            self._connection.commit()
            return cursor.rowcount > 0

        except Exception as e:
            return False

    def restore_note(
        self,
        note_id: int,
        restored_by: str = '',
        actor_role: str = ''
    ) -> bool:
        """Restore a soft-deleted note."""
        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                UPDATE review_notes
                SET deleted = 0, deleted_by = NULL, deleted_at = NULL
                WHERE id = ? AND deleted = 1
            ''', (note_id,))

            self._connection.commit()
            return cursor.rowcount > 0

        except Exception as e:
            return False

    def delete_note(self, note_id: int) -> bool:
        """Delete a note (uses soft delete)."""
        return self.soft_delete_note(note_id, '', '')

    def set_note_resolved(
        self,
        note_id: int,
        resolved: bool,
        resolved_by: str = '',
        actor_role: str = ''
    ) -> bool:
        """Set note resolved status."""
        try:
            cursor = self._connection.cursor()

            if resolved:
                cursor.execute('''
                    UPDATE review_notes
                    SET resolved = 1, resolved_by = ?, resolved_date = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (resolved_by, note_id))
            else:
                cursor.execute('''
                    UPDATE review_notes
                    SET resolved = 0, resolved_by = NULL, resolved_date = NULL
                    WHERE id = ?
                ''', (note_id,))

            self._connection.commit()
            return cursor.rowcount > 0

        except Exception as e:
            return False

    def get_note_by_id(self, note_id: int) -> Optional[Dict]:
        """Get a single note by ID."""
        cursor = self._connection.cursor()
        cursor.execute('SELECT * FROM review_notes WHERE id = ?', (note_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_unresolved_count(self, video_path: str) -> int:
        """Get unresolved comment count for a specific video."""
        video_id = self.get_video_id(video_path)

        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM review_sessions s
                JOIN review_notes n ON n.session_id = s.id
                WHERE s.video_id = ? AND n.deleted = 0 AND n.resolved = 0
            ''', (video_id,))
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    # ==================== Drawover Metadata ====================

    def update_drawover_metadata(
        self,
        video_path_or_id: str,
        frame_or_version: any,
        stroke_count_or_frame: any = None,
        authors_or_stroke_count: any = '',
        file_path_or_authors: str = '',
        file_path: str = ''
    ) -> bool:
        """
        Update or create drawover metadata entry.

        Supports two signatures for compatibility:
        1. Original: update_drawover_metadata(video_path, frame, stroke_count, authors, file_path)
        2. NotesDatabase-compatible: update_drawover_metadata(video_id, version_label, frame, stroke_count, authors, file_path)
        """
        # Detect which signature is being used
        if isinstance(frame_or_version, int):
            # Original signature: (video_path, frame, stroke_count, authors, file_path)
            video_id = self.get_video_id(video_path_or_id)
            frame = frame_or_version
            stroke_count = stroke_count_or_frame if stroke_count_or_frame is not None else 0
            authors = authors_or_stroke_count if isinstance(authors_or_stroke_count, str) else ''
            actual_file_path = file_path_or_authors
        else:
            # NotesDatabase signature: (video_id, version_label, frame, stroke_count, authors, file_path)
            # First arg is video_id, second is version_label (ignored)
            video_id = video_path_or_id
            frame = stroke_count_or_frame
            stroke_count = authors_or_stroke_count if isinstance(authors_or_stroke_count, int) else 0
            authors = file_path_or_authors
            actual_file_path = file_path

        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                INSERT INTO drawover_metadata
                    (video_id, frame, stroke_count, authors, file_path, modified_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id, frame)
                DO UPDATE SET
                    stroke_count = excluded.stroke_count,
                    authors = excluded.authors,
                    file_path = excluded.file_path,
                    modified_at = CURRENT_TIMESTAMP
            ''', (video_id, frame, stroke_count, authors, actual_file_path))
            self._connection.commit()
            return True
        except Exception as e:
            return False

    def get_drawover_metadata(
        self,
        video_path: str,
        frame: int
    ) -> Optional[Dict]:
        """Get drawover metadata for a specific frame."""
        video_id = self.get_video_id(video_path)

        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                SELECT * FROM drawover_metadata
                WHERE video_id = ? AND frame = ?
            ''', (video_id, frame))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def get_video_drawovers(
        self,
        video_path: str
    ) -> List[Dict]:
        """Get all drawover metadata for a video."""
        video_id = self.get_video_id(video_path)

        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                SELECT * FROM drawover_metadata
                WHERE video_id = ?
                ORDER BY frame ASC
            ''', (video_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def delete_drawover_metadata(
        self,
        video_path: str,
        frame: int
    ) -> bool:
        """Delete drawover metadata entry."""
        video_id = self.get_video_id(video_path)

        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                DELETE FROM drawover_metadata
                WHERE video_id = ? AND frame = ?
            ''', (video_id, frame))
            self._connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            return False

    # ==================== Studio Mode Compatibility ====================

    def is_studio_mode(self) -> bool:
        """Always return False - Analysis Mode doesn't use studio mode."""
        return False

    def get_current_user(self) -> str:
        """Return empty string - Analysis Mode doesn't track users."""
        return ''

    def get_show_deleted(self) -> bool:
        """Return False - Analysis Mode doesn't show deleted notes by default."""
        return False


# Singleton instance with thread safety
_reference_db_instance: Optional[ReferenceDatabase] = None
_reference_db_lock = threading.Lock()


def get_reference_database() -> ReferenceDatabase:
    """Get global ReferenceDatabase singleton instance (thread-safe)."""
    global _reference_db_instance
    if _reference_db_instance is None:
        with _reference_db_lock:
            # Double-check after acquiring lock
            if _reference_db_instance is None:
                _reference_db_instance = ReferenceDatabase()
                _reference_db_instance.initialize()
    return _reference_db_instance


__all__ = ['ReferenceDatabase', 'get_reference_database']
