"""
ShotCardDelegate - QStyledItemDelegate for shot cards with 16:9 aspect ratio

Implements T089: Integrate VideoPreviewWidget with shot card renderer

Pattern: QStyledItemDelegate with custom painting
Adapted from: AnimationCardDelegate for shot domain
Key difference: 16:9 aspect ratio, playblast thumbnails, no gradient backgrounds

Lookdev support:
- Uses PreviewModeRole to determine which preview to show
- Preview mode is controlled globally from header toolbar (PB/LD buttons)
"""

from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PyQt6.QtCore import QModelIndex, QSize, QRect, Qt
from PyQt6.QtGui import QPainter, QColor, QPen

from .renderers.shot_card_renderer import ShotCardRenderer
from ..models.shot_list_model import ShotRole
from ..config import Config
from ..services.database_service import get_database_service
from ..services.thumbnail_loader import get_shot_thumbnail_loader
from ..themes.theme_manager import get_theme_manager


class ShotCardDelegate(QStyledItemDelegate):
    """
    Delegate for rendering shot cards with 16:9 aspect ratio.

    Implements T089: Draws shot cards with video frame thumbnails.

    Features:
    - 16:9 aspect ratio cards (video-native)
    - Playblast/Lookdev frame thumbnails (mode controlled from header)
    - Shot status badges
    - Editorial order display
    - Playblast/Lookdev version indicators
    - Parse warning indicators
    - Selection highlighting

    Usage:
        delegate = ShotCardDelegate(view)
        view.setItemDelegate(delegate)
    """

    def __init__(self, parent=None, db_service=None, thumbnail_loader=None,
                 theme_manager=None):
        super().__init__(parent)

        # Services (injectable for testing)
        self._db_service = db_service or get_database_service()
        self._thumbnail_loader = thumbnail_loader or get_shot_thumbnail_loader()
        self._theme_manager = theme_manager or get_theme_manager()

        # Card size
        self._card_size = Config.DEFAULT_CARD_SIZE

        # Text height for shot name
        self._text_height = 28

        # Connect thumbnail loader signals
        self._thumbnail_loader.thumbnail_loaded.connect(self._on_thumbnail_loaded)

    def set_card_size(self, size: int):
        """
        Set card width.

        Args:
            size: Card width in pixels
        """
        self._card_size = size

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """
        Return size hint for 16:9 shot card.

        Args:
            option: Style options
            index: Model index

        Returns:
            Size (width, height) for 16:9 card plus text area
        """
        height = ShotCardRenderer.calculate_card_height(self._card_size, include_text=True)
        return QSize(self._card_size, height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """
        Paint shot card.

        Args:
            painter: QPainter instance
            option: Style options
            index: Model index
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get theme palette
        theme = self._theme_manager.get_current_theme()
        palette = theme.palette if theme else None

        # Get shot data
        shot_name = index.data(ShotRole.NameRole) or "Unknown"
        shot_uuid = index.data(ShotRole.UUIDRole)
        status = index.data(ShotRole.StatusRole) or Config.SHOT_STATUS_WIP
        has_playblast = index.data(ShotRole.HasPlayblastRole)
        playblast_version = index.data(ShotRole.LatestPlayblastVersionRole)
        playblast_path = index.data(ShotRole.LatestPlayblastPathRole)
        parse_warning = index.data(ShotRole.ParseWarningRole)

        # Lookdev data
        has_lookdev = index.data(ShotRole.HasLookdevRole)
        lookdev_path = index.data(ShotRole.LatestLookdevPathRole)

        # Render data
        has_render = index.data(ShotRole.HasRenderRole)
        render_proxy_path = index.data(ShotRole.RenderProxyPathRole)

        preview_mode = index.data(ShotRole.PreviewModeRole) or "playblast"

        # Editorial order components
        episode_num = index.data(ShotRole.EpisodeNumRole)
        sequence_num = index.data(ShotRole.SequenceNumRole)
        scene_num = index.data(ShotRole.SceneNumRole)
        shot_num = index.data(ShotRole.ShotNumRole)

        # Selection state
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Thumbnail fills the entire cell width, text is separate below
        cell_rect = option.rect
        thumbnail_width = cell_rect.width()
        thumbnail_height = int(thumbnail_width / ShotCardRenderer.ASPECT_RATIO)

        thumbnail_rect = QRect(cell_rect.x(), cell_rect.y(), thumbnail_width, thumbnail_height)
        text_rect = QRect(cell_rect.x(), cell_rect.y() + thumbnail_height, thumbnail_width, self._text_height)

        # Draw entire card background first to prevent default selection fill from showing
        card_bg_color = QColor("#1e1e1e")  # Match view background
        painter.fillRect(cell_rect, card_bg_color)

        # Draw text area background (slightly different shade)
        text_bg_color = QColor("#1a1a1a")
        if palette:
            text_bg_color = QColor(palette.background_secondary)
        painter.fillRect(text_rect, text_bg_color)

        # Determine which video path to use based on preview mode
        if preview_mode == "render" and render_proxy_path:
            video_path = render_proxy_path
            has_preview = has_render
        elif preview_mode == "lookdev" and lookdev_path:
            video_path = lookdev_path
            has_preview = has_lookdev
        else:
            video_path = playblast_path
            has_preview = has_playblast

        # Draw thumbnail
        pixmap = None
        if shot_uuid and video_path:
            # Try to get thumbnail from cache or trigger async load
            folder_path = index.data(ShotRole.FolderPathRole)
            shot_data = {
                'uuid': shot_uuid,
                'folder_path': folder_path,
                'latest_playblast_path': video_path  # Used for thumbnail loading
            }
            pixmap = self._get_shot_thumbnail(shot_data)

        if pixmap and not pixmap.isNull():
            ShotCardRenderer.draw_shot_thumbnail(
                painter, thumbnail_rect, pixmap,
                theme_manager=self._theme_manager
            )
        else:
            # Draw placeholder - ALWAYS draw this when no valid pixmap
            if not has_preview:
                if preview_mode == "render":
                    placeholder_text = "No Render"
                elif preview_mode == "lookdev":
                    placeholder_text = "No Lookdev"
                else:
                    placeholder_text = "No Playblast"
            else:
                placeholder_text = "Loading..."
            # Ensure we draw the placeholder background to cover any default fill
            ShotCardRenderer.draw_placeholder(
                painter, thumbnail_rect, placeholder_text,
                theme_manager=self._theme_manager
            )

        # Draw shot name
        ShotCardRenderer.draw_shot_name(
            painter, text_rect, shot_name,
            palette=palette,
            is_selected=is_selected
        )

        # Note: Assignment badges and view count badges removed from cards to keep them clean.
        # Task/assignment info and camera views are displayed in the metadata panel instead.

        # Draw selection border around thumbnail
        if is_selected:
            painter.setPen(QPen(QColor("#5b8cc9"), 2))  # Selection border blue
            painter.drawRect(thumbnail_rect.adjusted(1, 1, -1, -1))

        painter.restore()

    def _get_shot_thumbnail(self, shot_data: dict):
        """
        Get thumbnail for a shot, loading async if not cached.

        Args:
            shot_data: Dict with uuid, folder_path, latest_playblast_path

        Returns:
            QPixmap or None
        """
        shot_id = shot_data.get('uuid')
        playblast_path = shot_data.get('latest_playblast_path')
        folder_path = shot_data.get('folder_path')

        if not shot_id:
            return None

        if playblast_path:
            return self._thumbnail_loader.load_thumbnail_from_playblast(
                shot_id=shot_id,
                playblast_path=Path(playblast_path),
                frame_number=-1  # Middle frame
            )
        elif folder_path:
            return self._thumbnail_loader.load_shot_thumbnail(
                shot_id=shot_id,
                shot_folder=Path(folder_path)
            )

        return None

    def _on_thumbnail_loaded(self, uuid: str, pixmap):
        """Handle async thumbnail load completion - trigger repaint.

        Uses the source model's uuid→row index for O(1) lookup; the previous
        linear scan made folder loads O(n²) on large libraries.
        """
        parent = self.parent()
        if not (parent and hasattr(parent, 'model')):
            return

        view_model = parent.model()
        if view_model is None:
            return

        # Unwrap a proxy if present so we can use the source's uuid index.
        source_model = view_model.sourceModel() if hasattr(view_model, 'sourceModel') else None
        if source_model is None:
            source_model = view_model

        if not hasattr(source_model, 'get_row_for_uuid'):
            return

        source_row = source_model.get_row_for_uuid(uuid)
        if source_row < 0:
            return

        source_index = source_model.index(source_row, 0)
        if view_model is source_model:
            view_index = source_index
        else:
            view_index = view_model.mapFromSource(source_index)
            if not view_index.isValid():
                return  # row is filtered out — nothing to repaint

        view_model.dataChanged.emit(view_index, view_index)


__all__ = ['ShotCardDelegate']
