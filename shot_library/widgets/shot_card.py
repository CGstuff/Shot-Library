"""
ShotCard - Shot card widget with hover-to-play video preview

Implements tasks T089, T091:
- T089: Integrate VideoPreviewWidget with shot card renderer
- T091: Wire up hover events to trigger video preview

The shot card displays:
- 16:9 thumbnail from playblast (or placeholder)
- Shot name and editorial order badge
- Status badge (WIP, Review, Approved, Blocked)
- Playblast version badge
- Parse warning indicator (if name couldn't be parsed)

Hover behavior:
- 500ms delay before showing video preview
- Video plays in popup while hovering
- Preview stops when cursor leaves
"""

import os
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint, QModelIndex, pyqtSignal
from PyQt6.QtGui import QPixmap

from ..config import Config
from ..models.shot_list_model import ShotRole


class ShotCardHoverHandler:
    """
    Handles hover events for shot cards with video preview.

    Implements T091: Wire up hover events to trigger video preview.

    This is a mixin/helper class that can be used by shot card delegates
    or views to manage hover-to-play behavior.

    Usage:
        handler = ShotCardHoverHandler(view)
        # In mouseMoveEvent:
        handler.on_hover(index, position)
        # In leaveEvent:
        handler.on_leave()
    """

    def __init__(self, parent_view):
        """
        Initialize hover handler.

        Args:
            parent_view: Parent QListView or similar view widget
        """
        self._view = parent_view
        self._preview_widget = None  # Lazy-loaded

        # Hover state
        self._hover_index: Optional[QModelIndex] = None
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)
        self._last_hover_pos = QPoint()

    def _ensure_preview_widget(self):
        """Lazy-create the preview widget."""
        if self._preview_widget is None:
            from .shot_video_preview import ShotVideoPreviewWidget
            self._preview_widget = ShotVideoPreviewWidget(self._view)
            self._preview_widget.set_size(Config.HOVER_VIDEO_SIZE)

    def on_hover(self, index: QModelIndex, position: QPoint):
        """
        Handle mouse hover over a shot card.

        Implements T091: Wire up hover events to trigger video preview.

        Args:
            index: Model index of hovered shot
            position: Mouse position in view coordinates
        """
        if not Config.ENABLE_HOVER_VIDEO:
            return

        if index.isValid():
            if index != self._hover_index:
                # New item hovered - start timer
                self._cancel_pending_preview()
                self._hover_index = index
                self._last_hover_pos = position
                self._hover_timer.start(Config.HOVER_VIDEO_DELAY_MS)
        else:
            # No valid item under cursor
            self._cancel_pending_preview()
            self.on_leave()

    def on_leave(self):
        """Handle mouse leaving the view - hide preview."""
        self._cancel_pending_preview()
        if self._preview_widget:
            self._preview_widget.hide_preview()

    def update_position(self, position: QPoint):
        """Update preview position (for follow-mouse behavior)."""
        if self._preview_widget and self._preview_widget.is_showing:
            global_pos = self._calculate_preview_position(position)
            self._preview_widget.update_position(global_pos)

    def _cancel_pending_preview(self):
        """Cancel any pending hover preview."""
        self._hover_timer.stop()
        if self._preview_widget:
            self._preview_widget.cancel_hover_preview()

    def _on_hover_timeout(self):
        """Handle hover timer timeout - show preview."""
        if not self._hover_index or not self._hover_index.isValid():
            return

        # Get preview mode (playblast or lookdev)
        preview_mode = self._hover_index.data(ShotRole.PreviewModeRole) or "playblast"

        # Get video path based on preview mode
        if preview_mode == "lookdev":
            video_path_str = self._hover_index.data(ShotRole.LatestLookdevPathRole)
            placeholder_text = "No Lookdev"
        else:
            video_path_str = self._hover_index.data(ShotRole.LatestPlayblastPathRole)
            placeholder_text = "No Playblast"

        if not video_path_str:
            # No video - show placeholder
            shot_name = self._hover_index.data(ShotRole.NameRole) or "Unknown"
            self._ensure_preview_widget()
            position = self._calculate_preview_position(self._last_hover_pos)
            self._preview_widget.show_placeholder(f"{placeholder_text}\n{shot_name}")
            self._preview_widget.move(position)
            self._preview_widget.show()
            return

        video_path = Path(video_path_str)
        if not video_path.exists():
            return

        # Show preview
        self._ensure_preview_widget()
        position = self._calculate_preview_position(self._last_hover_pos)
        self._preview_widget.show_preview(video_path, position)

    def _calculate_preview_position(self, cursor_pos: QPoint) -> QPoint:
        """
        Calculate preview popup position.

        Args:
            cursor_pos: Cursor position in view coordinates

        Returns:
            Global screen position for popup
        """
        position_mode = Config.HOVER_VIDEO_POSITION
        popup_size = Config.HOVER_VIDEO_SIZE

        # Convert to global coordinates
        global_cursor_pos = self._view.viewport().mapToGlobal(cursor_pos)

        if position_mode == "cursor":
            # Position near cursor with offset
            offset = 20
            return QPoint(
                global_cursor_pos.x() + offset,
                global_cursor_pos.y() + offset
            )

        # Get card rect for other positioning modes
        if self._hover_index and self._hover_index.isValid():
            card_rect = self._view.visualRect(self._hover_index)
            global_card_top_left = self._view.viewport().mapToGlobal(card_rect.topLeft())

            if position_mode == "right":
                return QPoint(
                    global_card_top_left.x() + card_rect.width() + 10,
                    global_card_top_left.y()
                )
            elif position_mode == "left":
                return QPoint(
                    global_card_top_left.x() - popup_size - 10,
                    global_card_top_left.y()
                )
            elif position_mode == "above":
                return QPoint(
                    global_card_top_left.x(),
                    global_card_top_left.y() - int(popup_size / Config.SHOT_CARD_ASPECT_RATIO) - 10
                )
            elif position_mode == "below":
                return QPoint(
                    global_card_top_left.x(),
                    global_card_top_left.y() + card_rect.height() + 10
                )

        # Default: cursor position
        return global_cursor_pos

    def cleanup(self):
        """Clean up resources."""
        self._hover_timer.stop()
        if self._preview_widget:
            self._preview_widget.hide_preview()
            self._preview_widget.close()
            self._preview_widget = None


