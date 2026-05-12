"""
Shots API Routes

Endpoints for querying and updating shots.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_db_service, get_audit_service
from ..auth import get_current_user, get_current_user_optional
from ..models import (
    ShotResponse,
    ShotListResponse,
    ShotStatusUpdateRequest,
    ErrorResponse,
)
from ...services.database_service import DatabaseService
from ...services.audit_service import AuditService
from ...services.user_service import User


router = APIRouter()


def _shot_to_response(shot: dict, db: DatabaseService) -> ShotResponse:
    """Convert database shot dict to API response model."""
    # Get playblast info
    playblasts = db.get_playblasts_for_shot(shot['id'])
    playblast_count = len(playblasts)
    latest_version = max((pb.get('version', 0) for pb in playblasts), default=None)
    
    return ShotResponse(
        id=shot['id'],
        folder_path=shot.get('folder_path', ''),
        blend_file=shot.get('blend_file'),
        shot_name=shot.get('shot_name', shot.get('name', 'Unknown')),
        status=shot.get('status', 'WIP'),
        editorial_order=shot.get('editorial_order', 0),
        episode_num=shot.get('episode_num'),
        sequence_num=shot.get('sequence_num'),
        scene_num=shot.get('scene_num'),
        shot_num=shot.get('shot_num'),
        base_shot_name=shot.get('base_shot_name'),
        shot_version=shot.get('shot_version'),
        version_group_id=shot.get('version_group_id'),
        is_latest_shot_version=bool(shot.get('is_latest_shot_version', True)),
        created_at=datetime.fromisoformat(shot['created_at']) if shot.get('created_at') else datetime.now(),
        updated_at=datetime.fromisoformat(shot['updated_at']) if shot.get('updated_at') else datetime.now(),
        playblast_count=playblast_count,
        latest_playblast_version=latest_version,
    )


@router.get(
    "",
    response_model=ShotListResponse,
    summary="List all shots",
    description="Get all shots in editorial order. Optionally filter by status.",
)
async def list_shots(
    status: Optional[str] = Query(None, description="Filter by status (WIP, Review, Approved, Blocked)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    List all shots in editorial order.
    
    - **status**: Optional filter by shot status
    - **limit**: Maximum number of results (1-1000)
    - **offset**: Pagination offset
    
    Authentication is optional for read operations.
    """
    if status:
        shots = db.get_shots_by_status(status)
    else:
        shots = db.get_all_shots(order_by_editorial=True)
    
    # Apply pagination
    total = len(shots)
    shots = shots[offset:offset + limit]
    
    return ShotListResponse(
        shots=[_shot_to_response(s, db) for s in shots],
        total=total,
    )


@router.get(
    "/{shot_id}",
    response_model=ShotResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get shot by ID",
    description="Get detailed information about a specific shot.",
)
async def get_shot(
    shot_id: str,
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get a shot by its UUID.
    
    Returns 404 if shot not found.
    """
    shot = db.get_shot_by_uuid(shot_id)
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot not found: {shot_id}",
        )
    
    return _shot_to_response(shot, db)


@router.get(
    "/by-folder/{folder_path:path}",
    response_model=ShotResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get shot by folder path",
    description="Get a shot by its folder path.",
)
async def get_shot_by_folder(
    folder_path: str,
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get a shot by its folder path.
    
    The folder_path should be the relative or absolute path to the shot folder.
    Returns 404 if shot not found.
    """
    shot = db.get_shot_by_folder(folder_path)
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot not found at path: {folder_path}",
        )
    
    return _shot_to_response(shot, db)


@router.patch(
    "/{shot_id}/status",
    response_model=ShotResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Update shot status",
    description="Update the status of a shot. Requires authentication.",
)
async def update_shot_status(
    shot_id: str,
    request: ShotStatusUpdateRequest,
    db: DatabaseService = Depends(get_db_service),
    audit: AuditService = Depends(get_audit_service),
    user: User = Depends(get_current_user),
):
    """
    Update a shot's status.
    
    Valid statuses: WIP, In Review, Needs Work, Approved, Final, Blocked
    
    Requires authentication. The change is logged to the audit trail.
    
    Note: This endpoint is blocked when Shot Library is in Pipeline Mode.
    In Pipeline Mode, status changes must come from Pipeline Control.
    """
    # Check operation mode - block in Pipeline Mode
    from ...services.control_authority import get_control_authority
    
    if not get_control_authority().can_edit_status():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shot Library is in Pipeline Mode. Status changes must come from Pipeline Control.",
        )
    
    # Validate status (must match Pipeline Control)
    valid_statuses = ['WIP', 'In Review', 'Needs Work', 'Approved', 'Final', 'Blocked']
    if request.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )
    
    # Get current shot
    shot = db.get_shot_by_uuid(shot_id)
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot not found: {shot_id}",
        )
    
    old_status = shot.get('status', 'WIP')
    
    # Update status
    success = db.set_status(shot_id, request.status)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update shot status",
        )
    
    # Log to audit trail
    shot_name = shot.get('shot_name', shot.get('name', 'Unknown'))
    audit.log_status_change(
        shot_id=shot_id,
        shot_name=shot_name,
        old_status=old_status,
        new_status=request.status,
    )
    
    # Return updated shot
    updated_shot = db.get_shot_by_uuid(shot_id)
    return _shot_to_response(updated_shot, db)


@router.get(
    "/stats/by-status",
    summary="Get shot counts by status",
    description="Get the count of shots grouped by status.",
)
async def get_shot_stats(
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get shot statistics by status.
    
    Returns a dict with status as keys and counts as values.
    """
    counts = db.get_shot_count_by_status()
    total = db.get_shot_count()
    
    return {
        "total": total,
        "by_status": counts,
    }
