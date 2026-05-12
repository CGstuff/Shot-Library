"""
ShotView - QListView for shots with hover-to-play video preview

Implements tasks T089-T091:
- T089: Integrate VideoPreviewWidget with shot card renderer
- T090: Connect playblast indexer to shot discovery pipeline
- T091: Wire up hover events to trigger video preview

Pattern: QListView with Model/View architecture, adapted from AnimationView
Key difference: Shots display in fixed editorial order (no reordering)
"""

import os
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import QListView, QAbstractItemView
from PyQt6.QtCore import Qt, QTimer, QModelIndex, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QResizeEvent, QMouseEvent

from .shot_card_delegate import ShotCardDelegate
from ..models.shot_list_model import ShotRole
from ..services.database_service import get_database_service
from ..services.socket_client import get_socket_client
from ..events.event_bus import get_event_bus
from ..widgets.shot_video_preview import ShotVideoPreviewWidget
from ..widgets.shot_card import ShotCardHoverHandler
from ..config import Config


class ShotView(QListView):
    """
    View for displaying shots in grid mode with 16:9 cards

    Implements T089-T091:
    - T089: Integrates VideoPreviewWidget via ShotCardHoverHandler
    - T090: Connected to playblast discovery through shot data model
    - T091: Hover events trigger video preview after 500ms delay

    Implements T165 (Performance):
    - Virtual scrolling enabled via setUniformItemSizes(True)
    - Optimized for 2000+ shots with deferred rendering
    - Uses ScrollPerPixel for smooth scrolling

    Features:
    - Grid mode with 16:9 aspect ratio cards
    - Hover-to-play video preview
    - Fixed editorial order (no drag reordering)
    - Selection handling (single/multi)
    - Async thumbnail loading via delegate
    - Event bus integration
    - Virtual scrolling for large shot counts (2000+)

    Usage:
        view = ShotView()
        view.setModel(shot_filter_proxy_model)
    """

    # Signals
    shot_double_clicked = pyqtSignal(str)  # shot_uuid
    shot_context_menu = pyqtSignal(str, QPoint)  # shot_uuid, position
    hover_started = pyqtSignal(str, QPoint)  # shot_uuid, position
    hover_ended = pyqtSignal()

    def __init__(self, parent=None, db_service=None, event_bus=None,
                 thumbnail_loader=None, theme_manager=None):
        super().__init__(parent)

        # Services (injectable for testing)
        self._event_bus = event_bus or get_event_bus()
        self._db_service = db_service or get_database_service()

        # View mode (shots only support grid with 16:9 cards)
        self._card_size = Config.DEFAULT_CARD_SIZE

        # Delegate (pass through DI services)
        self._delegate = ShotCardDelegate(
            self,
            db_service=self._db_service,
            thumbnail_loader=thumbnail_loader,
            theme_manager=theme_manager
        )
        self.setItemDelegate(self._delegate)

        # Hover tracking for video preview (T091)
        self._hover_handler = ShotCardHoverHandler(self)
        self._hover_index: Optional[QModelIndex] = None
        self._last_hover_pos = QPoint()

        # Setup view
        self._setup_view()
        self._connect_signals()

    def _setup_view(self):
        """
        Configure view settings for 16:9 shot cards.

        T165: Virtual scrolling optimizations for 2000+ shots:
        - setUniformItemSizes(True) enables Qt's internal virtualization
        - ScrollPerPixel provides smooth scrolling experience
        - setLayoutMode(Batched) defers layout for large datasets
        - setBatchSize() controls items laid out per batch
        """
        # Remove default margins for tight-packed grid
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)

        # T165: Virtual scrolling for performance with 2000+ shots
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # T165: Uniform item sizes enables Qt's internal virtualization
        # Only visible items are rendered, critical for 2000+ shots
        self.setUniformItemSizes(True)

        # T165: Batched layout mode for deferred rendering
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(Config.BATCH_SIZE)  # Items per layout batch

        # Selection
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)

        # No drag & drop - shots have fixed editorial order
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

        # Mouse tracking for hover video preview
        self.setMouseTracking(True)

        # Performance: No alternating colors, handled in delegate
        self.setAlternatingRowColors(False)

        # Dark background for view, transparent items (selection handled in delegate)
        self.setStyleSheet("""
            QListView {
                background-color: #1e1e1e;
                border: none;
            }
            QListView::item {
                background-color: transparent;
            }
            QListView::item:selected {
                background-color: transparent;
            }
            QListView::item:hover {
                background-color: transparent;
            }
        """)

        # Grid mode for 16:9 cards
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(0)  # Use grid size padding instead
        # Grid size includes padding for visual separation between cards
        self.setGridSize(self._get_grid_size_with_padding())
        self.setMovement(QListView.Movement.Snap)

    def _connect_signals(self):
        """Connect internal signals."""
        # Double click
        self.doubleClicked.connect(self._on_double_clicked)

        # Event bus signals
        self._event_bus.card_size_changed.connect(self.set_card_size)

    def setModel(self, model):
        """Override setModel to connect selection signal."""
        old_selection_model = self.selectionModel()
        if old_selection_model:
            try:
                old_selection_model.selectionChanged.disconnect(self._on_selection_changed)
            except (RuntimeError, TypeError):
                pass

        super().setModel(model)

        new_selection_model = self.selectionModel()
        if new_selection_model:
            new_selection_model.selectionChanged.connect(self._on_selection_changed)

    def _get_grid_size_with_padding(self) -> QSize:
        """Get grid size with minimal padding."""
        card_size = self._delegate.sizeHint(None, QModelIndex())
        grid_padding = 4  # Minimal padding between cards
        return QSize(card_size.width() + grid_padding, card_size.height() + grid_padding)

    def set_card_size(self, size: int):
        """
        Set card size for grid.

        Args:
            size: Card width in pixels
        """
        self._card_size = size
        self._delegate.set_card_size(size)
        self.setGridSize(self._get_grid_size_with_padding())
        self.viewport().update()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for hover video preview (T091)."""
        super().mouseMoveEvent(event)

        if not Config.ENABLE_HOVER_VIDEO:
            return

        # Get index under mouse
        index = self.indexAt(event.pos())

        if index.isValid():
            if index != self._hover_index:
                # New item hovered
                self._hover_index = index
                self._last_hover_pos = event.pos()
                # Use hover handler (T091)
                self._hover_handler.on_hover(index, event.pos())
        else:
            # No item under mouse
            if self._hover_index:
                self._hover_index = None
                self._hover_handler.on_leave()
                self.hover_ended.emit()

    def leaveEvent(self, event):
        """Handle mouse leaving view - stop hover preview."""
        super().leaveEvent(event)

        if self._hover_index:
            self._hover_index = None
            self._hover_handler.on_leave()
            self.hover_ended.emit()

    def _on_hover_timeout(self):
        """Handle hover timer timeout - emit hover started signal."""
        if not self._hover_index or not self._hover_index.isValid():
            return

        uuid = self._hover_index.data(ShotRole.UUIDRole)
        if uuid:
            global_pos = self.viewport().mapToGlobal(self._last_hover_pos)
            self.hover_started.emit(uuid, global_pos)

    def _on_double_clicked(self, index: QModelIndex):
        """Handle double click on shot card."""
        if not index.isValid():
            return

        uuid = index.data(ShotRole.UUIDRole)
        if uuid:
            self.shot_double_clicked.emit(uuid)
            self._event_bus.set_selected_shot(uuid)

    def _on_selection_changed(self, selected, deselected):
        """Handle selection changes."""
        selected_indexes = self.selectionModel().selectedIndexes()
        selected_uuids = set()

        for index in selected_indexes:
            uuid = index.data(ShotRole.UUIDRole)
            if uuid:
                selected_uuids.add(uuid)

        # Update event bus
        if Config.ENABLE_MULTI_SELECT:
            self._event_bus.set_selected_shots(selected_uuids)

        if selected_uuids:
            last_uuid = list(selected_uuids)[-1]
            self._event_bus.set_selected_shot(last_uuid)
        else:
            self._event_bus.set_selected_shot(None)

    def contextMenuEvent(self, event):
        """Handle context menu."""
        index = self.indexAt(event.pos())
        if index.isValid():
            uuid = index.data(ShotRole.UUIDRole)
            if uuid:
                self.shot_context_menu.emit(uuid, event.globalPos())

    def resizeEvent(self, event: QResizeEvent):
        """Handle resize to adjust grid layout."""
        super().resizeEvent(event)
        self.setGridSize(self._get_grid_size_with_padding())

    def select_shot(self, uuid: str):
        """
        Select shot by UUID.

        Args:
            uuid: Shot UUID
        """
        model = self.model()
        if not model:
            return

        for row in range(model.rowCount()):
            index = model.index(row, 0)
            item_uuid = index.data(ShotRole.UUIDRole)
            if item_uuid == uuid:
                self.selectionModel().select(
                    index,
                    self.selectionModel().SelectionFlag.ClearAndSelect
                )
                self.scrollTo(index)
                break

    def clear_selection(self):
        """Clear all selections."""
        self.selectionModel().clearSelection()

    def get_selected_uuids(self) -> list[str]:
        """
        Get list of selected shot UUIDs.

        Returns:
            List of UUIDs (deduplicated)
        """
        selected_indexes = self.selectionModel().selectedIndexes()
        uuids = []
        seen = set()

        for index in selected_indexes:
            uuid = index.data(ShotRole.UUIDRole)
            if uuid and uuid not in seen:
                uuids.append(uuid)
                seen.add(uuid)

        return uuids

    def cleanup(self):
        """Clean up resources."""
        self._hover_handler.cleanup()


__all__ = ['ShotView']
