"""
Blender Service for Shot Library

Shot Library is a read-only browser. Blender interaction is limited to:
- Status queries (is Blender connected?)
- Playblast capture (triggered from Blender plugin)
- Opening .blend files (future feature)
"""

import threading
from typing import Optional


class BlenderService:
    """
    Minimal Blender service for Shot Library.

    Shot Library is read-only - this service only provides status queries.
    Playblast capture is triggered from the Blender plugin side, not here.
    """

    def __init__(self):
        self._connected = False

    def is_blender_connected(self) -> bool:
        """Check if Blender plugin is connected."""
        return self._connected

    def get_blender_version(self) -> Optional[str]:
        """Get connected Blender version (None if not connected)."""
        return None


# Singleton instance with thread safety
_blender_service_instance: Optional[BlenderService] = None
_blender_service_lock = threading.Lock()


def get_blender_service() -> BlenderService:
    """
    Get global BlenderService singleton instance (thread-safe).

    Returns:
        BlenderService instance
    """
    global _blender_service_instance
    if _blender_service_instance is None:
        with _blender_service_lock:
            # Double-check after acquiring lock
            if _blender_service_instance is None:
                _blender_service_instance = BlenderService()
    return _blender_service_instance


__all__ = ['BlenderService', 'get_blender_service']
