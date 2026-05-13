"""
Shot CRUD Operations

Database operations for shots table.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection

logger = logging.getLogger(__name__)


class ShotRepository:
    """Repository for shot database operations."""

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize repository.

        Args:
            connection: Database connection manager
        """
        self._conn = connection

    def create(
        self,
        folder_path: str,
        blend_file: str,
        shot_name: str,
        editorial_order: str,
        sequence_num: Optional[int] = None,
        scene_num: Optional[int] = None,
        shot_num: Optional[int] = None,
        episode_num: Optional[int] = None,
        status: str = "WIP",
        parse_warning: Optional[str] = None,
        base_shot_name: Optional[str] = None,
        shot_version: Optional[int] = None,
        version_group_id: Optional[str] = None,
        is_latest_shot_version: bool = True,
        display_mode: str = "playblast",
        shot_role: str = "standalone",
        master_shot_id: Optional[str] = None,
        view_name: Optional[str] = None,
        frame_in: Optional[int] = None,
        frame_out: Optional[int] = None,
        description: str = "",
        priority: int = 2,
    ) -> str:
        """
        Create a new shot record.

        Args:
            folder_path: Absolute path to shot folder
            blend_file: Path to primary .blend file
            shot_name: Display name for the shot
            editorial_order: Sort key (format: "EEEE.SSSS.CCCC.HHHH")
            sequence_num: Parsed sequence number
            scene_num: Parsed scene number
            shot_num: Parsed shot number
            episode_num: Parsed episode number
            status: Production status (WIP, In Review, Approved, Final, Blocked)
            parse_warning: Warning message if parsing failed
            base_shot_name: Base name without version suffix
            shot_version: Parsed version number
            version_group_id: UUID for grouping related versions
            is_latest_shot_version: True if latest in version group
            display_mode: Preview mode ('playblast', 'lookdev', or 'render')
            shot_role: 'standalone', 'master', or 'view'
            master_shot_id: For view shots, references the master shot
            view_name: For view shots, short suffix (e.g., 'cam01', 'ref02')
            frame_in: First frame of shot (v12)
            frame_out: Last frame of shot (v12)
            description: Free-form shot notes (v12)
            priority: 1=Low, 2=Normal, 3=High, 4=Critical (v12)

        Returns:
            UUID of created shot
        """
        shot_id = str(uuid4())
        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO shots (
                    id, folder_path, blend_file, shot_name,
                    sequence_num, scene_num, shot_num, episode_num,
                    editorial_order, status, parse_warning,
                    base_shot_name, shot_version, version_group_id, is_latest_shot_version,
                    display_mode, shot_role, master_shot_id, view_name,
                    frame_in, frame_out, description, priority,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                shot_id, folder_path, blend_file, shot_name,
                sequence_num, scene_num, shot_num, episode_num,
                editorial_order, status, parse_warning,
                base_shot_name, shot_version, version_group_id, 1 if is_latest_shot_version else 0,
                display_mode, shot_role, master_shot_id, view_name,
                frame_in, frame_out, description, priority,
                now, now
            ))

        return shot_id

    def get_by_id(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get shot by ID.

        Args:
            shot_id: Shot UUID

        Returns:
            Shot dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM shots WHERE id = ?', (shot_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_folder_path(self, folder_path: str) -> Optional[Dict[str, Any]]:
        """
        Get shot by folder path (returns first match).

        Note: With multi-version support, multiple shots can share the same folder.
        Use get_by_blend_file() for unique lookup, or get_all_by_folder_path()
        to get all shots in a folder.

        Args:
            folder_path: Absolute path to shot folder

        Returns:
            Shot dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM shots WHERE folder_path = ? LIMIT 1', (folder_path,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_by_blend_file(self, blend_file: str) -> Optional[Dict[str, Any]]:
        """
        Get shot by blend file path (unique lookup).

        Args:
            blend_file: Absolute path to .blend file

        Returns:
            Shot dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM shots WHERE blend_file = ?', (blend_file,))
        row = cursor.fetchone()

        if row:
            return self._row_to_dict(cursor, row)
        return None

    def get_all_by_folder_path(self, folder_path: str) -> List[Dict[str, Any]]:
        """
        Get all shots in a folder.

        Args:
            folder_path: Absolute path to shot folder

        Returns:
            List of shot dicts ordered by shot_version descending
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE folder_path = ?
               ORDER BY shot_version DESC NULLS LAST''',
            (folder_path,)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_all(self, order_by_editorial: bool = True) -> List[Dict[str, Any]]:
        """
        Get all shots.

        Args:
            order_by_editorial: If True, order by editorial_order

        Returns:
            List of shot dicts
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        order_clause = "ORDER BY editorial_order ASC" if order_by_editorial else ""
        cursor.execute(f'SELECT * FROM shots {order_clause}')

        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        Get shots by status.

        Args:
            status: Status to filter by

        Returns:
            List of shot dicts
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM shots WHERE status = ? ORDER BY editorial_order ASC',
            (status,)
        )

        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def update(
        self,
        shot_id: str,
        blend_file: Optional[str] = None,
        shot_name: Optional[str] = None,
        editorial_order: Optional[str] = None,
        sequence_num: Optional[int] = None,
        scene_num: Optional[int] = None,
        shot_num: Optional[int] = None,
        episode_num: Optional[int] = None,
        status: Optional[str] = None,
        parse_warning: Optional[str] = None,
        base_shot_name: Optional[str] = None,
        shot_version: Optional[int] = None,
        version_group_id: Optional[str] = None,
        is_latest_shot_version: Optional[bool] = None,
        display_mode: Optional[str] = None,
        shot_role: Optional[str] = None,
        master_shot_id: Optional[str] = None,
        view_name: Optional[str] = None,
        frame_in: Optional[int] = None,
        frame_out: Optional[int] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> bool:
        """
        Update a shot record.

        Args:
            shot_id: Shot UUID
            Other args: Fields to update (None = no change)

        Returns:
            True if updated, False if not found
        """
        updates = []
        params = []

        if blend_file is not None:
            updates.append("blend_file = ?")
            params.append(blend_file)
        if shot_name is not None:
            updates.append("shot_name = ?")
            params.append(shot_name)
        if editorial_order is not None:
            updates.append("editorial_order = ?")
            params.append(editorial_order)
        if sequence_num is not None:
            updates.append("sequence_num = ?")
            params.append(sequence_num)
        if scene_num is not None:
            updates.append("scene_num = ?")
            params.append(scene_num)
        if shot_num is not None:
            updates.append("shot_num = ?")
            params.append(shot_num)
        if episode_num is not None:
            updates.append("episode_num = ?")
            params.append(episode_num)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if parse_warning is not None:
            updates.append("parse_warning = ?")
            params.append(parse_warning)
        if base_shot_name is not None:
            updates.append("base_shot_name = ?")
            params.append(base_shot_name)
        if shot_version is not None:
            updates.append("shot_version = ?")
            params.append(shot_version)
        if version_group_id is not None:
            updates.append("version_group_id = ?")
            params.append(version_group_id)
        if is_latest_shot_version is not None:
            updates.append("is_latest_shot_version = ?")
            params.append(1 if is_latest_shot_version else 0)
        if display_mode is not None:
            updates.append("display_mode = ?")
            params.append(display_mode)
        if shot_role is not None:
            updates.append("shot_role = ?")
            params.append(shot_role)
        if master_shot_id is not None:
            updates.append("master_shot_id = ?")
            params.append(master_shot_id)
        if view_name is not None:
            updates.append("view_name = ?")
            params.append(view_name)
        if frame_in is not None:
            updates.append("frame_in = ?")
            params.append(frame_in)
        if frame_out is not None:
            updates.append("frame_out = ?")
            params.append(frame_out)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(shot_id)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE shots SET {", ".join(updates)} WHERE id = ?',
                params
            )
            return cursor.rowcount > 0

    def upsert(
        self,
        shot_id: str,
        folder_path: str,
        blend_file: str,
        shot_name: str,
        editorial_order: str,
        sequence_num: Optional[int] = None,
        scene_num: Optional[int] = None,
        shot_num: Optional[int] = None,
        episode_num: Optional[int] = None,
        status: str = "WIP",
        parse_warning: Optional[str] = None,
        base_shot_name: Optional[str] = None,
        shot_version: Optional[int] = None,
        version_group_id: Optional[str] = None,
        is_latest_shot_version: bool = True,
        display_mode: str = "playblast",
        shot_role: str = "standalone",
        master_shot_id: Optional[str] = None,
        view_name: Optional[str] = None,
        frame_in: Optional[int] = None,
        frame_out: Optional[int] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> str:
        """
        Insert or update a shot by ID.

        Unlike create(), this accepts a specific shot_id to use.
        If a shot with that ID exists, it updates it.
        Otherwise, creates a new record with that ID.

        Args:
            shot_id: Specific UUID to use for the shot
            folder_path: Absolute path to shot folder
            blend_file: Path to primary .blend file
            shot_name: Display name for the shot
            editorial_order: Sort key (format: "EEEE.SSSS.CCCC.HHHH")
            sequence_num: Parsed sequence number
            scene_num: Parsed scene number
            shot_num: Parsed shot number
            episode_num: Parsed episode number
            status: Production status (WIP, In Review, Approved, Final, Blocked)
            parse_warning: Warning message if parsing failed
            base_shot_name: Base name without version suffix
            shot_version: Parsed version number
            version_group_id: UUID for grouping related versions
            is_latest_shot_version: True if latest in version group
            display_mode: Preview mode ('playblast', 'lookdev', or 'render')
            shot_role: 'standalone', 'master', or 'view'
            master_shot_id: For view shots, references the master shot
            view_name: For view shots, short suffix (e.g., 'cam01', 'ref02')

        Returns:
            UUID of created/updated shot
        """
        existing = self.get_by_id(shot_id)
        if existing:
            # Update existing record
            self.update(
                shot_id,
                blend_file=blend_file,
                shot_name=shot_name,
                editorial_order=editorial_order,
                sequence_num=sequence_num,
                scene_num=scene_num,
                shot_num=shot_num,
                episode_num=episode_num,
                status=status,
                parse_warning=parse_warning,
                base_shot_name=base_shot_name,
                shot_version=shot_version,
                version_group_id=version_group_id,
                is_latest_shot_version=is_latest_shot_version,
                display_mode=display_mode,
                shot_role=shot_role,
                master_shot_id=master_shot_id,
                view_name=view_name,
                frame_in=frame_in,
                frame_out=frame_out,
                description=description,
                priority=priority,
            )
            return shot_id
        else:
            # Create new record with specific ID. New shots take sane defaults
            # for the v12 metadata fields when the caller didn't specify them.
            now = datetime.now().isoformat()
            new_description = "" if description is None else description
            new_priority = 2 if priority is None else priority

            with self._conn.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO shots (
                        id, folder_path, blend_file, shot_name,
                        sequence_num, scene_num, shot_num, episode_num,
                        editorial_order, status, parse_warning,
                        base_shot_name, shot_version, version_group_id, is_latest_shot_version,
                        display_mode, shot_role, master_shot_id, view_name,
                        frame_in, frame_out, description, priority,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    shot_id, folder_path, blend_file, shot_name,
                    sequence_num, scene_num, shot_num, episode_num,
                    editorial_order, status, parse_warning,
                    base_shot_name, shot_version, version_group_id, 1 if is_latest_shot_version else 0,
                    display_mode, shot_role, master_shot_id, view_name,
                    frame_in, frame_out, new_description, new_priority,
                    now, now
                ))

            return shot_id

    def bulk_set_priority(self, shot_ids: List[str], priority: int) -> int:
        """Set the same priority on many shots in one transaction.

        Returns the number of rows updated.
        """
        if not shot_ids:
            return 0
        now = datetime.now().isoformat()
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' for _ in shot_ids)
            cursor.execute(
                f"UPDATE shots SET priority = ?, updated_at = ? WHERE id IN ({placeholders})",
                [priority, now, *shot_ids],
            )
            return cursor.rowcount

    def delete(self, shot_id: str) -> bool:
        """
        Delete a shot record.

        Args:
            shot_id: Shot UUID

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM shots WHERE id = ?', (shot_id,))
            return cursor.rowcount > 0

    def delete_by_folder_path(self, folder_path: str) -> int:
        """
        Delete all shots in a folder.

        Args:
            folder_path: Absolute path to shot folder

        Returns:
            Number of shots deleted
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM shots WHERE folder_path = ?', (folder_path,))
            return cursor.rowcount

    def delete_by_blend_file(self, blend_file: str) -> bool:
        """
        Delete a shot by blend file path.

        Args:
            blend_file: Absolute path to .blend file

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM shots WHERE blend_file = ?', (blend_file,))
            return cursor.rowcount > 0

    def exists(self, folder_path: str) -> bool:
        """
        Check if any shot exists in folder path.

        Args:
            folder_path: Absolute path to shot folder

        Returns:
            True if any shot exists in folder
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM shots WHERE folder_path = ? LIMIT 1',
            (folder_path,)
        )
        return cursor.fetchone() is not None

    def exists_blend_file(self, blend_file: str) -> bool:
        """
        Check if shot exists by blend file path (unique check).

        Args:
            blend_file: Absolute path to .blend file

        Returns:
            True if exists
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM shots WHERE blend_file = ? LIMIT 1',
            (blend_file,)
        )
        return cursor.fetchone() is not None

    def count(self) -> int:
        """Get total shot count."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM shots')
        return cursor.fetchone()[0]

    def count_by_status(self) -> Dict[str, int]:
        """Get shot count by status."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT status, COUNT(*) FROM shots GROUP BY status')

        result = {}
        for row in cursor.fetchall():
            result[row[0]] = row[1]
        return result

    def get_all_folder_paths(self) -> List[str]:
        """Get all shot folder paths."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT folder_path FROM shots')
        return [row[0] for row in cursor.fetchall()]

    def get_shots_by_version_group(self, version_group_id: str) -> List[Dict[str, Any]]:
        """
        Get all shots in a version group.

        Args:
            version_group_id: UUID of the version group

        Returns:
            List of shot dicts ordered by version descending
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE version_group_id = ?
               ORDER BY shot_version DESC NULLS LAST''',
            (version_group_id,)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_shots_by_base_name(self, base_shot_name: str) -> List[Dict[str, Any]]:
        """
        Get all shots with the same base shot name.

        This is a fallback for finding related shot versions when
        version_group_id may not be set consistently.

        Args:
            base_shot_name: Base name without version suffix (e.g., "SH0010")

        Returns:
            List of shot dicts ordered by version descending
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE base_shot_name = ?
               ORDER BY shot_version DESC NULLS LAST''',
            (base_shot_name,)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_latest_shots_only(self) -> List[Dict[str, Any]]:
        """
        Get only latest versions of all shots.

        Returns:
            List of shot dicts where is_latest_shot_version=1,
            ordered by editorial_order
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE is_latest_shot_version = 1
               ORDER BY editorial_order ASC'''
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def update_latest_flags(self, version_group_id: str, latest_shot_id: str) -> bool:
        """
        Update is_latest_shot_version flags for a version group.

        Sets all shots in the group to is_latest=0 except the specified one.

        Args:
            version_group_id: UUID of the version group
            latest_shot_id: ID of the shot to mark as latest

        Returns:
            True if any rows were updated
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            # Reset all in group to not latest
            cursor.execute(
                '''UPDATE shots
                   SET is_latest_shot_version = 0, updated_at = ?
                   WHERE version_group_id = ?''',
                (datetime.now().isoformat(), version_group_id)
            )
            # Mark the specified shot as latest
            cursor.execute(
                '''UPDATE shots
                   SET is_latest_shot_version = 1, updated_at = ?
                   WHERE id = ?''',
                (datetime.now().isoformat(), latest_shot_id)
            )
            return cursor.rowcount > 0

    def get_version_group_count(self, version_group_id: str) -> int:
        """
        Get count of shots in a version group.

        Args:
            version_group_id: UUID of the version group

        Returns:
            Number of shots in the group
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM shots WHERE version_group_id = ?',
            (version_group_id,)
        )
        return cursor.fetchone()[0]

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

    # ==================== MULTI-CAMERA REFERENCE METHODS ====================

    def get_views_for_master(self, master_shot_id: str) -> List[Dict[str, Any]]:
        """
        Get all view shots attached to a master shot.

        Args:
            master_shot_id: UUID of the master shot

        Returns:
            List of view shot dicts ordered by shot_name
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE master_shot_id = ?
               ORDER BY shot_name ASC''',
            (master_shot_id,)
        )
        results = [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        return results

    def get_master_for_view(self, view_shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the master shot for a view shot.

        Args:
            view_shot_id: UUID of the view shot

        Returns:
            Master shot dict or None if not found
        """
        # First get the view shot to find its master_shot_id
        view_shot = self.get_by_id(view_shot_id)
        if not view_shot or not view_shot.get('master_shot_id'):
            return None

        return self.get_by_id(view_shot['master_shot_id'])

    def get_view_count(self, master_shot_id: str) -> int:
        """
        Get count of views attached to a master shot.

        Args:
            master_shot_id: UUID of the master shot

        Returns:
            Number of view shots
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM shots WHERE master_shot_id = ?',
            (master_shot_id,)
        )
        return cursor.fetchone()[0]

    def get_standalone_and_masters(self) -> List[Dict[str, Any]]:
        """
        Get all standalone and master shots (excludes view shots).

        This is used for the main grid view which shows only
        standalone and master shots, not individual views.

        Returns:
            List of shot dicts ordered by editorial_order
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE shot_role IN ('standalone', 'master')
               ORDER BY editorial_order ASC'''
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_by_role(self, shot_role: str) -> List[Dict[str, Any]]:
        """
        Get shots by role.

        Args:
            shot_role: 'standalone', 'master', or 'view'

        Returns:
            List of shot dicts ordered by editorial_order
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE shot_role = ?
               ORDER BY editorial_order ASC''',
            (shot_role,)
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def get_orphaned_views(self) -> List[Dict[str, Any]]:
        """
        Get view shots that have no master (orphaned).

        This can happen if the master shot file is deleted.

        Returns:
            List of orphaned view shot dicts
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT * FROM shots
               WHERE shot_role = 'view'
               AND (master_shot_id IS NULL OR master_shot_id NOT IN (SELECT id FROM shots))
               ORDER BY editorial_order ASC'''
        )
        return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def set_as_master(self, shot_id: str) -> bool:
        """
        Set a shot as a master (has view attachments).

        Args:
            shot_id: Shot UUID

        Returns:
            True if updated
        """
        return self.update(shot_id, shot_role='master')

    def set_as_view(self, shot_id: str, master_shot_id: str) -> bool:
        """
        Set a shot as a view of a master.

        Args:
            shot_id: Shot UUID
            master_shot_id: Master shot UUID

        Returns:
            True if updated successfully, False otherwise
        """
        if not shot_id or not master_shot_id:
            return False

        try:
            with self._conn.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''UPDATE shots
                       SET shot_role = 'view', master_shot_id = ?, updated_at = ?
                       WHERE id = ?''',
                    (master_shot_id, datetime.now().isoformat(), shot_id)
                )
                updated = cursor.rowcount > 0
                return updated
        except Exception:
            logger.warning(
                "set_as_view failed for shot_id=%s master_shot_id=%s",
                shot_id, master_shot_id, exc_info=True,
            )
            return False

    def clear_master_view_relationship(self, shot_id: str) -> bool:
        """
        Clear master/view relationship, resetting shot to standalone.

        Args:
            shot_id: Shot UUID

        Returns:
            True if updated
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''UPDATE shots
                   SET shot_role = 'standalone', master_shot_id = NULL, updated_at = ?
                   WHERE id = ?''',
                (datetime.now().isoformat(), shot_id)
            )
            return cursor.rowcount > 0


__all__ = ['ShotRepository']
