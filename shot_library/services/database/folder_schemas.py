"""
Folder Schemas Database Operations

CRUD operations for folder schema configurations.
Folder schemas define how studio folder structures map to shots.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection


class FolderSchemaRepository:
    """
    Repository for folder schema database operations.

    Provides:
    - Create, read, update, delete operations
    - Active schema management
    - Import/export to JSON files
    """

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize repository.

        Args:
            connection: Database connection manager
        """
        self._conn = connection

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all folder schemas.

        Returns:
            List of schema dicts with id, name, config, is_active, timestamps
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, config_json, is_active, created_at, updated_at
            FROM folder_schemas
            ORDER BY is_active DESC, name ASC
        ''')

        rows = cursor.fetchall()

        return [
            {
                'id': row['id'],
                'name': row['name'],
                'config': json.loads(row['config_json']),
                'is_active': bool(row['is_active']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }
            for row in rows
        ]

    def get_by_id(self, schema_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a folder schema by ID.

        Args:
            schema_id: Schema UUID

        Returns:
            Schema dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, config_json, is_active, created_at, updated_at
            FROM folder_schemas
            WHERE id = ?
        ''', (schema_id,))

        row = cursor.fetchone()

        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'config': json.loads(row['config_json']),
                'is_active': bool(row['is_active']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }

        return None

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a folder schema by name.

        Args:
            name: Schema name

        Returns:
            Schema dict or None if not found
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, config_json, is_active, created_at, updated_at
            FROM folder_schemas
            WHERE name = ?
        ''', (name,))

        row = cursor.fetchone()

        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'config': json.loads(row['config_json']),
                'is_active': bool(row['is_active']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }

        return None

    def get_active(self) -> Optional[Dict[str, Any]]:
        """
        Get the currently active folder schema.

        Returns:
            Active schema dict or None if none active
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, config_json, is_active, created_at, updated_at
            FROM folder_schemas
            WHERE is_active = 1
            LIMIT 1
        ''')

        row = cursor.fetchone()

        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'config': json.loads(row['config_json']),
                'is_active': True,
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }

        return None

    def create(self, name: str, config: Dict[str, Any], is_active: bool = False) -> str:
        """
        Create a new folder schema.

        Args:
            name: Schema name (must be unique)
            config: Schema configuration dict
            is_active: Whether to set as active schema

        Returns:
            New schema ID

        Raises:
            ValueError: If name already exists
        """
        # Check for duplicate name
        existing = self.get_by_name(name)
        if existing:
            raise ValueError(f"Schema with name '{name}' already exists")

        schema_id = str(uuid4())
        now = datetime.now().isoformat()
        config_json = json.dumps(config, indent=2)

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # If setting as active, deactivate others first
            if is_active:
                cursor.execute('UPDATE folder_schemas SET is_active = 0')

            cursor.execute('''
                INSERT INTO folder_schemas (id, name, config_json, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (schema_id, name, config_json, 1 if is_active else 0, now, now))

        return schema_id

    def update(self, schema_id: str, name: Optional[str] = None,
               config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update a folder schema.

        Args:
            schema_id: Schema ID to update
            name: New name (optional)
            config: New configuration (optional)

        Returns:
            True if updated, False if not found

        Raises:
            ValueError: If new name already exists
        """
        existing = self.get_by_id(schema_id)
        if not existing:
            return False

        # Check for duplicate name if changing
        if name and name != existing['name']:
            if self.get_by_name(name):
                raise ValueError(f"Schema with name '{name}' already exists")

        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            if name and config:
                config_json = json.dumps(config, indent=2)
                cursor.execute('''
                    UPDATE folder_schemas
                    SET name = ?, config_json = ?, updated_at = ?
                    WHERE id = ?
                ''', (name, config_json, now, schema_id))
            elif name:
                cursor.execute('''
                    UPDATE folder_schemas
                    SET name = ?, updated_at = ?
                    WHERE id = ?
                ''', (name, now, schema_id))
            elif config:
                config_json = json.dumps(config, indent=2)
                cursor.execute('''
                    UPDATE folder_schemas
                    SET config_json = ?, updated_at = ?
                    WHERE id = ?
                ''', (config_json, now, schema_id))
            else:
                return False

        return True

    def delete(self, schema_id: str) -> bool:
        """
        Delete a folder schema.

        Args:
            schema_id: Schema ID to delete

        Returns:
            True if deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            cursor.execute('DELETE FROM folder_schemas WHERE id = ?', (schema_id,))
            deleted = cursor.rowcount > 0

        return deleted

    def set_active(self, schema_id: str) -> bool:
        """
        Set a schema as the active schema.

        Deactivates all other schemas and activates the specified one.

        Args:
            schema_id: Schema ID to activate

        Returns:
            True if activated, False if not found
        """
        existing = self.get_by_id(schema_id)
        if not existing:
            return False

        now = datetime.now().isoformat()

        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # Deactivate all schemas
            cursor.execute('UPDATE folder_schemas SET is_active = 0')

            # Activate the specified schema
            cursor.execute('''
                UPDATE folder_schemas
                SET is_active = 1, updated_at = ?
                WHERE id = ?
            ''', (now, schema_id))

        return True

    def deactivate_all(self) -> None:
        """Deactivate all schemas."""
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE folder_schemas SET is_active = 0')

    def export_to_file(self, schema_id: str, file_path: Path) -> bool:
        """
        Export a schema to a JSON file.

        Args:
            schema_id: Schema ID to export
            file_path: Destination file path

        Returns:
            True if exported successfully, False if not found
        """
        schema = self.get_by_id(schema_id)
        if not schema:
            return False

        # Create export format
        export_data = {
            'name': schema['name'],
            'hierarchy_levels': schema['config'].get('hierarchy_levels', []),
            'blend_file_patterns': schema['config'].get('blend_file_patterns', []),
            'playblast_folder': schema['config'].get('playblast_folder', 'PlayBlast'),
            'playblast_pattern': schema['config'].get('playblast_pattern', r'^v(?P<version>\d{3})\.mp4$'),
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2)

        return True

    def import_from_file(self, file_path: Path, is_active: bool = False) -> str:
        """
        Import a schema from a JSON file.

        Args:
            file_path: Source file path
            is_active: Whether to set as active schema

        Returns:
            New schema ID

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is invalid or schema name exists
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Schema file not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate required fields
        name = data.get('name')
        if not name:
            raise ValueError("Schema file missing 'name' field")

        hierarchy_levels = data.get('hierarchy_levels', [])
        if not hierarchy_levels:
            raise ValueError("Schema file missing 'hierarchy_levels' field")

        # Build config
        config = {
            'name': name,
            'hierarchy_levels': hierarchy_levels,
            'blend_file_patterns': data.get('blend_file_patterns', [r'^(?P<shot>[\w]+)\.blend$']),
            'playblast_folder': data.get('playblast_folder', 'PlayBlast'),
            'playblast_pattern': data.get('playblast_pattern', r'^v(?P<version>\d{3})\.mp4$'),
        }

        return self.create(name, config, is_active)

    def get_count(self) -> int:
        """
        Get total number of schemas.

        Returns:
            Schema count
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM folder_schemas')
        result = cursor.fetchone()

        return result[0] if result else 0


__all__ = ['FolderSchemaRepository']
