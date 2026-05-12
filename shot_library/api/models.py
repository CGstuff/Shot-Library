"""
API Pydantic Models

Response and request schemas for the Shot Library REST API.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ==================== ERROR RESPONSES ====================

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional details")


# ==================== TOKEN / AUTH ====================

class TokenRequest(BaseModel):
    """Token request for authentication."""
    username: str = Field(..., description="Username")
    # For now, no password - just username identification for small studios


class TokenResponse(BaseModel):
    """Token response after successful authentication."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiry in seconds")
    user_id: str = Field(..., description="User UUID")
    username: str = Field(..., description="Username")
    role: str = Field(..., description="User role (admin/reviewer)")


# ==================== USER MODELS ====================

class UserResponse(BaseModel):
    """User information response."""
    id: str = Field(..., description="User UUID")
    username: str = Field(..., description="Username")
    display_name: str = Field(..., description="Display name")
    color: str = Field(..., description="User color (hex)")
    role: str = Field(..., description="Role (admin/reviewer)")
    is_active: bool = Field(..., description="Whether user is active")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """List of users response."""
    users: List[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total count")


class UserCreateRequest(BaseModel):
    """Request to create a new user."""
    username: str = Field(..., min_length=3, max_length=32, description="Username")
    display_name: str = Field(..., min_length=1, max_length=64, description="Display name")
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$', description="Hex color")
    role: str = Field(default="reviewer", description="Role (admin/reviewer)")


# ==================== SHOT MODELS ====================

class ShotResponse(BaseModel):
    """Shot information response."""
    id: str = Field(..., description="Shot UUID")
    folder_path: str = Field(..., description="Shot folder path")
    blend_file: Optional[str] = Field(None, description="Blend file name")
    shot_name: str = Field(..., description="Shot name")
    status: str = Field(..., description="Shot status")
    editorial_order: str = Field(..., description="Editorial order key (e.g., '0001.0002.0003.0004')")
    
    # Shot identity
    episode_num: Optional[int] = Field(None, description="Episode number")
    sequence_num: Optional[int] = Field(None, description="Sequence number")
    scene_num: Optional[int] = Field(None, description="Scene number")
    shot_num: Optional[int] = Field(None, description="Shot number")
    
    # Version grouping
    base_shot_name: Optional[str] = Field(None, description="Base shot name (without version)")
    shot_version: Optional[int] = Field(None, description="Shot version number")
    version_group_id: Optional[str] = Field(None, description="Version group identifier")
    is_latest_shot_version: bool = Field(default=True, description="Is latest version")
    
    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    # Playblast info (computed)
    playblast_count: Optional[int] = Field(None, description="Number of playblasts")
    latest_playblast_version: Optional[int] = Field(None, description="Latest playblast version")

    class Config:
        from_attributes = True


class ShotListResponse(BaseModel):
    """List of shots response."""
    shots: List[ShotResponse] = Field(..., description="List of shots")
    total: int = Field(..., description="Total count")


class ShotStatusUpdateRequest(BaseModel):
    """Request to update shot status."""
    status: str = Field(..., description="New status value")


# ==================== PLAYBLAST MODELS ====================

class PlayblastResponse(BaseModel):
    """Playblast information response."""
    id: str = Field(..., description="Playblast UUID")
    shot_id: str = Field(..., description="Parent shot UUID")
    version: int = Field(..., description="Version number")
    file_path: str = Field(..., description="Full file path")
    
    # Video metadata
    duration_ms: Optional[int] = Field(None, description="Duration in milliseconds")
    fps: Optional[float] = Field(None, description="Frames per second")
    width: Optional[int] = Field(None, description="Video width")
    height: Optional[int] = Field(None, description="Video height")
    frame_count: Optional[int] = Field(None, description="Total frame count")
    
    # Flags
    is_latest: bool = Field(default=False, description="Is latest version")
    is_archived: bool = Field(default=False, description="Is archived")
    
    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True


class PlayblastListResponse(BaseModel):
    """List of playblasts response."""
    playblasts: List[PlayblastResponse] = Field(..., description="List of playblasts")
    total: int = Field(..., description="Total count")


# ==================== AUDIT MODELS ====================

class AuditEventResponse(BaseModel):
    """Audit event response."""
    id: int = Field(..., description="Event ID")
    timestamp: datetime = Field(..., description="Event timestamp")
    user_id: Optional[str] = Field(None, description="User UUID who performed action")
    username: str = Field(..., description="Username")
    entity_type: str = Field(..., description="Entity type (shot, playblast, user, etc.)")
    entity_id: str = Field(..., description="Entity UUID")
    entity_name: Optional[str] = Field(None, description="Entity name for display")
    action: str = Field(..., description="Action performed")
    field_changed: Optional[str] = Field(None, description="Field that was changed")
    old_value: Optional[Any] = Field(None, description="Previous value")
    new_value: Optional[Any] = Field(None, description="New value")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    project_path: Optional[str] = Field(None, description="Project path context")

    class Config:
        from_attributes = True


class AuditListResponse(BaseModel):
    """List of audit events response."""
    events: List[AuditEventResponse] = Field(..., description="List of audit events")
    total: int = Field(..., description="Total count")


class AuditStatsResponse(BaseModel):
    """Audit statistics response."""
    total: int = Field(..., description="Total event count")
    by_action: Dict[str, int] = Field(..., description="Count by action type")
    by_entity_type: Dict[str, int] = Field(..., description="Count by entity type")
    by_user: Dict[str, int] = Field(..., description="Count by user (top 10)")
    last_24_hours: int = Field(..., description="Events in last 24 hours")


# ==================== PROJECT MODELS ====================

class ProjectInfoResponse(BaseModel):
    """Project/database information response."""
    project_path: str = Field(..., description="Project folder path")
    db_path: str = Field(..., description="Database file path")
    shot_count: int = Field(..., description="Total shots")
    playblast_count: int = Field(..., description="Total playblasts")
    user_count: int = Field(..., description="Total users")
    audit_event_count: int = Field(..., description="Total audit events")


# ==================== HEALTH CHECK ====================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(default="ok", description="Service status")
    version: str = Field(..., description="API version")
    db_connected: bool = Field(..., description="Database connection status")


__all__ = [
    'ErrorResponse',
    'TokenRequest',
    'TokenResponse',
    'UserResponse',
    'UserListResponse',
    'UserCreateRequest',
    'ShotResponse',
    'ShotListResponse',
    'ShotStatusUpdateRequest',
    'PlayblastResponse',
    'PlayblastListResponse',
    'AuditEventResponse',
    'AuditListResponse',
    'AuditStatsResponse',
    'ProjectInfoResponse',
    'HealthResponse',
]
