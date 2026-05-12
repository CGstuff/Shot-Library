"""Services for Shot Library"""

from .database_service import DatabaseService, get_database_service
from .thumbnail_loader import ThumbnailLoader, get_thumbnail_loader
from .media_engine import MediaEngine, VideoInfo, FrameResult, frame_to_timecode
from .user_service import UserService, Role, User
from .review_service import ReviewService, Comment, AnnotationData, Review
from .control_authority import ControlAuthority, OperationMode, get_control_authority
# New services for refactored architecture
from .discovery_service import DiscoveryService, DiscoveryResult, get_discovery_service
from .sync_service import SyncService, SyncResult, get_sync_service

__all__ = [
    # Database
    'DatabaseService',
    'get_database_service',
    # Thumbnail
    'ThumbnailLoader',
    'get_thumbnail_loader',
    # Media Engine
    'MediaEngine',
    'VideoInfo',
    'FrameResult',
    'frame_to_timecode',
    # User Service
    'UserService',
    'Role',
    'User',
    # Review Service
    'ReviewService',
    'Comment',
    'AnnotationData',
    'Review',
    # Control Authority (Pipeline Control integration)
    'ControlAuthority',
    'OperationMode',
    'get_control_authority',
    # Discovery Service
    'DiscoveryService',
    'DiscoveryResult',
    'get_discovery_service',
    # Sync Service
    'SyncService',
    'SyncResult',
    'get_sync_service',
]
