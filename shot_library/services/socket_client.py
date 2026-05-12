"""
Socket Client Stub for Shot Library

Shot Library does not use socket communication with Blender.
This stub provides the expected interface from Animation Library.
"""

from typing import Optional, Callable, Any
from PyQt6.QtCore import QObject, pyqtSignal


class SocketClient(QObject):
    """
    Stub socket client for Shot Library.

    Shot Library does not communicate with Blender via sockets.
    This is a compatibility stub.
    """

    # Signals (kept for compatibility but never emitted)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    message_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False

    def connect_to_blender(self, host: str = "localhost", port: int = 9999) -> bool:
        """Stub: Always returns False."""
        return False

    def disconnect_from_blender(self):
        """Stub: No-op."""
        pass

    def is_connected(self) -> bool:
        """Always returns False."""
        return False

    def send_message(self, message: str) -> bool:
        """Stub: Always returns False."""
        return False

    def send_command(self, command: str, data: Optional[dict] = None) -> bool:
        """Stub: Always returns False."""
        return False


# Singleton instance
_socket_client_instance: Optional[SocketClient] = None


def get_socket_client() -> SocketClient:
    """
    Get global SocketClient singleton instance.

    Returns:
        SocketClient stub instance
    """
    global _socket_client_instance
    if _socket_client_instance is None:
        _socket_client_instance = SocketClient()
    return _socket_client_instance


__all__ = ['SocketClient', 'get_socket_client']
