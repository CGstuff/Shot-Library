"""
Shot Library REST API

Provides HTTP endpoints for external applications (like the Kitsu-style
orchestration app) to access Shot Library data.

The API can run in two modes:
1. Embedded: Started automatically when Shot Library GUI launches
2. Standalone: Run as a separate server process

Usage (standalone):
    python -m shot_library.api.server --db-path /path/to/.meta/shot_library.db

Usage (embedded):
    from shot_library.api import create_app, EmbeddedAPIServer

    # Option 1: Using EmbeddedAPIServer helper class
    api_server = EmbeddedAPIServer(db_service, user_service, audit_service)
    api_server.start(port=8765)

    # Option 2: Manual control
    app = create_app(embedded=True, db_service=..., user_service=..., audit_service=...)
    thread = run_embedded_server(app, port=8765)

Note: FastAPI is optional. If not installed, API features are disabled.
"""

# API is optional - fastapi may not be installed in bundled builds
API_AVAILABLE = False
API_VERSION = "1.0.0"

# Placeholders for when fastapi is not available
create_app = None
run_server = None
run_embedded_server = None
EmbeddedAPIServer = None
ShotResponse = None
ShotListResponse = None
PlayblastResponse = None
PlayblastListResponse = None
AuditEventResponse = None
AuditListResponse = None
UserResponse = None
UserListResponse = None
TokenResponse = None
ErrorResponse = None
HealthResponse = None
ProjectInfoResponse = None

try:
    from .server import (
        create_app,
        run_server,
        run_embedded_server,
        EmbeddedAPIServer,
        API_VERSION,
    )
    from .models import (
        ShotResponse,
        ShotListResponse,
        PlayblastResponse,
        PlayblastListResponse,
        AuditEventResponse,
        AuditListResponse,
        UserResponse,
        UserListResponse,
        TokenResponse,
        ErrorResponse,
        HealthResponse,
        ProjectInfoResponse,
    )
    API_AVAILABLE = True
except ImportError:
    # FastAPI not installed - API features disabled
    pass

__all__ = [
    # Server
    'create_app',
    'run_server',
    'run_embedded_server',
    'EmbeddedAPIServer',
    'API_VERSION',
    # Models
    'ShotResponse',
    'ShotListResponse',
    'PlayblastResponse',
    'PlayblastListResponse',
    'AuditEventResponse',
    'AuditListResponse',
    'UserResponse',
    'UserListResponse',
    'TokenResponse',
    'ErrorResponse',
    'HealthResponse',
    'ProjectInfoResponse',
]
