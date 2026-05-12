"""
User Service

Manages user profiles, roles, and authentication.
Implements the user-service contract.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID
import re

from PyQt6.QtCore import QObject, pyqtSignal

from ..config import Config


class Role(Enum):
    """User role enumeration."""
    ADMIN = "admin"
    REVIEWER = "reviewer"


@dataclass
class User:
    """A team member profile."""
    id: UUID
    username: str
    display_name: str
    color: str  # Hex color (#RRGGBB)
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserService(QObject):
    """
    Manages user profiles and roles.

    Stores data locally in application database.
    Fully offline-capable.
    """

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

    # Signals
    user_created = pyqtSignal(object)  # User
    user_updated = pyqtSignal(object)  # User
    user_deactivated = pyqtSignal(object)  # UUID
    user_reactivated = pyqtSignal(object)  # User
    active_user_changed = pyqtSignal(object)  # User

    def __init__(self, db_service: 'DatabaseService', parent=None):
        """
        Initialize user service.

        Args:
            db_service: Database service for persistence
        """
        super().__init__(parent)
        self._db = db_service
        self._active_user: Optional[User] = None
        self._audit_service = None  # Set via set_audit_service()

        # Load persisted active user from config (T100)
        self._load_active_user_from_config()

    def set_audit_service(self, audit_service):
        """
        Set the audit service for user action logging.

        Args:
            audit_service: AuditService instance
        """
        self._audit_service = audit_service

    def get_user(self, user_id: UUID) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User's UUID

        Returns:
            User or None if not found
        """
        row = self._db.users.get_by_id(str(user_id))
        if row:
            return self._row_to_user(row)
        return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Get user by username.

        Args:
            username: Username to find

        Returns:
            User or None if not found
        """
        row = self._db.users.get_by_username(username)
        if row:
            return self._row_to_user(row)
        return None

    def get_all_users(self, include_inactive: bool = False) -> List[User]:
        """
        Get all users.

        Args:
            include_inactive: Whether to include deactivated users

        Returns:
            List of users
        """
        rows = self._db.users.get_all(include_inactive=include_inactive)
        return [self._row_to_user(row) for row in rows]

    def get_active_user(self) -> Optional[User]:
        """
        Get the currently active user.

        Returns:
            Current user or None if not set
        """
        return self._active_user

    def set_active_user(self, user_id: UUID) -> User:
        """
        Set the active user for this session.

        Persists active user ID to config file for session recovery (T100).

        Args:
            user_id: User to activate

        Returns:
            Activated user

        Raises:
            KeyError: If user not found
            ValueError: If user is inactive
        """
        user = self.get_user(user_id)
        if not user:
            raise KeyError(f"User not found: {user_id}")

        if not user.is_active:
            raise ValueError(f"Cannot activate inactive user: {user.username}")

        self._active_user = user

        # Persist active user ID to config (T100)
        self._save_active_user_to_config(user_id)

        # Log user login to audit trail
        if self._audit_service:
            self._audit_service.log_user_login(str(user_id), user.username)

        self.active_user_changed.emit(user)
        return user

    def create_user(
        self,
        username: str,
        display_name: str,
        color: str,
        role: Role = Role.REVIEWER
    ) -> User:
        """
        Create a new user profile.

        Requires admin role.

        Args:
            username: Unique username
            display_name: Display name
            color: Assigned color (hex)
            role: User role

        Returns:
            Created user

        Raises:
            PermissionError: If active user is not admin
            ValueError: If username exists or color invalid
        """
        # Check if first user (auto-admin) or admin creating
        users = self.get_all_users(include_inactive=True)
        is_first_user = len(users) == 0

        if not is_first_user:
            if not self._active_user:
                raise PermissionError("No active user")
            if self._active_user.role != Role.ADMIN:
                raise PermissionError("Only admins can create users")

        # Validate username
        if not self._validate_username(username):
            raise ValueError("Username must be 3-32 alphanumeric characters or underscores")

        # Validate color
        if not self._validate_color(color):
            raise ValueError("Color must be a valid hex color (#RRGGBB)")

        # Check for duplicate username
        if self._db.users.exists(username):
            raise ValueError(f"Username already exists: {username}")

        # First user is always admin
        actual_role = Role.ADMIN if is_first_user else role

        # Create user
        user_id = self._db.users.create(
            username=username,
            display_name=display_name,
            color=color,
            role=actual_role.value,
            is_active=True
        )

        user = self.get_user(UUID(user_id))
        if user:
            self.user_created.emit(user)

            # Log user creation to audit trail
            if self._audit_service:
                creator_id = str(self._active_user.id) if self._active_user else None
                creator_name = self._active_user.username if self._active_user else "system"
                self._audit_service.log_user_created(
                    user_id=user_id,
                    username=user.username,
                    created_by_id=creator_id,
                    created_by_name=creator_name
                )

            # Auto-activate first user
            if is_first_user:
                self.set_active_user(user.id)

        return user

    def update_user(
        self,
        user_id: UUID,
        display_name: Optional[str] = None,
        color: Optional[str] = None,
        role: Optional[Role] = None
    ) -> User:
        """
        Update a user profile.

        Requires admin role (except self-update of display_name).

        Args:
            user_id: User to update
            display_name: New display name
            color: New color
            role: New role

        Returns:
            Updated user

        Raises:
            PermissionError: If not authorized
            KeyError: If user not found
        """
        user = self.get_user(user_id)
        if not user:
            raise KeyError(f"User not found: {user_id}")

        # Check permissions
        is_self = self._active_user and self._active_user.id == user_id
        is_admin = self._active_user and self._active_user.role == Role.ADMIN

        # Non-admins can only update own display_name
        if not is_admin:
            if not is_self:
                raise PermissionError("Only admins can update other users")
            if color is not None or role is not None:
                raise PermissionError("Only admins can change color or role")

        # Validate color if provided
        if color and not self._validate_color(color):
            raise ValueError("Color must be a valid hex color (#RRGGBB)")

        # Update user
        self._db.users.update(
            user_id=str(user_id),
            display_name=display_name,
            color=color,
            role=role.value if role else None
        )

        updated_user = self.get_user(user_id)
        if updated_user:
            self.user_updated.emit(updated_user)

            # Update active user if it was modified
            if self._active_user and self._active_user.id == user_id:
                self._active_user = updated_user

        return updated_user

    def deactivate_user(self, user_id: UUID) -> None:
        """
        Deactivate a user (soft delete).

        Requires admin role. Cannot deactivate self.

        Args:
            user_id: User to deactivate

        Raises:
            PermissionError: If not admin or trying to self-deactivate
            KeyError: If user not found
        """
        if not self._active_user or self._active_user.role != Role.ADMIN:
            raise PermissionError("Only admins can deactivate users")

        if self._active_user.id == user_id:
            raise PermissionError("Cannot deactivate yourself")

        user = self.get_user(user_id)
        if not user:
            raise KeyError(f"User not found: {user_id}")

        self._db.users.deactivate(str(user_id))

        # Log user deactivation to audit trail
        if self._audit_service:
            self._audit_service.log_user_deactivated(str(user_id), user.username)

        self.user_deactivated.emit(user_id)

    def reactivate_user(self, user_id: UUID) -> User:
        """
        Reactivate a deactivated user.

        Requires admin role.

        Args:
            user_id: User to reactivate

        Returns:
            Reactivated user

        Raises:
            PermissionError: If not admin
            KeyError: If user not found
        """
        if not self._active_user or self._active_user.role != Role.ADMIN:
            raise PermissionError("Only admins can reactivate users")

        user = self.get_user(user_id)
        if not user:
            raise KeyError(f"User not found: {user_id}")

        self._db.users.reactivate(str(user_id))

        reactivated_user = self.get_user(user_id)
        if reactivated_user:
            self.user_reactivated.emit(reactivated_user)

        return reactivated_user

    def get_available_colors(self) -> List[str]:
        """
        Get list of available (unused) colors.

        Returns:
            List of hex colors not assigned to active users
        """
        return self._db.users.get_available_colors()

    def validate_color(self, color: str) -> bool:
        """
        Validate a color string.

        Args:
            color: Color to validate

        Returns:
            True if valid hex color
        """
        return self._validate_color(color)

    def _validate_username(self, username: str) -> bool:
        """Validate username format."""
        return bool(re.match(r'^[a-zA-Z0-9_]{3,32}$', username))

    def _validate_color(self, color: str) -> bool:
        """Validate hex color format."""
        return bool(re.match(r'^#[0-9A-Fa-f]{6}$', color))

    def _row_to_user(self, row: dict) -> User:
        """Convert database row to User object."""
        return User(
            id=UUID(row['id']),
            username=row['username'],
            display_name=row['display_name'],
            color=row['color'],
            role=Role(row['role']),
            is_active=bool(row.get('is_active', True)),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )

    # ==================== T100: Active User Persistence ====================

    def _load_active_user_from_config(self) -> None:
        """
        Load and restore active user from config file.

        Called during initialization to restore the last active user session.
        If the persisted user no longer exists or is inactive, falls back to
        the first available admin user.
        """
        import json

        settings_file = Config.get_settings_file()
        if not settings_file.exists():
            return

        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            user_id_str = settings.get('active_user_id')
            if not user_id_str:
                return

            # Try to restore the persisted user
            user = self.get_user(UUID(user_id_str))
            if user and user.is_active:
                self._active_user = user
                return

            # Persisted user not found or inactive - try to select first admin
            self._fallback_to_first_admin()

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Config file corrupted or invalid UUID - try fallback
            self._fallback_to_first_admin()

    def _fallback_to_first_admin(self) -> None:
        """
        Fall back to first active admin user if available.

        Called when the persisted active user is no longer valid.
        """
        try:
            admins = self._db.users.get_admins()
            if admins:
                admin = self._row_to_user(admins[0])
                self._active_user = admin
                # Save the fallback selection
                self._save_active_user_to_config(admin.id)
        except Exception:
            pass  # No admins available - leave active_user as None

    def _save_active_user_to_config(self, user_id: UUID) -> bool:
        """
        Save active user ID to config file for session persistence.

        Args:
            user_id: UUID of the user to persist

        Returns:
            True if saved successfully
        """
        import json

        try:
            settings_file = Config.get_settings_file()
            settings_file.parent.mkdir(parents=True, exist_ok=True)

            # Load existing settings
            settings = {}
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except json.JSONDecodeError:
                    pass  # Start with empty settings

            # Update active user ID
            settings['active_user_id'] = str(user_id)

            # Save back
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)

            return True

        except Exception:
            return False

    def clear_active_user_from_config(self) -> bool:
        """
        Remove active user ID from config file.

        Called when logging out or when the user should be cleared.

        Returns:
            True if cleared successfully
        """
        import json

        try:
            settings_file = Config.get_settings_file()
            if not settings_file.exists():
                return True

            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            if 'active_user_id' in settings:
                del settings['active_user_id']

                with open(settings_file, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2)

            return True

        except Exception:
            return False


__all__ = [
    'Role',
    'User',
    'UserService',
]
