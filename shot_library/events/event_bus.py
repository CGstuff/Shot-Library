"""
EventBus - Central event system for application-wide state management

Pattern: Observer/Publisher-Subscriber
Inspired by: Current animation_library EventBus with improvements
"""

import threading
from PyQt6.QtCore import QObject, pyqtSignal
from typing import Set, Optional


class EventBus(QObject):
    """
    Central event bus for decoupled communication between components

    Benefits:
    - Loose coupling between UI components
    - Single source of truth for application state
    - Easy to debug (all events flow through one place)
    - Type-safe with Qt signals

    Usage:
        event_bus = EventBus()
        event_bus.selected_animation_changed.connect(some_handler)
        event_bus.set_selected_animation("uuid-123")
    """

    # Animation selection events
    selected_animation_changed = pyqtSignal(str)  # animation_id
    selected_animations_changed = pyqtSignal(set)  # Set[animation_id]

    # Shot selection events (Shot Library specific)
    selected_shot_changed = pyqtSignal(str)  # shot_uuid
    selected_shots_changed = pyqtSignal(set)  # Set[shot_uuid]

    # View mode events
    view_mode_changed = pyqtSignal(str)  # "grid" or "list"
    card_size_changed = pyqtSignal(int)  # size in pixels

    # Edit mode events
    edit_mode_changed = pyqtSignal(bool)  # enabled/disabled

    # Folder navigation events
    folder_selected = pyqtSignal(str)  # folder_name
    folder_changed = pyqtSignal(int)  # folder_id - emitted when animations moved to folder

    # Search and filter events
    search_text_changed = pyqtSignal(str)  # search query
    filter_changed = pyqtSignal(dict)  # filter criteria

    # Theme events
    theme_changed = pyqtSignal(str)  # "light" or "dark"

    # Animation data events
    animation_added = pyqtSignal(str)  # animation_id
    animation_updated = pyqtSignal(str)  # animation_id
    animation_deleted = pyqtSignal(str)  # animation_id
    animations_bulk_updated = pyqtSignal(list)  # List[animation_id]

    # Archive events (first stage - soft delete)
    animation_archived = pyqtSignal(str)  # animation_id moved to archive
    animation_restored_from_archive = pyqtSignal(str)  # animation_id restored from archive to library
    archive_count_changed = pyqtSignal(int)  # new archive count

    # Trash events (second stage - hard delete staging)
    animation_moved_to_trash = pyqtSignal(str)  # animation_id moved from archive to trash
    animation_restored_to_archive = pyqtSignal(str)  # animation_id restored from trash to archive
    trash_item_deleted = pyqtSignal(str)  # animation_id permanently deleted
    trash_emptied = pyqtSignal()  # all trash items deleted
    trash_count_changed = pyqtSignal(int)  # new trash count

    # Tag events
    tags_updated = pyqtSignal(str, list)  # animation_id, tags

    # Review notes events (frame-specific notes for dailies)
    review_note_added = pyqtSignal(str, int)  # animation_uuid, note_id
    review_note_updated = pyqtSignal(str, int)  # animation_uuid, note_id
    review_note_deleted = pyqtSignal(str, int)  # animation_uuid, note_id
    review_note_resolved = pyqtSignal(str, int, bool)  # animation_uuid, note_id, resolved

    # Button state events
    apply_button_enabled = pyqtSignal(bool)
    delete_button_enabled = pyqtSignal(bool)

    # Loading state events
    loading_started = pyqtSignal(str)  # operation_name
    loading_finished = pyqtSignal(str)  # operation_name
    loading_progress = pyqtSignal(int, int)  # current, total

    # Error events
    error_occurred = pyqtSignal(str, str)  # error_type, error_message

    # Settings events
    settings_changed = pyqtSignal(str, object)  # setting_name, value

    # Filesystem change events (T151: FolderObserver integration)
    filesystem_changes_detected = pyqtSignal(list)  # List[FileSystemChange]
    filesystem_watch_started = pyqtSignal(str, str)  # watch_id, path
    filesystem_watch_stopped = pyqtSignal(str)  # watch_id
    filesystem_watch_error = pyqtSignal(str, str)  # watch_id, error_message
    filesystem_buffer_overflow = pyqtSignal(str)  # watch_id (polling fallback active)

    # Schema events (T155: Schema change triggers rescan)
    schema_changed = pyqtSignal(str)  # schema_id
    shots_rescan_requested = pyqtSignal()  # Request to rescan current folder

    # Shot scanning events (for ShotScanController)
    shot_scan_started = pyqtSignal(str)  # folder_path
    shot_scan_progress = pyqtSignal(int, int)  # current, total
    shot_scan_complete = pyqtSignal(object)  # result (list of shot_dicts)
    shot_scan_error = pyqtSignal(str)  # error_message
    folder_scan_requested = pyqtSignal(str)  # folder_path

    # Metadata events (for service boundary enforcement)
    metadata_changed = pyqtSignal(str)  # shot_uuid
    shot_status_changed = pyqtSignal(str, str, str)  # shot_uuid, old_status, new_status

    # Preview mode events
    preview_mode_changed = pyqtSignal(str)  # "playblast", "lookdev", or "render"
    shot_preview_mode_changed = pyqtSignal(str, str)  # shot_uuid, mode

    # Render management events
    render_discovered = pyqtSignal(str, object)  # shot_uuid, DiscoveredRender
    render_proxy_ready = pyqtSignal(str, str)  # shot_uuid, proxy_path
    render_archived = pyqtSignal(str, int)  # shot_uuid, version
    render_restored = pyqtSignal(str, int)  # shot_uuid, version
    render_job_queued = pyqtSignal(str, str)  # shot_uuid, job_id
    render_job_completed = pyqtSignal(str, bool)  # job_id, success

    def __init__(self):
        super().__init__()

        # State storage
        self._selected_animation_id: Optional[str] = None
        self._selected_animation_ids: Set[str] = set()
        self._selected_shot_id: Optional[str] = None
        self._selected_shot_ids: Set[str] = set()
        self._current_folder: str = "Home"
        self._view_mode: str = "grid"
        self._card_size: int = 160
        self._edit_mode: bool = False
        self._search_text: str = ""
        self._current_theme: str = "dark"

    # Getters (read current state)

    def get_selected_animation(self) -> Optional[str]:
        """Get currently selected animation ID (single selection)"""
        return self._selected_animation_id

    def get_selected_animations(self) -> Set[str]:
        """Get all selected animation IDs (multi-selection)"""
        return self._selected_animation_ids.copy()

    def get_current_folder(self) -> str:
        """Get current folder name"""
        return self._current_folder

    def get_view_mode(self) -> str:
        """Get current view mode ('grid' or 'list')"""
        return self._view_mode

    def get_card_size(self) -> int:
        """Get current card size"""
        return self._card_size

    def is_edit_mode(self) -> bool:
        """Check if edit mode is active"""
        return self._edit_mode

    def get_search_text(self) -> str:
        """Get current search text"""
        return self._search_text

    def get_current_theme(self) -> str:
        """Get current theme ('light' or 'dark')"""
        return self._current_theme

    # Setters (update state and emit signals)

    def set_selected_animation(self, animation_id: Optional[str]):
        """
        Set single selected animation

        Args:
            animation_id: UUID of animation, or None to clear selection
        """
        if self._selected_animation_id != animation_id:
            self._selected_animation_id = animation_id
            self.selected_animation_changed.emit(animation_id or "")

            # Update apply button state
            self.apply_button_enabled.emit(animation_id is not None)

    def set_selected_animations(self, animation_ids: Set[str]):
        """
        Set multiple selected animations (for multi-select)

        Args:
            animation_ids: Set of animation UUIDs
        """
        if self._selected_animation_ids != animation_ids:
            self._selected_animation_ids = animation_ids.copy()
            self.selected_animations_changed.emit(self._selected_animation_ids)

            # Update delete button state
            self.delete_button_enabled.emit(len(animation_ids) > 0)

    def set_folder(self, folder_name: str):
        """
        Set current folder

        Args:
            folder_name: Name of folder to select
        """
        if self._current_folder != folder_name:
            self._current_folder = folder_name
            self.folder_selected.emit(folder_name)

    def set_view_mode(self, mode: str):
        """
        Set view mode

        Args:
            mode: "grid" or "list"
        """
        if mode not in ("grid", "list"):
            raise ValueError(f"Invalid view mode: {mode}")

        if self._view_mode != mode:
            self._view_mode = mode
            self.view_mode_changed.emit(mode)

    def set_card_size(self, size: int):
        """
        Set card size for grid mode

        Args:
            size: Size in pixels (80-300)
        """
        if self._card_size != size:
            self._card_size = size
            self.card_size_changed.emit(size)

    def set_edit_mode(self, enabled: bool):
        """
        Set edit mode state

        Args:
            enabled: True to enable edit mode, False to disable
        """
        if self._edit_mode != enabled:
            self._edit_mode = enabled
            self.edit_mode_changed.emit(enabled)

    def set_search_text(self, text: str):
        """
        Set search query text

        Args:
            text: Search query
        """
        if self._search_text != text:
            self._search_text = text
            self.search_text_changed.emit(text)

    def set_theme(self, theme: str):
        """
        Set application theme

        Args:
            theme: "light" or "dark"
        """
        if theme not in ("light", "dark"):
            raise ValueError(f"Invalid theme: {theme}")

        if self._current_theme != theme:
            self._current_theme = theme
            self.theme_changed.emit(theme)

    # Convenience methods

    def clear_selection(self):
        """Clear all selections"""
        self.set_selected_animation(None)
        self.set_selected_animations(set())

    # Shot selection methods (Shot Library specific)

    def get_selected_shot(self) -> Optional[str]:
        """Get currently selected shot ID (single selection)"""
        return self._selected_shot_id

    def get_selected_shots(self) -> Set[str]:
        """Get all selected shot IDs (multi-selection)"""
        return self._selected_shot_ids.copy()

    def set_selected_shot(self, shot_id: Optional[str]):
        """
        Set single selected shot

        Args:
            shot_id: UUID of shot, or None to clear selection
        """
        if self._selected_shot_id != shot_id:
            self._selected_shot_id = shot_id
            self.selected_shot_changed.emit(shot_id or "")

    def set_selected_shots(self, shot_ids: Set[str]):
        """
        Set multiple selected shots (for multi-select)

        Args:
            shot_ids: Set of shot UUIDs
        """
        if self._selected_shot_ids != shot_ids:
            self._selected_shot_ids = shot_ids.copy()
            self.selected_shots_changed.emit(self._selected_shot_ids)

    def clear_shot_selection(self):
        """Clear all shot selections"""
        self.set_selected_shot(None)
        self.set_selected_shots(set())

    def report_error(self, error_type: str, message: str):
        """
        Report an error to the UI

        Args:
            error_type: Type of error (e.g., "database", "file_io", "validation")
            message: Human-readable error message
        """
        self.error_occurred.emit(error_type, message)

    def start_loading(self, operation: str):
        """Signal that a long operation has started"""
        self.loading_started.emit(operation)

    def finish_loading(self, operation: str):
        """Signal that a long operation has finished"""
        self.loading_finished.emit(operation)

    def update_progress(self, current: int, total: int):
        """Update progress of current operation"""
        self.loading_progress.emit(current, total)


# Singleton instance (lazy initialization with thread safety)
_event_bus_instance: Optional[EventBus] = None
_event_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """
    Get global EventBus singleton instance (thread-safe).

    Returns:
        Global EventBus instance
    """
    global _event_bus_instance
    if _event_bus_instance is None:
        with _event_bus_lock:
            # Double-check after acquiring lock
            if _event_bus_instance is None:
                _event_bus_instance = EventBus()
    return _event_bus_instance


# Export
__all__ = ['EventBus', 'get_event_bus']
