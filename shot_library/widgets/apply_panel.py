"""
Apply Panel Stub for Shot Library

Shot Library is read-only and does not apply animations to Blender.
This minimal stub provides interface compatibility with shared widgets.
"""

from typing import Optional, Dict, Any
from PyQt6.QtWidgets import QWidget, QVBoxLayout


class ApplyPanel(QWidget):
    """
    Minimal stub apply panel for Shot Library.

    Shot Library is read-only - this stub exists only for interface compatibility.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shot = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.hide()  # Never shown in Shot Library

    def set_animation(self, shot: Optional[Dict[str, Any]]):
        """Stub - stores shot reference but does nothing visible."""
        self._shot = shot

    def get_current_animation(self) -> Optional[Dict[str, Any]]:
        """Stub - returns current shot."""
        return self._shot

    def clear(self):
        """Stub - clears shot reference."""
        self._shot = None

    def get_options(self, apply_mode: str = "NEW") -> Dict[str, Any]:
        """Stub - returns empty options dict."""
        return {}

    def set_shortcut_toggles_visible(self, visible: bool):
        """Stub - no-op."""
        pass


__all__ = ['ApplyPanel']
