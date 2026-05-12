"""
Playblasts API Routes

Endpoints for querying playblast versions.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_db_service
from ..auth import get_current_user_optional
from ..models import (
    PlayblastResponse,
    PlayblastListResponse,
    ErrorResponse,
)
from ...services.database_service import DatabaseService
from ...services.user_service import User


router = APIRouter()


def _playblast_to_response(pb: dict) -> PlayblastResponse:
    """Convert database playblast dict to API response model."""
    return PlayblastResponse(
        id=pb['id'],
        shot_id=pb.get('shot_id', ''),
        version=pb.get('version', 1),
        file_path=pb.get('file_path', ''),
        duration_ms=pb.get('duration_ms'),
        fps=pb.get('fps'),
        width=pb.get('width'),
        height=pb.get('height'),
        frame_count=pb.get('frame_count'),
        is_latest=bool(pb.get('is_latest', False)),
        is_archived=bool(pb.get('is_archived', False)),
        created_at=datetime.fromisoformat(pb['created_at']) if pb.get('created_at') else datetime.now(),
        updated_at=datetime.fromisoformat(pb['updated_at']) if pb.get('updated_at') else datetime.now(),
    )


@router.get(
    "",
    response_model=PlayblastListResponse,
    summary="List all playblasts",
    description="Get all playblasts across all shots.",
)
async def list_playblasts(
    shot_id: Optional[str] = Query(None, description="Filter by shot ID"),
    latest_only: bool = Query(False, description="Only return latest version per shot"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    List playblasts with optional filtering.
    
    - **shot_id**: Optional filter by shot ID
    - **latest_only**: If true, only return latest version per shot
    - **limit**: Maximum number of results (1-1000)
    - **offset**: Pagination offset
    """
    if shot_id:
        # Get playblasts for specific shot
        if latest_only:
            latest = db.get_latest_playblast(shot_id)
            playblasts = [latest] if latest else []
        else:
            playblasts = db.get_playblasts_for_shot(shot_id)
    else:
        # Get all playblasts across all shots
        # Note: This queries all shots and collects their playblasts
        shots = db.get_all_shots()
        playblasts = []
        for shot in shots:
            if latest_only:
                latest = db.get_latest_playblast(shot['id'])
                if latest:
                    playblasts.append(latest)
            else:
                playblasts.extend(db.get_playblasts_for_shot(shot['id']))
    
    # Apply pagination
    total = len(playblasts)
    playblasts = playblasts[offset:offset + limit]
    
    return PlayblastListResponse(
        playblasts=[_playblast_to_response(pb) for pb in playblasts],
        total=total,
    )


@router.get(
    "/{playblast_id}",
    response_model=PlayblastResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get playblast by ID",
    description="Get detailed information about a specific playblast.",
)
async def get_playblast(
    playblast_id: str,
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get a playblast by its UUID.
    
    Returns 404 if playblast not found.
    """
    pb = db.playblasts.get_by_id(playblast_id)
    if not pb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playblast not found: {playblast_id}",
        )
    
    return _playblast_to_response(pb)


@router.get(
    "/shot/{shot_id}",
    response_model=PlayblastListResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get playblasts for shot",
    description="Get all playblast versions for a specific shot.",
)
async def get_playblasts_for_shot(
    shot_id: str,
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get all playblasts for a shot.
    
    Returns playblasts ordered by version (newest first).
    Returns 404 if shot not found.
    """
    # Verify shot exists
    shot = db.get_shot_by_uuid(shot_id)
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot not found: {shot_id}",
        )
    
    playblasts = db.get_playblasts_for_shot(shot_id)
    
    return PlayblastListResponse(
        playblasts=[_playblast_to_response(pb) for pb in playblasts],
        total=len(playblasts),
    )


@router.get(
    "/shot/{shot_id}/latest",
    response_model=PlayblastResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get latest playblast for shot",
    description="Get the latest playblast version for a specific shot.",
)
async def get_latest_playblast_for_shot(
    shot_id: str,
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get the latest playblast for a shot.
    
    Returns 404 if shot not found or has no playblasts.
    """
    # Verify shot exists
    shot = db.get_shot_by_uuid(shot_id)
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot not found: {shot_id}",
        )
    
    latest = db.get_latest_playblast(shot_id)
    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No playblasts found for shot: {shot_id}",
        )
    
    return _playblast_to_response(latest)


@router.get(
    "/stats/summary",
    summary="Get playblast statistics",
    description="Get overall playblast statistics.",
)
async def get_playblast_stats(
    db: DatabaseService = Depends(get_db_service),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get playblast statistics.
    
    Returns total count and other summary statistics.
    """
    total = db.get_playblast_count()
    
    # Count shots with playblasts
    shots = db.get_all_shots()
    shots_with_playblasts = 0
    total_versions = 0
    
    for shot in shots:
        playblasts = db.get_playblasts_for_shot(shot['id'])
        if playblasts:
            shots_with_playblasts += 1
            total_versions += len(playblasts)
    
    return {
        "total_playblasts": total,
        "shots_with_playblasts": shots_with_playblasts,
        "total_shots": len(shots),
        "average_versions_per_shot": round(total_versions / shots_with_playblasts, 2) if shots_with_playblasts > 0 else 0,
    }
