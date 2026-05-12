"""
API Routes

Aggregates all API routers into a single router for the main app.
"""

from fastapi import APIRouter

from .shots import router as shots_router
from .playblasts import router as playblasts_router
from .audit import router as audit_router
from .users import router as users_router


# Create main API router
api_router = APIRouter()

# Include all sub-routers
api_router.include_router(shots_router, prefix="/shots", tags=["shots"])
api_router.include_router(playblasts_router, prefix="/playblasts", tags=["playblasts"])
api_router.include_router(audit_router, prefix="/audit", tags=["audit"])
api_router.include_router(users_router, tags=["users"])  # Has own prefixes for /users and /auth


__all__ = ['api_router']
