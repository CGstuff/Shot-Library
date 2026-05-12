"""
API Dependencies

Provides FastAPI dependency injection for database services,
user services, and audit services.
"""

from pathlib import Path
from typing import Optional, Generator
from functools import lru_cache

from ..services.database_service import DatabaseService
from ..services.user_service import UserService
from ..services.audit_service import AuditService


class ServiceContainer:
    """
    Container for shared service instances.
    
    In standalone mode, this holds the services created from a db_path.
    In embedded mode, this holds references to the GUI's existing services.
    """
    
    _instance: Optional['ServiceContainer'] = None
    
    def __init__(self):
        self._db_service: Optional[DatabaseService] = None
        self._user_service: Optional[UserService] = None
        self._audit_service: Optional[AuditService] = None
        self._db_path: Optional[Path] = None
    
    @classmethod
    def get_instance(cls) -> 'ServiceContainer':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset singleton (for testing)."""
        if cls._instance:
            cls._instance.close()
        cls._instance = None
    
    def configure_standalone(self, db_path: Path):
        """
        Configure for standalone server mode.
        
        Creates new service instances connected to the specified database.
        
        Args:
            db_path: Path to shot_library.db file
        """
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        
        self._db_path = db_path
        self._db_service = DatabaseService(db_path)
        self._user_service = UserService(self._db_service)
        self._audit_service = AuditService(self._db_service, self._user_service)
        
        # Wire up audit service to user service
        self._user_service.set_audit_service(self._audit_service)
    
    def configure_embedded(
        self,
        db_service: DatabaseService,
        user_service: UserService,
        audit_service: AuditService
    ):
        """
        Configure for embedded mode (running alongside GUI).
        
        Uses existing service instances from the GUI.
        
        Args:
            db_service: Existing DatabaseService from GUI
            user_service: Existing UserService from GUI
            audit_service: Existing AuditService from GUI
        """
        self._db_service = db_service
        self._user_service = user_service
        self._audit_service = audit_service
        self._db_path = db_service.db_path
    
    @property
    def db_service(self) -> DatabaseService:
        """Get database service."""
        if self._db_service is None:
            raise RuntimeError("ServiceContainer not configured. Call configure_standalone() or configure_embedded() first.")
        return self._db_service
    
    @property
    def user_service(self) -> UserService:
        """Get user service."""
        if self._user_service is None:
            raise RuntimeError("ServiceContainer not configured. Call configure_standalone() or configure_embedded() first.")
        return self._user_service
    
    @property
    def audit_service(self) -> AuditService:
        """Get audit service."""
        if self._audit_service is None:
            raise RuntimeError("ServiceContainer not configured. Call configure_standalone() or configure_embedded() first.")
        return self._audit_service
    
    @property
    def db_path(self) -> Optional[Path]:
        """Get database path."""
        return self._db_path
    
    @property
    def is_configured(self) -> bool:
        """Check if container is configured."""
        return self._db_service is not None
    
    def close(self):
        """Close services (for standalone mode cleanup)."""
        if self._db_service:
            self._db_service.close()
        self._db_service = None
        self._user_service = None
        self._audit_service = None
        self._db_path = None


# ==================== FastAPI Dependencies ====================

def get_container() -> ServiceContainer:
    """
    FastAPI dependency: Get service container.
    
    Usage:
        @app.get("/shots")
        def get_shots(container: ServiceContainer = Depends(get_container)):
            return container.db_service.get_all_shots()
    """
    return ServiceContainer.get_instance()


def get_db_service() -> DatabaseService:
    """
    FastAPI dependency: Get database service.
    
    Usage:
        @app.get("/shots")
        def get_shots(db: DatabaseService = Depends(get_db_service)):
            return db.get_all_shots()
    """
    return ServiceContainer.get_instance().db_service


def get_user_service() -> UserService:
    """
    FastAPI dependency: Get user service.
    
    Usage:
        @app.get("/users")
        def get_users(users: UserService = Depends(get_user_service)):
            return users.get_all_users()
    """
    return ServiceContainer.get_instance().user_service


def get_audit_service() -> AuditService:
    """
    FastAPI dependency: Get audit service.
    
    Usage:
        @app.get("/audit")
        def get_audit(audit: AuditService = Depends(get_audit_service)):
            return audit.get_recent_activity()
    """
    return ServiceContainer.get_instance().audit_service


__all__ = [
    'ServiceContainer',
    'get_container',
    'get_db_service',
    'get_user_service',
    'get_audit_service',
]
