"""
Database Schema - Schema initialization for Shot Library

Manages database schema for shot production visibility.
Forked from Action Library and adapted for shot domain.
"""

import logging
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from .connection import DatabaseConnection

logger = logging.getLogger(__name__)


# Current schema version - starts fresh for Shot Library
SCHEMA_VERSION = 11

# Feature descriptions for each version
VERSION_FEATURES: Dict[int, List[str]] = {
    1: [
        "Shots table with editorial order",
        "Playblasts table with version tracking",
        "Reviews table with sidecar support",
        "Comments table with frame timestamps",
        "Annotations table for draw-overs",
        "Users table with roles",
        "Folder schemas table for studio configuration",
    ],
    2: [
        "Shot version grouping columns (base_shot_name, shot_version)",
        "Version group ID for grouping related shot versions",
        "is_latest_shot_version flag for filtering",
    ],
    3: [
        "Multiple shot versions per folder support",
        "Changed unique constraint from folder_path to blend_file",
        "Allows SH0010_v001.blend, SH0010_v002.blend in same folder",
    ],
    4: [
        "Updated status values to match Pipeline Control",
        "Renamed 'Review' status to 'In Review'",
        "Added 'Final' status for completed shots",
    ],
    5: [
        "Added 'Needs Work' status for revision requests",
    ],
    6: [
        "Added tasks table for shot assignments",
        "Supports assignee, priority, due date tracking",
        "Shared with Pipeline Control for supervisor workflow",
    ],
    7: [
        "Added app_settings table to shared database",
        "Supports operation_mode for Pipeline Control integration",
        "Allows external apps to detect Shot Library configuration",
    ],
    8: [
        "Added display_mode column to shots table",
        "Supports per-shot PB/LD preview mode",
        "Each shot can have its own playblast/lookdev display setting",
    ],
    9: [
        "Added shot_role column for multi-camera reference files",
        "Added master_shot_id column for master/view relationships",
        "Supports standalone, master, and view shot roles",
        "Enables multi-camera workflow with combined playblasts",
    ],
    10: [
        "Added view_name column for multi-camera view identification",
        "Stores short view suffix (e.g., 'cam01', 'ref02') for JSON sidecar matching",
        "Required for combined playblast segment lookup and seeking",
    ],
    11: [
        "Added renders table for PNG/EXR image sequence management",
        "Supports folder-based versioning (Render/current/ and Render/_archive/)",
        "Tracks proxy MP4 generation for preview playback",
        "Stores render metadata (engine, samples, render time, resolution)",
    ],
}


