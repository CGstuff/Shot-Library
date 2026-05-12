"""
Shot Library REST API Server

FastAPI application factory and server runner.

Supports two modes:
1. Embedded: Run alongside the GUI in a background thread
2. Standalone: Run as a separate server process

Usage (standalone):
    python -m shot_library.api.server --db-path /path/to/.meta/shot_library.db

Usage (embedded):
    from shot_library.api import create_app, run_embedded_server
    app = create_app(embedded=True, db_service=..., user_service=..., audit_service=...)
    thread = run_embedded_server(app, port=8765)
"""

import argparse
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import init_auth
from .dependencies import ServiceContainer
from .routes import api_router
from .models import HealthResponse, ProjectInfoResponse


logger = logging.getLogger(__name__)

# API Version
API_VERSION = "1.0.0"


def create_app(
    embedded: bool = False,
    db_service=None,
    user_service=None,
    audit_service=None,
    db_path: Optional[Path] = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Args:
        embedded: If True, use provided services from GUI.
                  If False, create standalone services from db_path.
        db_service: DatabaseService instance (embedded mode)
        user_service: UserService instance (embedded mode)
        audit_service: AuditService instance (embedded mode)
        db_path: Path to database file (standalone mode)
    
    Returns:
        Configured FastAPI application
    
    Raises:
        ValueError: If configuration is invalid
    """
    # Validate configuration
    if embedded:
        if not all([db_service, user_service, audit_service]):
            raise ValueError(
                "Embedded mode requires db_service, user_service, and audit_service"
            )
    else:
        if not db_path:
            raise ValueError("Standalone mode requires db_path")
    
    # Initialize auth system
    init_auth()
    
    # Configure service container
    container = ServiceContainer.get_instance()
    
    if embedded:
        container.configure_embedded(db_service, user_service, audit_service)
        mode_desc = "embedded with GUI"
    else:
        container.configure_standalone(db_path)
        mode_desc = f"standalone (db: {db_path})"
    
    # Create FastAPI app
    app = FastAPI(
        title="Shot Library API",
        description="""
REST API for Shot Library - a production visibility system for browsing shots and reviewing playblasts.

## Authentication

Most read endpoints are public. Write operations require authentication.

To authenticate:
1. POST to `/api/v1/auth/token` with your username
2. Include the returned token in the `Authorization: Bearer <token>` header

## Endpoints

- **Shots**: Query and update shot information
- **Playblasts**: Query playblast versions
- **Audit**: Query the audit trail
- **Users**: User management and authentication
        """,
        version=API_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure as needed for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include API routes
    app.include_router(api_router, prefix="/api/v1")
    
    # Root endpoints
    @app.get("/", include_in_schema=False)
    async def root():
        """Redirect to docs."""
        return {"message": "Shot Library API", "docs": "/docs"}
    
    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health_check():
        """Health check endpoint."""
        db_connected = container.is_configured
        return HealthResponse(
            status="ok" if db_connected else "degraded",
            version=API_VERSION,
            db_connected=db_connected,
        )
    
    @app.get("/api/v1/project", response_model=ProjectInfoResponse, tags=["system"])
    async def get_project_info():
        """Get project/database information."""
        db = container.db_service
        
        return ProjectInfoResponse(
            project_path=str(container.db_path.parent.parent) if container.db_path else "",
            db_path=str(container.db_path) if container.db_path else "",
            shot_count=db.get_shot_count(),
            playblast_count=db.get_playblast_count(),
            user_count=db.get_user_count(),
            audit_event_count=db.audit.count() if hasattr(db.audit, 'count') else 0,
        )
    
    logger.info(f"Shot Library API initialized ({mode_desc})")
    
    return app


def run_server(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    reload: bool = False,
):
    """
    Run the API server in standalone mode.
    
    This is a blocking call that runs until interrupted.
    
    Args:
        db_path: Path to shot_library.db
        host: Host to bind to
        port: Port to listen on
        reload: Enable auto-reload (development only)
    """
    import uvicorn
    
    # Create app
    app = create_app(embedded=False, db_path=db_path)
    
    # Run server
    logger.info(f"Starting Shot Library API server on http://{host}:{port}")
    logger.info(f"Database: {db_path}")
    logger.info("Press Ctrl+C to stop")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def run_embedded_server(
    app: FastAPI,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> threading.Thread:
    """
    Run the API server in a background thread (embedded mode).
    
    Returns immediately with a thread handle. The server runs until
    the thread is stopped or the application exits.
    
    Args:
        app: FastAPI application from create_app()
        host: Host to bind to
        port: Port to listen on
    
    Returns:
        Thread running the server
    """
    import uvicorn
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",  # Quieter in embedded mode
    )
    server = uvicorn.Server(config)
    
    def run():
        server.run()
    
    thread = threading.Thread(target=run, daemon=True, name="ShotLibraryAPI")
    thread.start()
    
    logger.info(f"Shot Library API server started on http://{host}:{port} (embedded)")
    
    return thread


class EmbeddedAPIServer:
    """
    Helper class for managing the embedded API server lifecycle.
    
    Usage:
        api_server = EmbeddedAPIServer(db_service, user_service, audit_service)
        api_server.start(port=8765)
        # ... later ...
        api_server.stop()
    """
    
    def __init__(self, db_service, user_service, audit_service):
        """
        Initialize embedded server.
        
        Args:
            db_service: DatabaseService instance
            user_service: UserService instance
            audit_service: AuditService instance
        """
        self._db_service = db_service
        self._user_service = user_service
        self._audit_service = audit_service
        self._app: Optional[FastAPI] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._running = False
    
    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running and self._thread is not None and self._thread.is_alive()
    
    def start(self, host: str = "127.0.0.1", port: int = 8765) -> bool:
        """
        Start the embedded API server.
        
        Args:
            host: Host to bind to
            port: Port to listen on
        
        Returns:
            True if started successfully
        """
        if self.is_running:
            logger.warning("API server is already running")
            return False
        
        try:
            import uvicorn
            
            # Create app
            self._app = create_app(
                embedded=True,
                db_service=self._db_service,
                user_service=self._user_service,
                audit_service=self._audit_service,
            )
            
            # Configure server
            config = uvicorn.Config(
                self._app,
                host=host,
                port=port,
                log_level="warning",
            )
            self._server = uvicorn.Server(config)
            
            # Start in thread
            def run():
                self._running = True
                try:
                    self._server.run()
                finally:
                    self._running = False
            
            self._thread = threading.Thread(target=run, daemon=True, name="ShotLibraryAPI")
            self._thread.start()
            
            logger.info(f"Embedded API server started on http://{host}:{port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            return False
    
    def stop(self):
        """Stop the embedded API server."""
        if self._server:
            self._server.should_exit = True
        self._running = False
        
        # Give thread a moment to stop
        if self._thread:
            self._thread.join(timeout=2.0)
        
        # Reset state
        self._app = None
        self._thread = None
        self._server = None
        
        logger.info("Embedded API server stopped")


# ==================== CLI ====================

def main():
    """Command-line entry point for standalone server."""
    parser = argparse.ArgumentParser(
        description="Shot Library REST API Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start server with database
    python -m shot_library.api.server --db-path /project/.meta/shot_library.db
    
    # Start on custom port
    python -m shot_library.api.server --db-path /project/.meta/shot_library.db --port 9000
    
    # Enable external access
    python -m shot_library.api.server --db-path /project/.meta/shot_library.db --host 0.0.0.0
        """
    )
    
    parser.add_argument(
        "--db-path",
        type=Path,
        required=True,
        help="Path to shot_library.db file"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only)"
    )
    
    args = parser.parse_args()
    
    # Validate database path
    if not args.db_path.exists():
        print(f"Error: Database not found: {args.db_path}")
        return 1
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run server
    try:
        run_server(
            db_path=args.db_path,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    
    return 0


if __name__ == "__main__":
    exit(main())
