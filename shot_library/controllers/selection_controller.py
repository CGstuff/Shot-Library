"""
SelectionController - Manages selection state across the application

This controller centralizes selection state management and ensures
consistent selection behavior across all UI components.

Usage:
    from shot_library.controllers import SelectionController

    controller = SelectionController()

    # Connect to signals
    controller.selection_changed.connect(on_selection_changed)
    controller.single_selection_changed.connect(on_single_selection)

    # Set selection
    controller.set_selection(['uuid1', 'uuid2'])
    controller.set_single_selection('uuid1')
"""

from typing import Optional, Set, List, Dict, Any

from PyQt6.QtCore import QObject, pyqtSignal

from ..events.event_bus import get_event_bus


class SelectionController(QObject):
    """
    Controller for managing selection state.

    This controller:
    - Tracks single and multi-selection state
    - Emits signals when selection changes
    - Coordinates with EventBus for global state
    - Provides selection data to other components

    Signals:
        selection_changed: Emitted when selection changes (Set[str])
        single_selection_changed: Emitted for single selection (str or '')
        selection_count_changed: Emitted when count changes (int)
    """

    # Controller signals
    selection_changed = pyqtSignal(set)  # Set[str] of selected UUIDs
    single_selection_changed = pyqtSignal(str)  # Single selected UUID or ''
    selection_count_changed = pyqtSignal(int)  # Count of selected items

    def __init__(self, event_bus=None, parent=None):
        """
        Initialize selection controller.

        Args:
            event_bus: EventBus instance (uses singleton if None)
            parent: Qt parent object
        """
        super().__init__(parent)

        self._event_bus = event_bus or get_event_bus()

        # Selection state
        self._selected_ids: Set[str] = set()
        self._single_selection: Optional[str] = None

        # Selected shot data (for metadata panel)
        self._selected_shot_data: Optional[Dict[str, Any]] = None

    @property
    def selected_ids(self) -> Set[str]:
        """Return set of selected shot UUIDs."""
        return self._selected_ids.copy()

    @property
    def selected_count(self) -> int:
        """Return count of selected items."""
        return len(self._selected_ids)

    @property
    def single_selection(self) -> Optional[str]:
        """Return single selected UUID, or None if none/multiple selected."""
        return self._single_selection

    @property
    def selected_shot_data(self) -> Optional[Dict[str, Any]]:
        """Return the data dict for the single selected shot."""
        return self._selected_shot_data

    @property
    def has_selection(self) -> bool:
        """Return True if any items are selected."""
        return len(self._selected_ids) > 0

    @property
    def has_single_selection(self) -> bool:
        """Return True if exactly one item is selected."""
        return len(self._selected_ids) == 1

    def set_selection(self, ids: Set[str], shot_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Set the current selection.

        Args:
            ids: Set of selected UUIDs
            shot_data: Optional data dict for single selected shot
        """
        if self._selected_ids == ids:
            return

        old_count = len(self._selected_ids)
        self._selected_ids = ids.copy()
        new_count = len(self._selected_ids)

        # Update single selection
        if len(ids) == 1:
            self._single_selection = next(iter(ids))
            self._selected_shot_data = shot_data
        else:
            self._single_selection = None
            self._selected_shot_data = None

        # Emit signals
        self.selection_changed.emit(self._selected_ids)
        self._event_bus.selected_shots_changed.emit(self._selected_ids)

        if self._single_selection:
            self.single_selection_changed.emit(self._single_selection)
            self._event_bus.selected_shot_changed.emit(self._single_selection)
        else:
            self.single_selection_changed.emit('')
            self._event_bus.selected_shot_changed.emit('')

        if old_count != new_count:
            self.selection_count_changed.emit(new_count)

    def set_single_selection(self, uuid: str, shot_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Set single item selection.

        Args:
            uuid: UUID of selected item
            shot_data: Optional data dict for the selected shot
        """
        self.set_selection({uuid} if uuid else set(), shot_data)

    def add_to_selection(self, uuid: str) -> None:
        """
        Add an item to the selection.

        Args:
            uuid: UUID to add
        """
        if uuid and uuid not in self._selected_ids:
            new_selection = self._selected_ids | {uuid}
            self.set_selection(new_selection)

    def remove_from_selection(self, uuid: str) -> None:
        """
        Remove an item from the selection.

        Args:
            uuid: UUID to remove
        """
        if uuid and uuid in self._selected_ids:
            new_selection = self._selected_ids - {uuid}
            self.set_selection(new_selection)

    def toggle_selection(self, uuid: str) -> None:
        """
        Toggle an item's selection state.

        Args:
            uuid: UUID to toggle
        """
        if uuid in self._selected_ids:
            self.remove_from_selection(uuid)
        else:
            self.add_to_selection(uuid)

    def clear_selection(self) -> None:
        """Clear all selection."""
        if self._selected_ids:
            self.set_selection(set())

    def select_all(self, all_ids: List[str]) -> None:
        """
        Select all items from a list.

        Args:
            all_ids: List of all UUIDs to select
        """
        self.set_selection(set(all_ids))

    def get_selected_ids_list(self) -> List[str]:
        """
        Return selected IDs as a list (ordered).

        Returns:
            List of selected UUIDs
        """
        return list(self._selected_ids)


__all__ = ['SelectionController']