class ShotCardRenderer:
    """
    Static methods for rendering shot cards with 16:9 aspect ratio.

    This delegates to the shot_card_renderer module for actual drawing.
    See: shot_library/views/renderers/shot_card_renderer.py
    """

    @staticmethod
    def get_thumbnail_pixmap(
        shot_data: dict,
        thumbnail_loader=None
    ) -> Optional[QPixmap]:
        """
        Get thumbnail pixmap for a shot.

        Uses ShotThumbnailLoader to extract frame from playblast video.

        Args:
            shot_data: Shot data dict
            thumbnail_loader: Optional ShotThumbnailLoader instance

        Returns:
            QPixmap or None if not yet loaded
        """
        if thumbnail_loader is None:
            from ..services.thumbnail_loader import get_shot_thumbnail_loader
            thumbnail_loader = get_shot_thumbnail_loader()

        shot_id = shot_data.get('uuid') or shot_data.get('id')
        folder_path = shot_data.get('folder_path')
        playblast_path = shot_data.get('latest_playblast_path')

        if not shot_id:
            return None

        # Try to load thumbnail
        if playblast_path:
            return thumbnail_loader.load_thumbnail_from_playblast(
                shot_id=shot_id,
                playblast_path=Path(playblast_path),
                frame_number=-1  # Middle frame
            )
        elif folder_path:
            return thumbnail_loader.load_shot_thumbnail(
                shot_id=shot_id,
                shot_folder=Path(folder_path)
            )

        return None


__all__ = ['ShotCardHoverHandler', 'ShotCardRenderer']
