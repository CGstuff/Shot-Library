"""
API Authentication

Simple token-based authentication for Shot Library API.

This is a lightweight auth system designed for small studios:
- No passwords (users are identified by username only)
- JWT tokens with expiration
- Tokens are issued per-session, not persisted

For production use with external access, consider adding:
- API keys for service accounts
- OAuth2 integration
- Rate limiting
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import jwt

from .dependencies import get_user_service
from ..services.user_service import UserService, User


# ==================== CONFIGURATION ====================

# Secret key for JWT signing (generated at startup)
# In production, this should be loaded from environment/config
_jwt_secret: str = ""

# Token expiration time
TOKEN_EXPIRY_HOURS = 24

# JWT algorithm
JWT_ALGORITHM = "HS256"


def init_auth():
    """
    Initialize authentication system.
    
    Generates a new JWT secret for this server session.
    Call this during server startup.
    """
    global _jwt_secret
    _jwt_secret = secrets.token_urlsafe(32)


def get_jwt_secret() -> str:
    """Get current JWT secret."""
    if not _jwt_secret:
        init_auth()
    return _jwt_secret


# ==================== TOKEN GENERATION ====================

def create_access_token(user: User) -> tuple[str, int]:
    """
    Create a JWT access token for a user.
    
    Args:
        user: User to create token for
        
    Returns:
        Tuple of (token_string, expires_in_seconds)
    """
    expires_delta = timedelta(hours=TOKEN_EXPIRY_HOURS)
    expires_at = datetime.utcnow() + expires_delta
    
    payload = {
        "sub": str(user.id),  # Subject (user ID)
        "username": user.username,
        "role": user.role.value,
        "exp": expires_at,
        "iat": datetime.utcnow(),
    }
    
    token = jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)
    expires_in = int(expires_delta.total_seconds())
    
    return token, expires_in


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload
        
    Raises:
        jwt.InvalidTokenError: If token is invalid or expired
    """
    return jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])


# ==================== FASTAPI DEPENDENCIES ====================

# HTTP Bearer scheme for token extraction
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    user_service: UserService = Depends(get_user_service)
) -> Optional[User]:
    """
    FastAPI dependency: Get current user from token (optional).
    
    Returns None if no token provided or token is invalid.
    Does not raise exceptions.
    
    Usage:
        @app.get("/shots")
        def get_shots(user: Optional[User] = Depends(get_current_user_optional)):
            # user may be None
    """
    if credentials is None:
        return None
    
    try:
        payload = decode_token(credentials.credentials)
        user_id = UUID(payload["sub"])
        user = user_service.get_user(user_id)
        
        if user and user.is_active:
            return user
        return None
        
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    user_service: UserService = Depends(get_user_service)
) -> User:
    """
    FastAPI dependency: Get current user from token (required).
    
    Raises HTTPException if no valid token provided.
    
    Usage:
        @app.patch("/shots/{id}/status")
        def update_status(user: User = Depends(get_current_user)):
            # user is guaranteed to exist
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if credentials is None:
        raise credentials_exception
    
    try:
        payload = decode_token(credentials.credentials)
        user_id = UUID(payload["sub"])
        user = user_service.get_user(user_id)
        
        if user is None:
            raise credentials_exception
            
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated",
            )
        
        return user
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise credentials_exception


async def require_admin(
    user: User = Depends(get_current_user)
) -> User:
    """
    FastAPI dependency: Require admin role.
    
    Raises HTTPException if user is not an admin.
    
    Usage:
        @app.post("/users")
        def create_user(admin: User = Depends(require_admin)):
            # admin is guaranteed to have admin role
    """
    from ..services.user_service import Role
    
    if user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


__all__ = [
    'init_auth',
    'create_access_token',
    'decode_token',
    'get_current_user',
    'get_current_user_optional',
    'require_admin',
    'TOKEN_EXPIRY_HOURS',
]