class SchemaManager:
    """
    Database schema management for Shot Library.

    Handles:
    - Initial schema creation
    - Version tracking
    - Incremental migrations
    """

    def __init__(self, connection: DatabaseConnection):
        """
        Initialize schema manager.

        Args:
            connection: Database connection manager
        """
        self._conn = connection

    def init_database(self):
        """Initialize database schema and check for migrations."""
        with self._conn.transaction() as conn:
            cursor = conn.cursor()

            # Schema version table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Check current version
            cursor.execute('SELECT MAX(version) FROM schema_version')
            result = cursor.fetchone()
            current_version = result[0] if result[0] is not None else 0

            # Apply migrations if needed
            if current_version == 0:
                # Fresh install - create full schema
                self._create_schema(cursor)
                cursor.execute(
                    'INSERT OR REPLACE INTO schema_version (version) VALUES (?)',
                    (SCHEMA_VERSION,)
                )
            elif current_version < SCHEMA_VERSION:
                # Apply incremental migrations
                if current_version < 2:
                    self._migrate_to_v2(cursor)
                if current_version < 3:
                    self._migrate_to_v3(cursor)
                if current_version < 4:
                    self._migrate_to_v4(cursor)
                if current_version < 5:
                    self._migrate_to_v5(cursor)
                if current_version < 6:
                    self._migrate_to_v6(cursor)
                if current_version < 7:
                    self._migrate_to_v7(cursor)
                if current_version < 8:
                    self._migrate_to_v8(cursor)
                if current_version < 9:
                    self._migrate_to_v9(cursor)
                if current_version < 10:
                    self._migrate_to_v10(cursor)
                if current_version < 11:
                    self._migrate_to_v11(cursor)
                cursor.execute(
                    'INSERT OR REPLACE INTO schema_version (version) VALUES (?)',
                    (SCHEMA_VERSION,)
                )

    def _create_schema(self, cursor: sqlite3.Cursor):
        """Create database schema for Shot Library."""

        # ==================== SHOTS TABLE ====================
        # Core entity: represents a shot discovered from filesystem
        # Note: Multiple shots can share same folder_path (different blend files)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shots (
                id TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                blend_file TEXT NOT NULL UNIQUE,
                shot_name TEXT NOT NULL,

                -- Parsed identity (from folder schema parser)
                sequence_num INTEGER,
                scene_num INTEGER,
                shot_num INTEGER,
                episode_num INTEGER,

                -- Editorial order for sorting (format: "EEEE.SSSS.CCCC.HHHH")
                editorial_order TEXT NOT NULL,

                -- Shot version grouping (v2 schema)
                base_shot_name TEXT,
                shot_version INTEGER,
                version_group_id TEXT,
                is_latest_shot_version INTEGER DEFAULT 1,

                -- Production status
                status TEXT NOT NULL DEFAULT 'WIP',

                -- Preview mode (playblast or lookdev) - per-shot setting (v8 schema)
                display_mode TEXT DEFAULT 'playblast',

                -- Multi-camera reference files (v9 schema)
                -- shot_role: 'standalone' (default), 'master', or 'view'
                shot_role TEXT DEFAULT 'standalone',
                -- master_shot_id: For view shots, points to the master shot
                master_shot_id TEXT REFERENCES shots(id) ON DELETE SET NULL,
                -- view_name: Short view suffix (v10 schema)
                view_name TEXT,

                -- Parse warnings (if name couldn't be fully parsed)
                parse_warning TEXT,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        # Indexes for shots
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_editorial_order ON shots(editorial_order)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_status ON shots(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_folder_path ON shots(folder_path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_version_group ON shots(version_group_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_base_name ON shots(base_shot_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_is_latest ON shots(is_latest_shot_version)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_role ON shots(shot_role)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_master ON shots(master_shot_id)')

        # ==================== PLAYBLASTS TABLE ====================
        # Versioned video previews for each shot
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playblasts (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                file_path TEXT NOT NULL UNIQUE,

                -- Video metadata (extracted via opencv-python)
                duration_ms INTEGER,
                fps REAL,
                width INTEGER,
                height INTEGER,
                frame_count INTEGER,

                -- Version tracking
                is_latest INTEGER NOT NULL DEFAULT 0,
                is_archived INTEGER NOT NULL DEFAULT 0,

                -- Timestamp
                created_at TEXT NOT NULL,

                FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE
            )
        ''')

        # Indexes for playblasts
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_playblasts_shot_id ON playblasts(shot_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_playblasts_shot_version ON playblasts(shot_id, version)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_playblasts_shot_latest ON playblasts(shot_id, is_latest)')

        # ==================== LOOKDEVS TABLE ====================
        # Lookdev rendered previews for shots (similar to playblasts but for lookdev renders)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lookdevs (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                file_path TEXT NOT NULL UNIQUE,

                -- Video metadata (extracted via opencv-python)
                duration_ms INTEGER,
                fps REAL,
                width INTEGER,
                height INTEGER,
                frame_count INTEGER,

                -- Version tracking
                is_latest INTEGER NOT NULL DEFAULT 0,
                is_archived INTEGER NOT NULL DEFAULT 0,

                -- Timestamp
                created_at TEXT NOT NULL,

                FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE
            )
        ''')

        # Indexes for lookdevs
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lookdevs_shot_id ON lookdevs(shot_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lookdevs_shot_version ON lookdevs(shot_id, version)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lookdevs_shot_latest ON lookdevs(shot_id, is_latest)')

        # ==================== REVIEWS TABLE ====================
        # Review sessions linking shots to sidecar files
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,
                playblast_id TEXT,
                sidecar_path TEXT NOT NULL,

                -- Sync tracking
                last_synced_at TEXT NOT NULL,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE,
                FOREIGN KEY (playblast_id) REFERENCES playblasts(id) ON DELETE SET NULL
            )
        ''')

        # Indexes for reviews
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reviews_shot_id ON reviews(shot_id)')

        # ==================== COMMENTS TABLE ====================
        # Timestamped comments on playblasts
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL,
                user_id TEXT NOT NULL,

                -- Frame reference
                frame INTEGER NOT NULL,
                timecode TEXT,

                -- Content
                content TEXT NOT NULL,

                -- Timestamp
                created_at TEXT NOT NULL,

                FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

        # Indexes for comments
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_review_id ON comments(review_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_frame ON comments(frame)')

        # ==================== ANNOTATIONS TABLE ====================
        # Draw-over annotations attached to comments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS annotations (
                id TEXT PRIMARY KEY,
                comment_id TEXT NOT NULL,

                -- Frame reference
                frame INTEGER NOT NULL,

                -- Serialized drawing data (JSON)
                data_json TEXT NOT NULL,

                -- Timestamp
                created_at TEXT NOT NULL,

                FOREIGN KEY (comment_id) REFERENCES comments(id) ON DELETE CASCADE
            )
        ''')

        # Indexes for annotations
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_annotations_comment_id ON annotations(comment_id)')

        # ==================== USERS TABLE ====================
        # Team member profiles for comment attribution
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,

                -- Visual identity
                color TEXT NOT NULL,

                -- Role and status
                role TEXT NOT NULL DEFAULT 'reviewer',
                is_active INTEGER NOT NULL DEFAULT 1,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        # Indexes for users
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)')

        # ==================== TASKS TABLE ====================
        # Shot assignments for Pipeline Control integration
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,

                -- Assignment
                assigned_to TEXT,
                assigned_by TEXT,

                -- Task details
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'pending',

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE,
                FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL
            )
        ''')

        # Indexes for tasks
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_shot_id ON tasks(shot_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)')

        # ==================== FOLDER SCHEMAS TABLE ====================
        # Studio folder structure configurations
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folder_schemas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,

                -- Full schema configuration (JSON)
                config_json TEXT NOT NULL,

                -- Active schema flag (only one can be active)
                is_active INTEGER NOT NULL DEFAULT 0,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        # Indexes for folder_schemas
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_folder_schemas_active ON folder_schemas(is_active)')

        # ==================== APP SETTINGS TABLE ====================
        # Application settings shared with external tools (Pipeline Control)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        # ==================== INSERT DEFAULT DATA ====================
        # Insert built-in folder schema presets
        now = datetime.now().isoformat()

        # Simple shot schema (default)
        simple_schema = '''{
            "name": "Simple Shot",
            "hierarchy_levels": [
                {"level": "shot", "folder_contains": ".blend"}
            ],
            "blend_file_patterns": [
                "^(?P<shot>[\\\\w]+)\\\\.blend$"
            ],
            "playblast_folder": "PlayBlast",
            "playblast_pattern": "^v(?P<version>\\\\d{3})\\\\.mp4$"
        }'''

        cursor.execute('''
            INSERT OR IGNORE INTO folder_schemas (id, name, config_json, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
        ''', ('preset_simple', 'Simple Shot', simple_schema, now, now))

        # Netflix VFX schema
        netflix_schema = '''{
            "name": "Netflix VFX",
            "hierarchy_levels": [
                {"level": "show", "pattern": "^[A-Z][A-Za-z0-9_]*$"},
                {"level": "episode", "pattern": "^EP\\\\d{2}$"},
                {"level": "sequence", "pattern": "^(SQ|SEQ)\\\\d{3}$"},
                {"level": "shot", "folder_contains": ".blend"}
            ],
            "blend_file_patterns": [
                "^(?P<shot>[A-Z]+\\\\d+)_v(?P<version>\\\\d{3})\\\\.blend$",
                "^(?P<shot>[A-Za-z0-9_]+)\\\\.blend$"
            ],
            "playblast_folder": "PlayBlast",
            "playblast_pattern": "^v(?P<version>\\\\d{3})\\\\.mp4$"
        }'''

        cursor.execute('''
            INSERT OR IGNORE INTO folder_schemas (id, name, config_json, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
        ''', ('preset_netflix', 'Netflix VFX', netflix_schema, now, now))

        # ShotGrid standard schema
        shotgrid_schema = '''{
            "name": "ShotGrid Standard",
            "hierarchy_levels": [
                {"level": "show", "pattern": "^[A-Za-z0-9_]+$"},
                {"level": "sequence", "pattern": "^(SQ|SEQ|sq)_?\\\\d{3,4}$"},
                {"level": "shot", "pattern": "^(SH|SHOT|sh)_?\\\\d{3,4}$"}
            ],
            "blend_file_patterns": [
                "^(?P<shot>[\\\\w]+)_v(?P<version>\\\\d{3})\\\\.blend$",
                "^(?P<shot>[\\\\w]+)\\\\.blend$"
            ],
            "playblast_folder": "PlayBlast",
            "playblast_pattern": "^v(?P<version>\\\\d{3})\\\\.mp4$"
        }'''

        cursor.execute('''
            INSERT OR IGNORE INTO folder_schemas (id, name, config_json, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
        ''', ('preset_shotgrid', 'ShotGrid Standard', shotgrid_schema, now, now))

        # TV Flat schema
        tv_flat_schema = '''{
            "name": "TV Flat",
            "hierarchy_levels": [
                {"level": "episode", "pattern": "^EP[_\\\\-]?\\\\d+$"},
                {"level": "shot", "folder_contains": ".blend"}
            ],
            "blend_file_patterns": [
                "^(?P<shot>[\\\\w]+)_v(?P<version>\\\\d{3})\\\\.blend$",
                "^(?P<shot>[\\\\w]+)\\\\.blend$"
            ],
            "playblast_folder": "PlayBlast",
            "playblast_pattern": "^v(?P<version>\\\\d{3})\\\\.mp4$"
        }'''

        cursor.execute('''
            INSERT OR IGNORE INTO folder_schemas (id, name, config_json, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
        ''', ('preset_tv_flat', 'TV Flat', tv_flat_schema, now, now))

    def _migrate_to_v2(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v1 to v2: Add shot version grouping columns.

        Adds columns to shots table:
        - base_shot_name: Base name without version suffix
        - shot_version: Parsed version number
        - version_group_id: UUID for grouping related versions
        - is_latest_shot_version: Flag for latest in group (default 1)
        """
        # Add new columns if they don't exist
        # SQLite doesn't have ADD COLUMN IF NOT EXISTS, so we check first
        cursor.execute("PRAGMA table_info(shots)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if 'base_shot_name' not in existing_columns:
            cursor.execute('ALTER TABLE shots ADD COLUMN base_shot_name TEXT')

        if 'shot_version' not in existing_columns:
            cursor.execute('ALTER TABLE shots ADD COLUMN shot_version INTEGER')

        if 'version_group_id' not in existing_columns:
            cursor.execute('ALTER TABLE shots ADD COLUMN version_group_id TEXT')

        if 'is_latest_shot_version' not in existing_columns:
            cursor.execute('ALTER TABLE shots ADD COLUMN is_latest_shot_version INTEGER DEFAULT 1')

        # Create indexes for new columns
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_version_group ON shots(version_group_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_base_name ON shots(base_shot_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_is_latest ON shots(is_latest_shot_version)')

        # Populate version info for existing shots
        self._populate_version_info(cursor)

    def _populate_version_info(self, cursor: sqlite3.Cursor):
        """
        Populate version info for existing shots during migration.

        Parses shot_name to extract base_shot_name and shot_version,
        generates version_group_id, and marks latest versions.
        """
        from ...core.shot_version_parser import (
            parse_shot_version,
            generate_version_group_id,
        )
        from pathlib import Path

        # Get all shots
        cursor.execute('SELECT id, shot_name, folder_path FROM shots')
        shots = cursor.fetchall()

        # Group shots by base name and parent path
        groups = {}

        for shot_id, shot_name, folder_path in shots:
            info = parse_shot_version(shot_name)
            parent_path = str(Path(folder_path).parent)
            group_id = generate_version_group_id(info.base_name, parent_path)

            # Update shot with parsed version info
            cursor.execute('''
                UPDATE shots
                SET base_shot_name = ?,
                    shot_version = ?,
                    version_group_id = ?,
                    is_latest_shot_version = 0
                WHERE id = ?
            ''', (info.base_name, info.version, group_id, shot_id))

            # Track for latest determination
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append({
                'id': shot_id,
                'version': info.version,
            })

        # Mark latest versions in each group
        for group_id, shots_in_group in groups.items():
            # Sort by version (None sorts last)
            versioned = [s for s in shots_in_group if s['version'] is not None]
            unversioned = [s for s in shots_in_group if s['version'] is None]

            if versioned:
                # Mark highest version as latest
                latest = max(versioned, key=lambda s: s['version'])
                cursor.execute('''
                    UPDATE shots SET is_latest_shot_version = 1 WHERE id = ?
                ''', (latest['id'],))
            elif unversioned:
                # Mark first unversioned as latest (all are effectively latest)
                for shot in unversioned:
                    cursor.execute('''
                        UPDATE shots SET is_latest_shot_version = 1 WHERE id = ?
                    ''', (shot['id'],))

    def _migrate_to_v3(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v2 to v3: Change unique constraint from folder_path to blend_file.

        This allows multiple shot versions (blend files) to exist in the same folder.
        SQLite doesn't support ALTER TABLE DROP CONSTRAINT, so we recreate the table.
        """
        # Check if migration is needed by examining table structure
        cursor.execute("PRAGMA table_info(shots)")
        columns = {row[1]: row for row in cursor.fetchall()}

        # Check current indexes to see if we have the old unique constraint
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='shots'")
        indexes = cursor.fetchall()

        # Recreate the shots table with correct constraints
        # First, rename the old table
        cursor.execute('ALTER TABLE shots RENAME TO shots_old')

        # Create new table with blend_file UNIQUE instead of folder_path UNIQUE
        cursor.execute('''
            CREATE TABLE shots (
                id TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                blend_file TEXT NOT NULL UNIQUE,
                shot_name TEXT NOT NULL,

                -- Parsed identity (from folder schema parser)
                sequence_num INTEGER,
                scene_num INTEGER,
                shot_num INTEGER,
                episode_num INTEGER,

                -- Editorial order for sorting (format: "EEEE.SSSS.CCCC.HHHH")
                editorial_order TEXT NOT NULL,

                -- Shot version grouping (v2 schema)
                base_shot_name TEXT,
                shot_version INTEGER,
                version_group_id TEXT,
                is_latest_shot_version INTEGER DEFAULT 1,

                -- Production status
                status TEXT NOT NULL DEFAULT 'WIP',

                -- Parse warnings (if name couldn't be fully parsed)
                parse_warning TEXT,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        # Copy data from old table
        cursor.execute('''
            INSERT INTO shots
            SELECT * FROM shots_old
        ''')

        # Drop old table
        cursor.execute('DROP TABLE shots_old')

        # Recreate indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_editorial_order ON shots(editorial_order)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_status ON shots(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_folder_path ON shots(folder_path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_version_group ON shots(version_group_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_base_name ON shots(base_shot_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_is_latest ON shots(is_latest_shot_version)')

    def _migrate_to_v4(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v3 to v4: Update status values to match Pipeline Control.

        Changes:
        - Rename 'Review' status to 'In Review'
        - No schema changes, just data migration
        """
        # Update existing shots with old 'Review' status to new 'In Review'
        cursor.execute('''
            UPDATE shots
            SET status = 'In Review'
            WHERE status = 'Review'
        ''')
        
        # Log how many were updated
        updated_count = cursor.rowcount
        if updated_count > 0:
            logger.info("Schema migration v4: updated %d shots from 'Review' to 'In Review'", updated_count)

    def _migrate_to_v5(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v4 to v5: Add 'Needs Work' status support.

        Changes:
        - No schema changes needed, 'Needs Work' is a new valid status value
        - This is a version bump only to track the status addition
        """
        logger.info("Schema migration v5: 'Needs Work' status now supported")

    def _migrate_to_v6(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v5 to v6: Add tasks table for shot assignments.

        Adds tasks table for Pipeline Control integration:
        - assigned_to, assigned_by (user references)
        - priority (low, medium, high, urgent)
        - due_date, notes, status
        """
        # Create tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,

                -- Assignment
                assigned_to TEXT,
                assigned_by TEXT,

                -- Task details
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'pending',

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE,
                FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL
            )
        ''')

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_shot_id ON tasks(shot_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)')

        logger.info("Schema migration v6: created tasks table for shot assignments")

    def _migrate_to_v7(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v6 to v7: Add app_settings table.

        Adds app_settings table for Pipeline Control integration:
        - Stores operation_mode (standalone/pipeline)
        - Allows external apps to detect Shot Library configuration
        """
        now = datetime.now().isoformat()
        
        # Create app_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        # Set default operation mode to standalone
        cursor.execute('''
            INSERT OR IGNORE INTO app_settings (key, value, updated_at)
            VALUES ('operation_mode', 'standalone', ?)
        ''', (now,))

        logger.info("Schema migration v7: created app_settings table for operation mode")

    def _migrate_to_v8(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v7 to v8: Add display_mode column for per-shot preview mode.

        Adds column to shots table:
        - display_mode: 'playblast', 'lookdev', or 'render' (default 'playblast')

        This allows each shot to have its own preview mode setting that
        persists across sessions and is used in Sequence Review mode.
        """
        # Check if column already exists
        cursor.execute("PRAGMA table_info(shots)")
        columns = {row[1] for row in cursor.fetchall()}

        if 'display_mode' not in columns:
            cursor.execute(
                "ALTER TABLE shots ADD COLUMN display_mode TEXT DEFAULT 'playblast'"
            )

        logger.info("Schema migration v8: added display_mode column to shots")

    def _migrate_to_v9(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v8 to v9: Add multi-camera reference file support.

        Adds columns to shots table:
        - shot_role: 'standalone' (default), 'master', or 'view'
        - master_shot_id: For view shots, references the master shot

        This enables multi-camera workflows where:
        - Master: Contains animation/props/lighting, no camera
        - View: Links master collection + camera angle
        - Standalone: Traditional single-file shot (unchanged behavior)
        """
        # Check existing columns
        cursor.execute("PRAGMA table_info(shots)")
        columns = {row[1] for row in cursor.fetchall()}

        # Add shot_role column
        if 'shot_role' not in columns:
            cursor.execute(
                "ALTER TABLE shots ADD COLUMN shot_role TEXT DEFAULT 'standalone'"
            )

        # Add master_shot_id column
        if 'master_shot_id' not in columns:
            cursor.execute(
                "ALTER TABLE shots ADD COLUMN master_shot_id TEXT REFERENCES shots(id) ON DELETE SET NULL"
            )

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_role ON shots(shot_role)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shots_master ON shots(master_shot_id)')

        logger.info("Schema migration v9: added shot_role and master_shot_id for multi-camera")

    def _migrate_to_v10(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v9 to v10: Add view_name column for multi-camera views.

        Adds column to shots table:
        - view_name: Short view suffix (e.g., 'cam01', 'ref02') for view shots

        This is used to match segments in combined playblast JSON sidecars
        for seeking to specific camera angles.
        """
        # Check existing columns
        cursor.execute("PRAGMA table_info(shots)")
        columns = {row[1] for row in cursor.fetchall()}

        # Add view_name column
        if 'view_name' not in columns:
            cursor.execute(
                "ALTER TABLE shots ADD COLUMN view_name TEXT"
            )

        logger.info("Schema migration v10: added view_name column for multi-camera view identification")

    def _migrate_to_v11(self, cursor: sqlite3.Cursor):
        """
        Migrate from schema v10 to v11: Add renders table for image sequences.

        Adds renders table for PNG/EXR sequence management with folder-based versioning:
        - Render/current/ contains active render
        - Render/_archive/vXXX/ contains archived versions
        - Tracks proxy MP4 for preview playback
        - Stores render metadata (engine, samples, time, resolution)
        """
        # Create renders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS renders (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                folder_path TEXT NOT NULL UNIQUE,

                -- Frame sequence info
                frame_start INTEGER,
                frame_end INTEGER,
                frame_count INTEGER,
                extension TEXT,
                file_pattern TEXT,

                -- Proxy video
                proxy_path TEXT,
                proxy_generated_at TEXT,

                -- Render metadata
                render_engine TEXT,
                samples INTEGER,
                render_time_seconds REAL,
                resolution_x INTEGER,
                resolution_y INTEGER,

                -- Version tracking
                is_current INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,

                FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE
            )
        ''')

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_renders_shot_id ON renders(shot_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_renders_is_current ON renders(shot_id, is_current)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_renders_version ON renders(shot_id, version)')

        logger.info("Schema migration v11: created renders table for image sequence management")

    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics for status display.

        Returns:
            Dict containing schema version, record counts, file size, etc.
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        # Schema version
        cursor.execute('SELECT MAX(version) FROM schema_version')
        result = cursor.fetchone()
        schema_version = result[0] if result and result[0] is not None else 0

        # Record counts
        shot_count = 0
        playblast_count = 0
        review_count = 0
        comment_count = 0
        user_count = 0

        try:
            cursor.execute('SELECT COUNT(*) FROM shots')
            shot_count = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('SELECT COUNT(*) FROM playblasts')
            playblast_count = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('SELECT COUNT(*) FROM reviews')
            review_count = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('SELECT COUNT(*) FROM comments')
            comment_count = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
            user_count = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            pass

        # Database file size
        db_path = self._conn.db_path
        db_size_bytes = db_path.stat().st_size if db_path.exists() else 0

        # Get pending features
        pending_features = []
        for version in range(schema_version + 1, SCHEMA_VERSION + 1):
            if version in VERSION_FEATURES:
                pending_features.extend(VERSION_FEATURES[version])

        return {
            'schema_version': schema_version,
            'latest_version': SCHEMA_VERSION,
            'is_up_to_date': schema_version >= SCHEMA_VERSION,
            'needs_upgrade': schema_version < SCHEMA_VERSION,
            'shot_count': shot_count,
            'playblast_count': playblast_count,
            'review_count': review_count,
            'comment_count': comment_count,
            'user_count': user_count,
            'db_size_bytes': db_size_bytes,
            'db_size_mb': round(db_size_bytes / (1024 * 1024), 2),
            'db_path': str(db_path),
            'pending_features': pending_features,
        }

    def run_integrity_check(self) -> Tuple[bool, str]:
        """
        Run database integrity check.

        Returns:
            Tuple of (is_ok, message)
        """
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        results = []

        # Run PRAGMA integrity_check
        cursor.execute('PRAGMA integrity_check')
        integrity_result = cursor.fetchall()
        integrity_ok = len(integrity_result) == 1 and integrity_result[0][0] == 'ok'

        if integrity_ok:
            results.append("Integrity check: OK")
        else:
            results.append(f"Integrity check: FAILED - {integrity_result}")

        # Run PRAGMA foreign_key_check
        cursor.execute('PRAGMA foreign_key_check')
        fk_result = cursor.fetchall()
        fk_ok = len(fk_result) == 0

        if fk_ok:
            results.append("Foreign key check: OK")
        else:
            results.append(f"Foreign key check: FAILED - {len(fk_result)} violations")

        is_ok = integrity_ok and fk_ok
        message = "\n".join(results)

        return is_ok, message

    def optimize_database(self) -> Tuple[int, int]:
        """
        Optimize database by running VACUUM.

        Returns:
            Tuple of (size_before, size_after) in bytes
        """
        db_path = self._conn.db_path
        size_before = db_path.stat().st_size if db_path.exists() else 0

        # Close all connections and run VACUUM
        conn = self._conn.get_connection()
        conn.execute('VACUUM')

        size_after = db_path.stat().st_size if db_path.exists() else 0

        return size_before, size_after

    def get_current_version(self) -> int:
        """Get current schema version."""
        conn = self._conn.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT MAX(version) FROM schema_version')
            result = cursor.fetchone()
            return result[0] if result and result[0] is not None else 0
        except sqlite3.OperationalError:
            return 0


def backup_database(db_path: Path, backup_dir: Optional[Path] = None) -> Path:
    """
    Create a backup of the database using SQLite backup API.

    Args:
        db_path: Path to the database file
        backup_dir: Directory for backups (defaults to db_path.parent / 'backups')

    Returns:
        Path to the backup file
    """
    if backup_dir is None:
        backup_dir = db_path.parent / 'backups'

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"database_backup_{timestamp}.db"

    # Checkpoint WAL to ensure all data is in main file
    source = sqlite3.connect(str(db_path))
    source.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Use SQLite backup API for atomic, consistent snapshot
    dest = sqlite3.connect(str(backup_path))
    source.backup(dest)

    source.close()
    dest.close()

    return backup_path


def get_backups(db_path: Path) -> List[Dict[str, Any]]:
    """
    Get list of existing backups.

    Args:
        db_path: Path to the database file

    Returns:
        List of backup info dicts with 'path', 'size', 'date'
    """
    backup_dir = db_path.parent / 'backups'
    if not backup_dir.exists():
        return []

    backups = []
    for backup_file in sorted(backup_dir.glob("database_backup_*.db"), reverse=True):
        stat = backup_file.stat()
        backups.append({
            'path': str(backup_file),
            'filename': backup_file.name,
            'size_bytes': stat.st_size,
            'size_mb': round(stat.st_size / (1024 * 1024), 2),
            'date': datetime.fromtimestamp(stat.st_mtime),
        })

    return backups


def delete_backup(backup_path: Path) -> bool:
    """
    Delete a backup file.

    Args:
        backup_path: Path to the backup file

    Returns:
        True if deleted successfully
    """
    try:
        if backup_path.exists():
            backup_path.unlink()
            return True
        return False
    except Exception:
        return False


__all__ = [
    'SchemaManager',
    'SCHEMA_VERSION',
    'VERSION_FEATURES',
    'backup_database',
    'get_backups',
    'delete_backup',
]
