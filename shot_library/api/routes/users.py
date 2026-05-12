"""
Users and Authentication API Routes

Endpoints for user management and authentication.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import get_user_service, get_audit_service
from ..auth import (
    create_access_token,
    get_current_user,
    get_current_user_optional,
    require_admin,
)
from ..models import (
    TokenRequest,
    TokenResponse,
    UserResponse,
    UserListResponse,
    UserCreateRequest,
    ErrorResponse,
)
from ...services.user_service import UserService, User, Role
from ...services.audit_service import AuditService


router = APIRouter()


def _user_to_response(user: User) -> UserResponse:
    """Convert User object to API response model."""
    return UserResponse(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        color=user.color,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# ==================== AUTHENTICATION ====================

@router.post(
    "/auth/token",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Get access token",
    description="Authenticate and get a JWT access token.",
    tags=["auth"],
)
async def login(
    request: TokenRequest,
    user_service: UserService = Depends(get_user_service),
    audit: AuditService = Depends(get_audit_service),
):
    """
    Authenticate with username and get a JWT token.
    
    Shot Library uses a simple authentication model:
    - No passwords (small studio trust model)
    - Just provide your username to get a token
    - Token expires after 24 hours
    
    The user must exist and be active.
    """
    # Find user by username
    user = user_service.get_user_by_username(request.username)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {request.username}",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated",
        )
    
    # Create token
    token, expires_in = create_access_token(user)
    
    # Log login
    audit.log_user_login(str(user.id), user.username)
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
        user_id=str(user.id),
        username=user.username,
        role=user.role.value,
    )


@router.get(
    "/auth/me",
    response_model=UserResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Get current user",
    description="Get the currently authenticated user's profile.",
    tags=["auth"],
)
async def get_me(
    user: User = Depends(get_current_user),
):
    """
    Get the current authenticated user's profile.
    
    Requires a valid token.
    """
    return _user_to_response(user)


# ==================== USER MANAGEMENT ====================

@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List all users",
    description="Get all users. Optionally include inactive users.",
)
async def list_users(
    include_inactive: bool = False,
    user_service: UserService = Depends(get_user_service),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    List all users.
    
    - **include_inactive**: If true, include deactivated users
    
    Authentication is optional for read operations.
    """
    users = user_service.get_all_users(include_inactive=include_inactive)
    
    return UserListResponse(
        users=[_user_to_response(u) for u in users],
        total=len(users),
    )


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get user by ID",
    description="Get a specific user's profile.",
)
async def get_user(
    user_id: str,
    user_service: UserService = Depends(get_user_service),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get a user by their UUID.
    
    Returns 404 if user not found.
    """
    try:
        user = user_service.get_user(UUID(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {user_id}",
        )
    
    return _user_to_response(user)


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Create a new user",
    description="Create a new user. Requires admin role (except for first user).",
)
async def create_user(
    request: UserCreateRequest,
    user_service: UserService = Depends(get_user_service),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Create a new user.
    
    - Requires admin role (except when creating the first user)
    - The first user created automatically becomes an admin
    - Username must be unique, 3-32 alphanumeric characters or underscores
    - Color must be a valid hex color (#RRGGBB)
    """
    # Check if this is the first user (bootstrap case)
    existing_users = user_service.get_all_users(include_inactive=True)
    is_first_user = len(existing_users) == 0
    
    if not is_first_user:
        # Require authentication and admin role
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if current_user.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required to create users",
            )
        
        # Temporarily set active user for permission checks
        user_service._active_user = current_user
    
    try:
        # Determine role
        role = Role(request.role) if request.role else Role.REVIEWER
        
        # Determine color
        color = request.color
        if not color:
            available = user_service.get_available_colors()
            color = available[0] if available else "#3498DB"
        
        # Create user
        new_user = user_service.create_user(
            username=request.username,
            display_name=request.display_name,
            color=color,
            role=role,
        )
        
        return _user_to_response(new_user)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Deactivate a user",
    description="Soft-delete a user (deactivate). Requires admin role.",
)
async def deactivate_user(
    user_id: str,
    user_service: UserService = Depends(get_user_service),
    admin: User = Depends(require_admin),
):
    """
    Deactivate a user (soft delete).
    
    - Requires admin role
    - Cannot deactivate yourself
    - User data is preserved but they can no longer authenticate
    """
    # Set active user for permission checks
    user_service._active_user = admin
    
    try:
        user_service.deactivate_user(UUID(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {user_id}",
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


@router.post(
    "/users/{user_id}/reactivate",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Reactivate a user",
    description="Reactivate a deactivated user. Requires admin role.",
)
async def reactivate_user(
    user_id: str,
    user_service: UserService = Depends(get_user_service),
    admin: User = Depends(require_admin),
):
    """
    Reactivate a deactivated user.
    
    Requires admin role.
    """
    # Set active user for permission checks
    user_service._active_user = admin
    
    try:
        user = user_service.reactivate_user(UUID(user_id))
        return _user_to_response(user)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {user_id}",
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


@router.get(
    "/users/colors/available",
    summary="Get available colors",
    description="Get list of colors not yet assigned to active users.",
)
async def get_available_colors(
    user_service: UserService = Depends(get_user_service),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get available user colors.
    
    Returns a list of hex colors that are not currently assigned
    to any active user.
    """
    colors = user_service.get_available_colors()
    return {"colors": colors}
