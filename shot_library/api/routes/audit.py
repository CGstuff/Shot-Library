"""
Audit API Routes

Endpoints for querying the audit trail.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_audit_service
from ..auth import get_current_user, get_current_user_optional
from ..models import (
    AuditEventResponse,
    AuditListResponse,
    AuditStatsResponse,
)
from ...services.audit_service import AuditService, AuditEntityType, AuditAction, AuditEvent
from ...services.user_service import User


router = APIRouter()


def _event_to_response(event: AuditEvent) -> AuditEventResponse:
    """Convert AuditEvent to API response model."""
    return AuditEventResponse(
        id=event.id,
        timestamp=event.timestamp,
        user_id=event.user_id,
        username=event.username,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        entity_name=event.entity_name,
        action=event.action,
        field_changed=event.field_changed,
        old_value=event.old_value,
        new_value=event.new_value,
        metadata=event.metadata,
        project_path=event.project_path,
    )


@router.get(
    "",
    response_model=AuditListResponse,
    summary="Get audit events",
    description="Query the audit trail with optional filters.",
)
async def list_audit_events(
    entity_type: Optional[str] = Query(None, description="Filter by entity type (shot, playblast, user, etc.)"),
    action: Optional[str] = Query(None, description="Filter by action (created, updated, status_changed, etc.)"),
    user_id: Optional[str] = Query(None, description="Filter by user who performed the action"),
    entity_id: Optional[str] = Query(None, description="Filter by specific entity ID"),
    since: Optional[datetime] = Query(None, description="Only events after this timestamp"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results"),
    audit: AuditService = Depends(get_audit_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Query the audit trail.
    
    Filters can be combined. All filters are optional.
    
    - **entity_type**: shot, playblast, user, note, drawover, playlist, project
    - **action**: created, updated, deleted, restored, viewed, status_changed, discovered, logged_in, logged_out
    - **user_id**: UUID of the user who performed the action
    - **entity_id**: UUID of the specific entity to get history for
    - **since**: ISO timestamp to filter events after
    - **limit**: Maximum number of results (1-500)
    """
    # Handle entity-specific history
    if entity_id and entity_type:
        try:
            etype = AuditEntityType(entity_type)
            events = audit.get_entity_history(etype, entity_id, limit=limit)
        except ValueError:
            events = []
    # Handle user activity
    elif user_id:
        events = audit.get_user_activity(user_id, limit=limit)
    # General query
    else:
        entity_types = None
        actions = None
        
        if entity_type:
            try:
                entity_types = [AuditEntityType(entity_type)]
            except ValueError:
                pass
        
        if action:
            try:
                actions = [AuditAction(action)]
            except ValueError:
                pass
        
        events = audit.get_recent_activity(
            limit=limit,
            entity_types=entity_types,
            actions=actions,
            since=since,
        )
    
    return AuditListResponse(
        events=[_event_to_response(e) for e in events],
        total=len(events),
    )


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=AuditListResponse,
    summary="Get entity history",
    description="Get audit history for a specific entity.",
)
async def get_entity_history(
    entity_type: str,
    entity_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    audit: AuditService = Depends(get_audit_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get the complete audit history for a specific entity.
    
    - **entity_type**: shot, playblast, user, note, drawover, playlist, project
    - **entity_id**: UUID of the entity
    
    Returns events in reverse chronological order (newest first).
    """
    try:
        etype = AuditEntityType(entity_type)
    except ValueError:
        return AuditListResponse(events=[], total=0)
    
    events = audit.get_entity_history(etype, entity_id, limit=limit)
    
    return AuditListResponse(
        events=[_event_to_response(e) for e in events],
        total=len(events),
    )


@router.get(
    "/user/{user_id}",
    response_model=AuditListResponse,
    summary="Get user activity",
    description="Get all audit events for actions performed by a specific user.",
)
async def get_user_activity(
    user_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    audit: AuditService = Depends(get_audit_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get activity feed for a specific user.
    
    Shows all actions performed by the user in reverse chronological order.
    """
    events = audit.get_user_activity(user_id, limit=limit)
    
    return AuditListResponse(
        events=[_event_to_response(e) for e in events],
        total=len(events),
    )


@router.get(
    "/stats",
    response_model=AuditStatsResponse,
    summary="Get audit statistics",
    description="Get aggregated statistics from the audit trail.",
)
async def get_audit_stats(
    audit: AuditService = Depends(get_audit_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get audit statistics for the current project.
    
    Returns:
    - Total event count
    - Breakdown by action type
    - Breakdown by entity type
    - Top users by activity
    - Events in last 24 hours
    """
    stats = audit.get_stats()
    
    return AuditStatsResponse(
        total=stats.get('total', 0),
        by_action=stats.get('by_action', {}),
        by_entity_type=stats.get('by_entity_type', {}),
        by_user=stats.get('by_user', {}),
        last_24_hours=stats.get('last_24_hours', 0),
    )


@router.get(
    "/recent",
    response_model=AuditListResponse,
    summary="Get recent activity",
    description="Get the most recent audit events (activity feed).",
)
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100, description="Number of recent events"),
    audit: AuditService = Depends(get_audit_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get recent activity feed.
    
    A convenience endpoint for dashboard/activity widgets.
    Returns the most recent events across all entity types.
    """
    events = audit.get_recent_activity(limit=limit)
    
    return AuditListResponse(
        events=[_event_to_response(e) for e in events],
        total=len(events),
    )
